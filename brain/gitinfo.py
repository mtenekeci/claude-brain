"""Thin, timeout-guarded git wrappers. Every function returns an empty value on failure."""
import subprocess, time

def _git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True, timeout=3)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""

def current_branch(cwd):
    return _git(cwd, "branch", "--show-current").strip()

def head_sha(cwd):
    return _git(cwd, "rev-parse", "HEAD").strip()

def last_subject(cwd):
    return _git(cwd, "log", "-1", "--format=%s").strip()

def _since_today():
    return "--since=%s 00:00" % time.strftime("%Y-%m-%d")

def commits_today(cwd):
    out = _git(cwd, "log", _since_today(), "--format=%s")
    return [l for l in out.splitlines() if l.strip()][:5]

def changed_files_today(cwd):
    committed = [l for l in _git(cwd, "log", _since_today(), "--name-only", "--format=").splitlines() if l.strip()]
    status = []
    for l in _git(cwd, "status", "--short").splitlines():
        if len(l) > 3:
            f = l[3:].strip()
            if " -> " in f:
                f = f.split(" -> ")[-1]
            status.append(f)
    seen, out = set(), []
    for f in committed[:8] + status[:5]:
        if f not in seen:
            seen.add(f); out.append(f)
    return out
