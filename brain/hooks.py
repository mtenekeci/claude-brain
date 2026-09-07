"""Hook handlers. dispatch() is the only entry point; each on_<event> returns a HookResult.
Contract: never raise, never print outside brain projects."""
import os, re, shlex, subprocess, sys, traceback
from brain import config, project, state, vault, gitinfo

PROTOCOL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "protocol.md")
SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".rb", ".java", ".kt", ".swift",
               ".vue", ".svelte", ".c", ".cpp", ".cs", ".php", ".scala", ".m", ".mm", ".h")

class HookResult(object):
    def __init__(self, stdout="", json=None, exit_code=0):
        self.stdout, self.json, self.exit_code = stdout, json, exit_code

EMPTY = HookResult()

class Ctx(object):
    def __init__(self, payload, proj, vault_root):
        self.payload = payload
        self.session_id = str(payload.get("session_id") or "unknown")
        self.cwd = payload.get("cwd") or os.getcwd()
        self.project = proj
        self.vault = vault_root
        self.pdir = project.vault_project_dir(vault_root, proj.slug)
        self.context_path = os.path.join(self.pdir, "context.md")
        self.arch_path = os.path.join(self.pdir, "architecture.md")
        self.log_path = os.path.join(self.pdir, "log.md")
        self.state = None   # attached by dispatch() inside state.locked()

    def attach_state(self, s):
        self.state = s
        if not s.slug:
            s.slug, s.vault, s.project_dir = self.project.slug, self.vault, self.project.project_dir

def cli_command():
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__main__.py")
    return 'python3 "%s"' % main_py

def resolve_ctx(payload):
    vault_root = config.vault_root()
    if not vault_root:
        return None
    cwd = payload.get("cwd") or os.getcwd()
    proj = project.resolve_project(cwd)
    if proj is None:
        return None
    if payload.get("agent_id"):
        # inside a subagent: only SubagentStart/Stop-with-agent logic should ever act; handlers check this
        pass
    return Ctx(payload, proj, vault_root)

def dispatch(event, payload):
    try:
        handler = _HANDLERS.get(event)
        if handler is None:
            return EMPTY
        ctx = resolve_ctx(payload)
        if ctx is None:
            return EMPTY
        with state.locked(ctx.session_id) as s:
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
        return HookResult("Brain: project '%s' has no context.md at %s — run /brain init.\n" % (ctx.project.slug, ctx.pdir))
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
_COMMIT_RE = re.compile(r"(?:^|[;&|]\s*)git\s+commit\b(?![^;&|]*--dry-run)")

def is_source_path(path):
    return bool(path) and path.lower().endswith(SOURCE_EXTS)

def under(path, root):
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
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
    return p if os.path.isabs(p) else os.path.join(ctx.cwd, p)

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

def on_post_tool_use(ctx):
    tool = str(ctx.payload.get("tool_name") or "")
    ti = ctx.payload.get("tool_input") or {}
    if tool == "Bash":
        cmd = str(ti.get("command") or "")
        if is_git_commit(cmd):
            sha = gitinfo.head_sha(ctx.cwd)
            if not sha or sha == ctx.state.last_head_sha:
                return EMPTY                      # command ran but nothing was committed
            ctx.state.last_head_sha = sha
            subject = subprocess.run(["git", "-C", ctx.cwd, "log", "-1", "--format=%s"], capture_output=True, text=True, timeout=3).stdout.strip()
            ctx.state.note_commit(subject)
            branch = gitinfo.current_branch(ctx.cwd)
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

_HANDLERS = {
    "SessionStart": on_session_start,
}
_HANDLERS["PostToolUse"] = on_post_tool_use
