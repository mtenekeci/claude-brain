"""Hook handlers. dispatch() is the only entry point; each on_<event> returns a HookResult.
Contract: never raise, never print outside brain projects."""
import os, sys, traceback
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
        if os.environ.get("BRAIN_TEST_RAISE"):
            raise RuntimeError("test")
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
    migrated_line = ""
    try:
        from brain import migrate
        if migrate.needs_migration(ctx.project, ctx.vault):
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
    ctx.state.stop_blocks_this_turn = 0
    return HookResult("\n".join(parts) + "\n")

_HANDLERS = {
    "SessionStart": on_session_start,
}
