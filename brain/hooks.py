"""Hook handlers. dispatch() is the only entry point; each on_<event> returns a HookResult.
Contract: never raise, never print outside brain projects."""
import os, re, shlex, time, traceback
from brain import config, project, state, vault, gitinfo

PROTOCOL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "protocol.md")
_SOFT_EDIT_THRESHOLD = 5        # soft-tier Stop gate: uncommitted source edits before nudging
from brain.codemap import SOURCE_EXTS

class HookResult(object):
    def __init__(self, stdout="", json=None, exit_code=0):
        self.stdout, self.json, self.exit_code = stdout, json, exit_code

EMPTY = HookResult()

class Ctx(object):
    def __init__(self, payload, proj, vault_root):
        self.payload = payload
        self.session_id = str(payload["session_id"])   # resolve_ctx guarantees both are
        self.cwd = str(payload["cwd"])                 # non-empty strings; no ambient fallback
        self.project = proj
        self.vault = vault_root
        self.pdir = project.vault_project_dir(vault_root, proj.slug)
        self.context_path = os.path.join(self.pdir, "context.md")
        self.arch_path = os.path.join(self.pdir, "architecture.md")
        self.log_path = os.path.join(self.pdir, "log.md")
        self.state = None   # attached by dispatch() inside state.locked()
        self.pre = {}       # facts gathered by handler.prepare() BEFORE the lock is taken

    def attach_state(self, s):
        # Invariant: slug/vault/project_dir are back-filled exactly once per session and
        # never change afterwards — later events reuse the identity the first event recorded.
        self.state = s
        if not s.slug:
            s.slug, s.vault, s.project_dir = self.project.slug, self.vault, self.project.project_dir

def cli_command():
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__main__.py")
    return 'python3 "%s"' % main_py

def _nonempty_str(payload, key):
    v = payload.get(key)
    return v if isinstance(v, str) and v else None

def resolve_ctx(payload):
    """None unless the payload is a well-formed hook payload for a configured brain project.
    A malformed payload must never fall back to the ambient cwd or a shared session id."""
    if not isinstance(payload, dict):
        return None
    cwd = _nonempty_str(payload, "cwd")
    if not cwd or not _nonempty_str(payload, "session_id"):
        return None
    vault_root = config.vault_root()
    if not vault_root:
        return None
    proj = project.resolve_project(cwd)
    if proj is None:
        return None
    return Ctx(payload, proj, vault_root)

def dispatch(event, payload):
    try:
        handler = _HANDLERS.get(event)
        if handler is None:
            return EMPTY
        ctx = resolve_ctx(payload)
        if ctx is None:
            return EMPTY
        # Pre-lock phase: a handler's optional prepare() does the slow, lock-free work
        # (subprocesses, I/O) so the locked body below stays short. ctx.state is still None here.
        prepare = getattr(handler, "prepare", None)
        if prepare is not None:
            ctx.pre = prepare(ctx) or {}
        # SessionEnd runs against a 1 s hook timeout: never wait on a peer that holds the lock.
        timeout = 0.5 if event == "SessionEnd" else None
        with state.locked(ctx.session_id, timeout=timeout) as s:
            ctx.attach_state(s)
            result = handler(ctx)
        return result or EMPTY
    except Exception:
        config.log_error("%s failed: %s" % (event, traceback.format_exc().strip().splitlines()[-1]))
        return EMPTY

def _protocol(ctx):
    text = vault.read(PROTOCOL_PATH)
    return text.replace("{BRAIN}", cli_command()).replace("{SLUG}", ctx.project.slug)

def _banner(title):
    return "═" * 63 + "\n" + title + "\n" + "═" * 63 + "\n"

def on_session_start(ctx):
    source = str(ctx.payload.get("source") or "startup")
    state.prune(days=7)
    ctx.state.stop_blocks_this_turn = 0
    migrated_line = ""
    try:
        try:
            from brain import migrate
        except ImportError:         # module not installed yet — nothing to migrate
            migrate = None
        if migrate is not None and migrate.needs_migration(ctx.project, ctx.vault):
            actions = migrate.migrate_project(ctx.project, ctx.vault, ctx.project.project_dir)
            if actions:
                ctx.project = project.resolve_project(ctx.project.project_dir) or ctx.project
                migrated_line = "Brain: migrated %s to v2 layout (%s). Run /brain sync once to reconcile concepts." % (ctx.project.slug, ", ".join(actions))
    except Exception as e:          # migration must never suppress injection
        config.log_error("migration failed for %s: %r" % (ctx.project.slug, e))
    if ctx.state.log_entries_at_start < 0:
        ctx.state.log_entries_at_start = vault.count_log_entries(vault.read(ctx.log_path))
    if not ctx.state.last_head_sha:
        ctx.state.last_head_sha = gitinfo.head_sha(ctx.cwd)
    parts = [_protocol(ctx).rstrip("\n"), ""]
    context_text = vault.read(ctx.context_path)
    if not context_text:
        msg = "Brain: project '%s' has no context.md at %s — run /brain init.\n" % (ctx.project.slug, ctx.pdir)
        return HookResult(migrated_line + "\n" + msg if migrated_line else msg)
    parts.append(_banner("VAULT FILE: " + ctx.context_path) + context_text.rstrip("\n"))
    last = vault.last_log_entry(vault.read(ctx.log_path))
    if last:
        parts += ["", _banner("VAULT FILE: %s (last entry only)" % ctx.log_path) + last]
    if os.path.exists(ctx.arch_path):
        parts += ["", "Tier 2 (read by section, on demand): " + ctx.arch_path]
    if source in ("compact", "resume"):
        fm, _ = vault.parse_frontmatter(context_text)
        expected = fm.get("branch") or "unset"
        parts += ["", "Brain: context re-injected after %s; branch is %s (expected: %s)" % (
            source, gitinfo.current_branch(ctx.cwd) or "?", expected)]
    if migrated_line:
        parts += ["", migrated_line]
    return HookResult("\n".join(parts) + "\n")

_READ_CMDS = ("cat", "sed", "head", "tail", "less", "bat", "more")
# Deliberately permissive (matches `git commit --dry-run`, `git commit` in a message): the
# real guard is on_post_tool_use's HEAD-moved check, which ignores commands that landed nothing.
_COMMIT_RE = re.compile(r"\bgit\s+commit\b")

def is_source_path(path):
    return bool(path) and path.lower().endswith(SOURCE_EXTS)

def under(path, root):
    """True when path is inside root. Both sides are realpath'd so a symlinked vault or
    project root (e.g. /var -> /private/var on macOS) still compares equal."""
    try:
        rroot = os.path.realpath(root)
        return os.path.commonpath([os.path.realpath(path), rroot]) == rroot
    except ValueError:
        return False

def bash_read_targets(cmd):
    out = []
    for seg in re.split(r"[;&|]+", cmd or ""):
        try:
            toks = shlex.split(seg.strip())
        except ValueError:
            continue
        if toks and toks[0] in _READ_CMDS:
            out += [t for t in toks[1:] if not t.startswith("-") and is_source_path(t)]
    return out

def is_git_commit(cmd):
    return bool(_COMMIT_RE.search(cmd or ""))

def _abs(ctx, p):
    # realpath: cwd itself can be a symlink into the project, and the resulting path is
    # both compared against roots (under) and stored in state for later _rel().
    p = p if os.path.isabs(p) else os.path.join(ctx.cwd, p)
    return os.path.realpath(p)

def _read_nudge(ctx):
    s = ctx.state
    bucket = min(s.reads // 3, 3)
    if bucket <= s.last_nudge_bucket:
        return EMPTY
    quiet_since_last = (s.last_nudge_bucket == 0) or (s.vault_writes == s.vault_writes_at_last_nudge)
    s.last_nudge_bucket = bucket
    s.vault_writes_at_last_nudge = s.vault_writes
    if not quiet_since_last:
        return EMPTY
    return HookResult("Brain: %d source files read — add what you learned to %s (+ a codemap Modules row if it's a module). Concept note only if you'd link it from more than one place.\n" % (s.reads, ctx.arch_path))

def _prepare_post_tool_use(ctx):
    """Runs BEFORE the session lock: all git subprocess calls for this event live here."""
    ti = ctx.payload.get("tool_input") or {}
    if str(ctx.payload.get("tool_name") or "") != "Bash" or not is_git_commit(str(ti.get("command") or "")):
        return {}
    return {"sha": gitinfo.head_sha(ctx.cwd), "branch": gitinfo.current_branch(ctx.cwd), "subject": gitinfo.last_subject(ctx.cwd)}

def on_post_tool_use(ctx):
    tool = str(ctx.payload.get("tool_name") or "")
    ti = ctx.payload.get("tool_input") or {}
    if tool == "Bash":
        cmd = str(ti.get("command") or "")
        if is_git_commit(cmd):
            pre = ctx.pre                         # gathered by _prepare_post_tool_use, outside the lock
            sha = pre.get("sha", "")
            if not sha or sha == ctx.state.last_head_sha:
                return EMPTY                      # command ran but nothing was committed
            ctx.state.last_head_sha = sha
            ctx.state.note_commit(pre.get("subject", ""))
            branch = pre.get("branch", "")
            text = vault.read(ctx.context_path)
            if text and branch:
                fm, _ = vault.parse_frontmatter(text)
                if fm.get("branch") != branch:
                    vault.write(ctx.context_path, vault.set_frontmatter(text, "branch", branch))
            return HookResult("Brain: commit landed — update ## State and ## Active Work in %s before continuing.\n" % ctx.context_path)
        hit = False
        for p in bash_read_targets(cmd):
            ap = _abs(ctx, p)
            if not under(ap, ctx.vault):
                ctx.state.note_read(); hit = True
        return _read_nudge(ctx) if hit else EMPTY
    if tool == "Read":
        p = _abs(ctx, str(ti.get("file_path") or ""))
        if is_source_path(p) and not under(p, ctx.vault):
            ctx.state.note_read()
            return _read_nudge(ctx)
        return EMPTY
    if tool in ("Edit", "Write", "MultiEdit"):
        p = _abs(ctx, str(ti.get("file_path") or ""))
        if under(p, ctx.vault):
            ctx.state.note_vault_write()
        elif is_source_path(p) and under(p, ctx.project.project_dir):
            ctx.state.note_source_edit(p)
        return EMPTY
    return EMPTY

on_post_tool_use.prepare = _prepare_post_tool_use

_HANDLERS = {
    "SessionStart": on_session_start,
}
_HANDLERS["PostToolUse"] = on_post_tool_use

def gate_decision(s, mode, stop_hook_active, agent_id, last_msg):
    """Return a block reason, or None. Pure: no I/O."""
    if mode == "off" or stop_hook_active or agent_id or s.stop_blocks_this_turn:
        return None
    k, m = s.commits_since_vault_write, s.source_edits_since_vault_write
    hard = k > 0
    soft = mode == "all" and m >= _SOFT_EDIT_THRESHOLD and not (last_msg or "").rstrip().endswith("?")
    if not (hard or soft):
        return None
    what = []
    if k: what.append("%d commit%s" % (k, "" if k == 1 else "s"))
    if m: what.append("%d source edit%s" % (m, "" if m == 1 else "s"))
    return ("Brain: this turn landed %s with no vault update. Edit ## State + ## Active Work in %s "
            "(and append a log.md entry if a task completed), then finish." % (" and ".join(what), "{context}"))

def on_stop(ctx):
    reason = gate_decision(ctx.state, config.gate_mode(), bool(ctx.payload.get("stop_hook_active")),
                           ctx.payload.get("agent_id"), str(ctx.payload.get("last_assistant_message") or ""))
    if reason is None:
        return EMPTY
    ctx.state.stop_blocks_this_turn = 1
    if ctx.state.source_edits_since_vault_write >= _SOFT_EDIT_THRESHOLD:
        ctx.state.source_edits_since_vault_write = 0   # soft tier resets after firing (spec §7.7)
    return HookResult(json={"decision": "block", "reason": reason.replace("{context}", ctx.context_path)})

def on_user_prompt_submit(ctx):
    # A <task-notification> prompt is a background-subagent completion notice, not a user
    # turn (spec §3/§7.2) — it must not clear a block the current turn already earned.
    if not str(ctx.payload.get("prompt") or "").lstrip().startswith("<task-notification>"):
        ctx.state.stop_blocks_this_turn = 0
    return EMPTY   # Plan 2 adds per-prompt graph retrieval here

_HANDLERS["Stop"] = on_stop
_HANDLERS["UserPromptSubmit"] = on_user_prompt_submit

def _rel(ctx, p):
    # Both sides realpath'd so a symlinked cwd yields "src/x.ts", never "../../repolink/src/x.ts".
    try:
        return os.path.relpath(os.path.realpath(p), os.path.realpath(ctx.project.project_dir))
    except ValueError:
        return p

def _changed_line(ctx, with_git):
    files = [_rel(ctx, p) for p in ctx.state.edited_files]
    if with_git:
        files += [f for f in gitinfo.changed_files_today(ctx.cwd) if f not in files]
    line = " ".join(files)
    if len(line) > 200:
        cut = line.rfind(" ", 0, 200)          # never truncate mid-path
        line = line[:cut] if cut > 0 else line[:200]
    return line or "—"

def _completed_line(ctx):
    return "; ".join(ctx.state.commit_subjects) if ctx.state.commit_subjects else "—"

def _append_entry(ctx, tag, with_git):
    text = vault.read(ctx.log_path)
    if not text or vault.last_entry_is_placeholder(text):
        return False
    if (tag == "auto-close" and ctx.state.log_entries_at_start >= 0
            and vault.count_log_entries(text) != ctx.state.log_entries_at_start):
        return False                       # a real entry (e.g. /brain sync) was already written this session
    n = vault.count_log_entries(text) + 1
    entry = vault.format_log_entry(time.strftime("%Y-%m-%d"), n, _completed_line(ctx), _changed_line(ctx, with_git), "none", "—", tag=tag)
    vault.append(ctx.log_path, entry)
    return True

def on_pre_compact(ctx):
    if not vault.read(ctx.log_path):
        return HookResult("BRAIN SYNC: no log.md for '%s' at %s — run /brain init before compacting.\n" % (ctx.project.slug, ctx.log_path))
    wrote = _append_entry(ctx, "pre-compact", with_git=True)
    if wrote:
        return HookResult("BRAIN SYNC: checkpoint written to %s. NOW fill in Completed and Decided with real session detail, then update ## State and ## Active Work in %s before the compact proceeds.\n" % (ctx.log_path, ctx.context_path))
    return HookResult("BRAIN SYNC: a checkpoint already exists in %s — enrich its Completed/Decided fields, then update context.md.\n" % ctx.log_path)

def on_session_end(ctx):
    s = ctx.state
    if s.commits + s.source_edits + s.vault_writes > 0:
        _append_entry(ctx, "auto-close", with_git=False)
    s.discard = True
    s.delete()
    return EMPTY

_HANDLERS["PreCompact"] = on_pre_compact
_HANDLERS["SessionEnd"] = on_session_end
