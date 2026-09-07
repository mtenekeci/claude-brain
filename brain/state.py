"""Per-session counters used by hooks. One JSON file per Claude session_id under the plugin data dir."""
import contextlib, fcntl, json, os, time
from brain import config

_DEFAULTS = dict(
    slug="", vault="", project_dir="", started_at=0.0,
    reads=0, source_edits=0, commits=0, vault_writes=0,
    last_work_at=0.0, last_vault_write=0.0,
    edited_files=[], commit_subjects=[], injected=[],
    commits_since_vault_write=0, source_edits_since_vault_write=0,
    stop_blocks_this_turn=0, codemap_stale=False, backend_fallbacks=0,
    last_head_sha="", log_entries_at_start=-1, last_nudge_bucket=0, vault_writes_at_last_nudge=0,
)

def _sessions_dir():
    d = os.path.join(config.data_dir(), "sessions")
    os.makedirs(d, exist_ok=True)
    return d

class SessionState(object):
    def __init__(self, session_id, data=None):
        self.session_id = session_id
        d = dict(_DEFAULTS)
        d["edited_files"], d["commit_subjects"], d["injected"] = [], [], []
        d.update(data or {})
        for k, v in d.items():
            setattr(self, k, v)

    @property
    def path(self):
        safe = "".join(c for c in self.session_id if c.isalnum() or c in "-_") or "unknown"
        return os.path.join(_sessions_dir(), safe + ".json")

    @classmethod
    def load(cls, session_id):
        s = cls(session_id)
        try:
            with open(s.path) as f:
                s = cls(session_id, json.load(f))
        except (OSError, ValueError):
            pass
        if not s.started_at:
            s.started_at = time.time()
        return s

    def save(self):
        data = {k: getattr(self, k) for k in _DEFAULTS}
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)

    def delete(self):
        """Remove only the JSON state file. Never unlink the .lock file: locked()
        may still hold flock on that inode (e.g. SessionEnd calling delete() from
        inside locked()), and removing it would let a concurrent locked() open a
        fresh lock file and proceed unexcluded."""
        try:
            os.remove(self.path)
        except OSError:
            pass

    def note_read(self):
        self.reads += 1

    def note_source_edit(self, path):
        self.source_edits += 1
        self.source_edits_since_vault_write += 1
        self.last_work_at = time.time()
        if path and path not in self.edited_files:
            self.edited_files.append(path)
        self.codemap_stale = True

    def note_commit(self, subject):
        self.commits += 1
        self.commits_since_vault_write += 1
        self.last_work_at = time.time()
        if subject:
            self.commit_subjects.append(subject)

    def note_vault_write(self):
        self.vault_writes += 1
        self.last_vault_write = time.time()
        self.commits_since_vault_write = 0
        self.source_edits_since_vault_write = 0

@contextlib.contextmanager
def locked(session_id):
    """Exclusive read-modify-write of one session's state. Holds the lock for the whole block."""
    probe = SessionState(session_id)
    lock_path = probe.path + ".lock"
    with open(lock_path, "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            s = SessionState.load(session_id)
            s.discard = False
            yield s
            if not s.discard:
                s.save()
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

def prune(days=7):
    """Remove stale session files. .json files older than the cutoff are removed
    outright. .lock files older than the cutoff are only removed if an exclusive,
    non-blocking flock on them succeeds (i.e. nothing currently holds the lock);
    otherwise they are left alone so a live locked() block is never undermined."""
    cutoff = time.time() - days * 86400
    for name in os.listdir(_sessions_dir()):
        p = os.path.join(_sessions_dir(), name)
        try:
            if os.path.getmtime(p) >= cutoff:
                continue
            if name.endswith(".lock"):
                with open(p, "a") as f:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except (OSError, BlockingIOError):
                        continue
                    try:
                        os.remove(p)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            else:
                os.remove(p)
        except OSError:
            pass
