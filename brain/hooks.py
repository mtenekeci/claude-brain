"""Hook handlers. dispatch() is the only entry point; each on_<event> returns a HookResult.
Contract: never raise, never print outside brain projects."""
import os, re, shlex, subprocess, sys, time, traceback
from brain import briefing, codemap, config, graph, project, retrieve, state, vault, gitinfo

PROTOCOL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "protocol.md")
_SOFT_EDIT_THRESHOLD = 5        # soft-tier Stop gate: uncommitted source edits before nudging
_INJECTED_CAP = 300             # bound on ctx.state.injected — a long session must not grow this file forever

class HookResult(object):
    def __init__(self, stdout="", json=None, exit_code=0, after_lock=None):
        self.stdout, self.json, self.exit_code = stdout, json, exit_code
        # after_lock: a zero-arg callable dispatch() runs once the session lock is released.
        # For work a handler can only *decide* under the lock (it needs state) but must not
        # *do* there — today: the detached `map --regen` spawn.
        self.after_lock = after_lock

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

# Ceiling on how long dispatch() waits for the session lock, per event, in seconds. Every event
# has one: an unbounded wait is indistinguishable from a hang, and Claude Code's own hook
# deadline is then the only thing that ends it — at which point the output is discarded anyway,
# so waiting past the budget buys nothing and costs the whole event. Each budget leaves the rest
# of that event's hook timeout (hooks/hooks.json) for the handler's own work. Peers hold the
# lock for ~1 ms, since the slow work happens in prepare() before it, so these are ~1000x the
# contention we expect to see and should never trip in normal use.
_LOCK_WAIT = {
    "SessionEnd": 0.5,          # 1 s deadline: never wait on a peer at all
    "SessionStart": 6.0,        # 10 s deadline
    "PreCompact": 6.0,          # 10 s deadline
    "UserPromptSubmit": 10.0,   # 15 s deadline
}
_LOCK_WAIT_DEFAULT = 3.0        # the 5 s-deadline events: PostToolUse, Stop, PreToolUse, SubagentStart

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
        timeout = _LOCK_WAIT.get(event, _LOCK_WAIT_DEFAULT)
        try:
            with state.locked(ctx.session_id, timeout=timeout) as s:
                ctx.attach_state(s)
                result = handler(ctx)
        except state.LockBusy:
            # Skipping loses this event's state update — a retrieval, an edit count, a gate
            # check. That is the lesser loss: the alternative is to keep waiting until Claude
            # Code kills the hook, which discards the same output and stalls the turn to boot.
            # Logged rather than silent so a real contention bug stays visible in brain.log.
            config.log_error("%s skipped: session lock busy after %.1fs" % (event, timeout))
            return EMPTY
        result = _deliverable(event, result or EMPTY)
        if result.after_lock is not None:
            try:
                result.after_lock()
            except Exception as e:      # post-lock work is best-effort: never cost the event
                config.log_error("%s after_lock failed: %r" % (event, e))
        return result
    except Exception:
        config.log_error("%s failed: %s" % (event, traceback.format_exc().strip().splitlines()[-1]))
        return EMPTY

# Events whose plain stdout is transcript-only — the model never sees it. Measured in
# SMOKE.md check 10 against Claude Code 2.1.263: a PostToolUse reminder written to stdout
# does not reach the turn (the same miss that cost us SubagentStop), while the identical text
# in hookSpecificOutput.additionalContext does. SessionStart and UserPromptSubmit DO inject
# stdout and are deliberately not listed; nothing is added here that has not been measured.
_ADDITIONAL_CONTEXT_EVENTS = ("PostToolUse",)


def _deliverable(event, result):
    """Re-address a stdout-only result onto the channel its event actually delivers.

    `stdout` is kept alongside the JSON: __main__ prefers `json`, so nothing is emitted twice,
    and handlers plus their tests keep reading the text off one field."""
    if event not in _ADDITIONAL_CONTEXT_EVENTS or result.json is not None or not result.stdout:
        return result
    return HookResult(stdout=result.stdout, exit_code=result.exit_code, after_lock=result.after_lock,
                      json={"hookSpecificOutput": {"hookEventName": event, "additionalContext": result.stdout}})


def _protocol(ctx):
    text = vault.read(PROTOCOL_PATH)
    return text.replace("{BRAIN}", cli_command()).replace("{SLUG}", ctx.project.slug)

def _banner(title):
    return "═" * 63 + "\n" + title + "\n" + "═" * 63 + "\n"

_REGEN_MIN_INTERVAL = 60.0

def _spawn_regen_process(project_dir, force=False):
    """Fire-and-forget `map --regen` in a detached process. Touches no session state, so it can
    run either before the lock (SessionStart's prepare) or after it (PostToolUse's after_lock) —
    never inside, where a Popen would stretch a 1 ms critical section into tens of ms."""
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__main__.py")
    argv = [sys.executable, main_py, "map", "--regen"] + (["--force"] if force else []) + ["--quiet"]
    try:
        subprocess.Popen(argv, cwd=project_dir,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception as e:      # Popen can raise more than OSError (bad argv types, ValueError)
        config.log_error("spawn regen failed: %r" % e)
        return False
    return True

def _finish_regen_spawn(session_id, project_dir, key):
    """Run the detached build outside the lock, then release the claim if it never started.

    The claim is recorded optimistically under the main lock (two SessionStarts must not both
    spawn), which on its own would remember a failed Popen as a spawn — and then `compact` and
    `resume` would never retry. Re-opening the lock for two field writes is cheap; the Popen
    itself has already happened by then, so nothing heavy runs inside it."""
    if _spawn_regen_process(project_dir, force=True):
        return
    try:
        # Bounded like every other acquisition: this runs after the main lock is released but
        # still inside the hook process, so an unbounded wait here would spend the deadline the
        # event has already earned. Losing the undo only costs a retry of a background rebuild.
        with state.locked(session_id, timeout=_LOCK_WAIT_DEFAULT) as s:
            if s.regen_spawned_for == key:      # only undo OUR claim, never a newer one
                s.regen_spawned_for = ""
                s.last_regen_spawn_at = 0.0
    except Exception as e:
        config.log_error("could not release regen claim: %r" % e)

def _claim_regen_slot(ctx, enabled):
    """Rate limit, under the lock: True at most once a minute per session, and only when
    background regeneration is enabled. Records the claim so a peer event cannot re-spawn;
    the caller performs the actual Popen outside the lock."""
    if not enabled:
        return False
    now = time.time()
    if now - ctx.state.last_regen_spawn_at < _REGEN_MIN_INTERVAL:
        return False
    ctx.state.last_regen_spawn_at = now
    return True

def _prepare_session_start(ctx):
    """Everything slow or git-touching for SessionStart runs here, BEFORE the session lock."""
    # os.listdir + getmtime + remove over the whole sessions dir. Harmless in isolation, but it
    # is I/O, and the one rule of the locked body is that it holds none. Nothing here depends on
    # this session's state, and prune is mtime-based, so a session started seconds ago is safe.
    state.prune(days=7)
    # log.md is read ONCE per event: the locked body needs the last entry and prepare needs the
    # entry count, and re-reading it under the lock put file I/O in the critical section.
    log_text = vault.read(ctx.log_path)
    pre = {"migrated_line": "", "large": False, "top": "", "health": "", "head_sha": gitinfo.head_sha(ctx.cwd),
           "log_entries": vault.count_log_entries(log_text), "last_entry": vault.last_log_entry(log_text),
           "refreshed": False, "regen_key": "", "branch": gitinfo.current_branch(ctx.cwd)}
    try:
        from brain import migrate
    except ImportError:         # module not installed yet — nothing to migrate
        migrate = None
    try:
        if migrate is not None and migrate.needs_migration(ctx.project, ctx.vault):
            actions = migrate.migrate_project(ctx.project, ctx.vault, ctx.project.project_dir)
            if actions:
                ctx.project = project.resolve_project(ctx.project.project_dir) or ctx.project
                pre["migrated_line"] = "Brain: migrated %s to v2 layout (%s). Run /brain sync once to reconcile concepts." % (ctx.project.slug, ", ".join(actions))
    except Exception as e:      # migration must never suppress injection
        config.log_error("migration failed for %s: %r" % (ctx.project.slug, e))
    try:
        # One `git ls-files` for the whole event: the size check, ensure() and regenerate()
        # all read this list instead of walking the tree again.
        files = codemap.list_files(ctx.project.project_dir)
        pre["large"] = len(files) >= codemap.LARGE_REPO_FILES
        if pre["large"]:
            # A full build_layer() here would read every source file synchronously before the
            # user's first prompt (the tree render alone is O(n^2) in the file count). Write the
            # scaffold; the detached --force regen fills it in.
            codemap.ensure_stub(ctx.project.project_dir, ctx.pdir)
            if config.async_regen():
                # The Popen itself is decided under the lock (on_session_start) and performed
                # after it, so `compact`/`resume` in the same session cannot each spawn one.
                pre["regen_key"] = codemap.freshness_key(ctx.project.project_dir, files)
                # "Large" is a size test, not a freshness test. A detached regen from an earlier
                # SessionStart in this same session may already have filled the map in, and a
                # compact/resume afterwards must neither re-spawn nor claim the map is deferred.
                #
                # The signal is codemap.md's own generated block, NOT .brain/codelayer.json: the
                # layer's sha is a git fingerprint that does not move when ensure_stub writes an
                # empty block, so a stale stub sitting next to a current layer would read as
                # fresh. The stub's marker carries `sha=` blank and no tree; a real regen writes
                # both. Read pre-lock, like everything else here.
                stored_sha, generated, _ = codemap.split_codemap(
                    vault.read(os.path.join(ctx.pdir, "codemap.md")))
                pre["map_generated"] = bool(generated.strip())
                pre["map_fresh"] = pre["map_generated"] and stored_sha == pre["regen_key"]
                pre["want_regen"] = not pre["map_fresh"]
            else:
                # No background process will ever fill the stub in, so the foreground build is
                # the only path left — an empty code map all session is the worse trade.
                codemap.regenerate(ctx.project.project_dir, ctx.pdir, files=files)
                pre["built_sync"] = True
        else:
            codemap.ensure(ctx.project.project_dir, ctx.pdir, files=files)
            codemap.regenerate(ctx.project.project_dir, ctx.pdir, files=files)
        pre["refreshed"] = True
    except Exception as e:
        config.log_error("codemap refresh failed: %r" % e)
    g = None
    try:
        g = graph.load(ctx.vault, ctx.project.slug, ctx.project.project_dir)
        pre["top"] = graph.render_top(g, graph.top(g, n=graph.TOP_LIMIT, near=graph.node_id("project", ctx.project.slug))).rstrip("\n")
    except Exception as e:
        config.log_error("graph load failed: %r" % e)
    if g is not None:
        try:
            from brain import lint                     # Task 11
            pre["health"] = lint.health_line(lint.run(ctx.vault, ctx.project.slug, ctx.project.project_dir, g))
        except ImportError:
            pass
        except Exception as e:                         # lint is advisory — never cost the injection
            config.log_error("lint failed: %r" % e)
    return pre

def _graph_lines(ctx):
    lines = []
    if ctx.pre.get("top"):
        lines += ["", "Brain: most-connected nodes for %s — `%s graph near <id>` for a neighborhood, `graph find <term>` before grepping code:" % (ctx.project.slug, cli_command()), ctx.pre["top"]]
    if ctx.pre.get("health"):
        lines += ["", ctx.pre["health"]]
    return lines

def on_session_start(ctx):
    """Locked body: state mutation + output assembly only. All heavy work already ran in
    _prepare_session_start(). context.md is read HERE (not in prepare) because lint's
    auto-apply may have just rewritten it."""
    source = str(ctx.payload.get("source") or "startup")
    ctx.state.stop_blocks_this_turn = 0
    migrated_line = ctx.pre.get("migrated_line", "")
    if ctx.state.log_entries_at_start < 0:
        ctx.state.log_entries_at_start = ctx.pre.get("log_entries", 0)
    if not ctx.state.last_head_sha:
        ctx.state.last_head_sha = ctx.pre.get("head_sha", "")
    # Stale unless the refresh actually ran to completion: an exception in prepare left the
    # code map untouched, which is exactly the case a "fresh" flag would hide. A large repo
    # whose code map is already current is NOT deferred — nothing is missing from it.
    deferred = (bool(ctx.pre.get("large")) and not ctx.pre.get("built_sync")
                and not ctx.pre.get("map_fresh"))
    ctx.state.codemap_stale = deferred or not ctx.pre.get("refreshed")
    after_lock = None
    if ctx.pre.get("want_regen"):
        key = ctx.pre.get("regen_key", "")
        # Once per session-state lifetime unless the tree moved: `compact` and `resume` re-fire
        # SessionStart against the same state file and would otherwise each spawn a build. The
        # claim is taken here, optimistically, so two events cannot both spawn;
        # _finish_regen_spawn releases it again if the Popen turns out to have failed.
        if ctx.state.regen_spawned_for != key:
            ctx.state.regen_spawned_for = key
            ctx.state.last_regen_spawn_at = time.time()
            project_dir, session_id = ctx.project.project_dir, ctx.session_id
            after_lock = lambda: _finish_regen_spawn(session_id, project_dir, key)
    parts = [_protocol(ctx).rstrip("\n"), ""]
    context_text = vault.read(ctx.context_path)
    if not context_text:
        msg = "Brain: project '%s' has no context.md at %s — run /brain init.\n" % (ctx.project.slug, ctx.pdir)
        return HookResult(migrated_line + "\n" + msg if migrated_line else msg, after_lock=after_lock)
    # Bytes, not lines: an 81 KB context.md in 128 lines passes the line cap and then buries
    # every line below it — the graph hints, the health line, the migration notice.
    shown, over_kb = vault.for_injection(context_text)
    parts.append(_banner("VAULT FILE: " + ctx.context_path) + shown.rstrip("\n"))
    if over_kb:
        parts += ["", "Brain: context.md truncated at %d KB — trim it (/brain sync)" % (vault.INJECT_BYTE_CAP // 1024)]
    last = ctx.pre.get("last_entry", "")                # read once, in prepare
    if last:
        last_shown, last_over_kb = vault.for_injection(last)
        parts += ["", _banner("VAULT FILE: %s (last entry only)" % ctx.log_path) + last_shown]
        if last_over_kb:
            parts += ["", "Brain: last log entry truncated at %d KB — trim it (/brain sync)" % (vault.INJECT_BYTE_CAP // 1024)]
    if os.path.exists(ctx.arch_path):
        parts += ["", "Tier 2 (read by section, on demand): " + ctx.arch_path]
    parts += _graph_lines(ctx)
    if over_kb:
        # Next to the health line, not only next to the cut: this is the actionable half —
        # the file is too big and only /brain sync can shrink it.
        parts += ["", "Brain: context.md oversize: %d KB" % over_kb]
    if deferred:
        # Two different states reach here: no generated block at all (a fresh stub), and a
        # complete-but-stale one. Saying "holds only the curated block" in the second case is
        # simply false — the map is there, it just predates the current tree. The flag comes
        # from prepare; re-reading codemap.md here would be file I/O inside the lock.
        what = ("codemap.md is stale — it describes an earlier commit" if ctx.pre.get("map_generated")
                else "codemap.md holds only the curated block for now")
        parts += ["", "Brain: code map deferred — this repo has %d+ tracked files, so %s. Run "
                      "`%s map --regen` if you need the current generated tree this session."
                  % (codemap.LARGE_REPO_FILES, what, cli_command())]
    if source in ("compact", "resume"):
        fm, _ = vault.parse_frontmatter(context_text)
        expected = fm.get("branch")
        line = "Brain: context re-injected after %s; branch is %s" % (source, ctx.pre.get("branch") or "?")
        if expected:
            line += " (expected: %s)" % expected
        parts += ["", line]
        # PreCompact/SessionEnd write their checkpoint with placeholder Completed/Decided lines.
        # No model turn runs between the PreCompact hook and the compaction itself, so the hook's
        # own stdout can only be acted on here, after the fact — this is the first turn that can.
        if last and vault.last_entry_is_placeholder(last):
            parts += ["", "Brain: the last log entry is a checkpoint with placeholder Completed/Decided lines — "
                          "fill them in with real session detail now, then update ## State and ## Active Work in %s."
                      % ctx.context_path]
    if migrated_line:
        parts += ["", migrated_line]
    return HookResult("\n".join(parts) + "\n", after_lock=after_lock)

on_session_start.prepare = _prepare_session_start

_READ_CMDS = ("cat", "sed", "head", "tail", "less", "bat", "more")
# Deliberately permissive (matches `git commit --dry-run`, `git commit` in a message): the
# real guard is on_post_tool_use's HEAD-moved check, which ignores commands that landed nothing.
_COMMIT_RE = re.compile(r"\bgit\s+commit\b")

def is_source_path(path):
    return bool(path) and path.lower().endswith(codemap.SOURCE_EXTS)

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

def _vault_notes_reminder(ctx):
    return ("Brain: subagent reported vault notes — fold them into %s / codemap.md ## Modules now "
            "(a concept note only if you'd link it from more than one place).\n" % ctx.arch_path)

def vault_mtime(pdir):
    """Newest .md mtime under the vault project dir, or 0.0 if there is nothing to stat.
    Dot-directories are skipped: `.brain/` holds the graph cache the plugin writes itself, and
    counting that as a vault update would clear the Stop gate on the plugin's own bookkeeping."""
    newest = 0.0
    for root, dirs, files in os.walk(pdir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.endswith(".md"):
                continue
            try:
                m = os.stat(os.path.join(root, f)).st_mtime
            except OSError:
                continue
            if m > newest:
                newest = m
    return newest

def _prepare_post_tool_use(ctx):
    """Runs BEFORE the session lock: all git subprocess calls, stats and config reads for this event."""
    ti = ctx.payload.get("tool_input") or {}
    tool = str(ctx.payload.get("tool_name") or "")
    if tool in ("Edit", "Write", "MultiEdit"):
        return {"async_regen": config.async_regen()}
    if tool != "Bash":
        return {}
    # PostToolUse runs after the command did its work, so this stat already reflects any vault
    # file the command touched.
    pre = {"vault_mtime": vault_mtime(ctx.pdir)}
    if is_git_commit(str(ti.get("command") or "")):
        pre.update(sha=gitinfo.head_sha(ctx.cwd), branch=gitinfo.current_branch(ctx.cwd),
                   subject=gitinfo.last_subject(ctx.cwd))
    return pre

def _note_bash_vault_write(ctx):
    """Count a vault edit made through the shell — a heredoc, `sed -i`, `{BRAIN} sync`. None of
    those pass through Edit/Write, so tool-name detection misses them and
    `commits_since_vault_write` never clears; the gate then re-fires against a vault that is
    already current. Arbitrate on mtime, the way commits arbitrate on HEAD: whatever moved the
    newest mtime, it was a write. The first Bash call of a session adopts the baseline without
    counting it — there is nothing yet to compare against."""
    m = ctx.pre.get("vault_mtime") or 0.0
    seen = ctx.state.vault_mtime_seen
    if m:
        ctx.state.vault_mtime_seen = m
    if seen and m > seen:
        ctx.state.note_vault_write()

# Both names for a subagent dispatch: `Agent` is the documented tool name, `Task` is what
# several Claude Code builds actually put in tool_name. hooks/hooks.json matches both.
AGENT_TOOLS = ("Agent", "Task")


def on_post_tool_use(ctx):
    tool = str(ctx.payload.get("tool_name") or "")
    ti = ctx.payload.get("tool_input") or {}
    if tool in AGENT_TOOLS:
        # A foreground subagent's result lands in the PARENT turn, which is the only place the
        # notes can actually be written. (SubagentStop's output never reached it — SMOKE.md #10.)
        if "Vault notes:" in str(ctx.payload.get("tool_response") or ""):
            return HookResult(_vault_notes_reminder(ctx))
        return EMPTY
    if tool == "Bash":
        # Before the commit accounting below: a command that updated the vault AND committed
        # still leaves the gate armed for that commit, which is the conservative reading.
        _note_bash_vault_write(ctx)
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
                    # Our own write. Re-baseline, or the next Bash call reads it as the user
                    # updating the vault and clears the gate this commit just armed.
                    ctx.state.vault_mtime_seen = vault_mtime(ctx.pdir)
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
            # Keep the shell-side baseline level with the write we just counted, so the next
            # Bash call does not count this same edit a second time.
            ctx.state.vault_mtime_seen = vault_mtime(ctx.pdir)
        elif is_source_path(p) and under(p, ctx.project.project_dir):
            ctx.state.note_source_edit(p)
            # Decided (and rate-limited) under the lock because it reads session state; spawned
            # after it. No --force: the fingerprint already reflects uncommitted edits.
            if _claim_regen_slot(ctx, ctx.pre.get("async_regen")):
                project_dir = ctx.project.project_dir
                return HookResult(after_lock=lambda: _spawn_regen_process(project_dir))
        return EMPTY
    return EMPTY

on_post_tool_use.prepare = _prepare_post_tool_use

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

def _prepare_user_prompt_submit(ctx):
    """Pre-lock: classify the prompt, then tokenise it and build/load the graph. The locked body
    only reads and writes session state and renders what is already in memory. A sign-off or a
    subagent completion notice short-circuits BEFORE the graph load: neither can earn a
    retrieval, and loading the graph to throw it away is the most expensive no-op we have."""
    prompt = str(ctx.payload.get("prompt") or "")
    done = retrieve.is_done_signal(prompt)
    notes = prompt.lstrip().startswith("<task-notification>") and "Vault notes:" in prompt
    if done or notes or retrieve.is_system_prompt(prompt):
        return {"done": done, "notes": notes}
    terms = retrieve.tokens(prompt)
    if not terms:
        return {}
    try:
        g = graph.load(ctx.vault, ctx.project.slug, ctx.project.project_dir)
    except Exception as e:
        config.log_error("retrieval graph load failed: %r" % e); return {}
    return {"graph": g, "terms": terms}

def on_user_prompt_submit(ctx):
    # A <task-notification> prompt is a background-subagent completion notice, not a user
    # turn (spec §3/§7.2) — it must not clear a block the current turn already earned.
    prompt = str(ctx.payload.get("prompt") or "")
    if not prompt.lstrip().startswith("<task-notification>"):
        ctx.state.stop_blocks_this_turn = 0
    if ctx.pre.get("notes"):
        # A background subagent finished and reported vault notes; this notice is the parent's
        # only sight of them.
        return HookResult(_vault_notes_reminder(ctx))
    if retrieve.is_system_prompt(prompt):
        return EMPTY
    s = ctx.state
    already = set(s.injected)
    if ctx.pre.get("done") and (s.commits_since_vault_write + s.source_edits_since_vault_write) > 0:
        return HookResult("Brain: user signalled done — write the log entry and update ## State / ## Active Work in %s now.\n" % ctx.context_path)
    g, terms = ctx.pre.get("graph"), ctx.pre.get("terms")
    if g is None or not terms:
        return EMPTY
    nodes = retrieve.select(g, terms, already)
    if not nodes:
        return EMPTY
    text, ids = retrieve.render_with_ids(g, nodes)
    if not text:
        return EMPTY
    merged = list(s.injected) + [i for i in ids if i not in already]
    seen = set()
    merged = [i for i in merged if not (i in seen or seen.add(i))]
    s.injected = merged[-_INJECTED_CAP:]
    return HookResult(text)

on_user_prompt_submit.prepare = _prepare_user_prompt_submit

def _rel(ctx, p):
    # Both sides realpath'd so a symlinked cwd yields "src/x.ts", never "../../repolink/src/x.ts".
    try:
        return os.path.relpath(os.path.realpath(p), os.path.realpath(ctx.project.project_dir))
    except ValueError:
        return p

def _changed_line(ctx, with_git):
    files = [_rel(ctx, p) for p in ctx.state.edited_files]
    if with_git:                                  # gathered pre-lock by _prepare_pre_compact
        files += [f for f in (ctx.pre.get("git_changed") or []) if f not in files]
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

def _prepare_pre_compact(ctx):
    """Pre-lock: the only git call PreCompact makes."""
    return {"git_changed": gitinfo.changed_files_today(ctx.cwd)}

def on_pre_compact(ctx):
    if not vault.read(ctx.log_path):
        return HookResult("BRAIN SYNC: no log.md for '%s' at %s — run /brain init before compacting.\n" % (ctx.project.slug, ctx.log_path))
    wrote = _append_entry(ctx, "pre-compact", with_git=True)
    if wrote:
        return HookResult("BRAIN SYNC: checkpoint written to %s. After compaction, fill in its Completed and Decided lines with real session detail, then update ## State and ## Active Work in %s.\n" % (ctx.log_path, ctx.context_path))
    return HookResult("BRAIN SYNC: a checkpoint already exists in %s — after compaction, enrich its Completed/Decided lines, then update context.md.\n" % ctx.log_path)

def on_session_end(ctx):
    s = ctx.state
    if s.commits + s.source_edits + s.vault_writes > 0:
        _append_entry(ctx, "auto-close", with_git=False)
    s.discard = True
    s.delete()
    return EMPTY

on_pre_compact.prepare = _prepare_pre_compact

# The cheap gate in front of the parser: a `git` token and, in the same segment, a later `push`
# token. NOT `\bgit\s+push\b` — that required them to be adjacent, so every shape git itself
# accepts a global option in (`git -c x=y push`, `git -C . push`, `git --no-pager push`,
# `git -P push`, `git --work-tree=. push`) never reached `push_targets`, which has parsed those
# correctly all along. The lookarounds exclude `-`, so `git-lfs` and `push-notify` are not `git`
# and `push`; splitting on `[\n;|&]` keeps the two tokens inside one command.
_GIT_TOKEN_RE = re.compile(r"(?<![\w-])git(?![\w-])")
_PUSH_TOKEN_RE = re.compile(r"(?<![\w-])push(?![\w-])")
_GATE_SPLIT_RE = re.compile(r"[\n;|&]")
_CONTINUATION_RE = re.compile(r"\\\n[ \t]*")
_MAIN_RULE_RE = re.compile(r"never\s+.*commit.*\bto\b.*\b(main|master)\b", re.I)
_PUSH_VALUE_OPTS = ("-o", "--push-option", "--receive-pack", "--exec")
# Options that push branches the command never names — the branch rules cannot be applied.
_BROAD_PUSH_OPTS = ("--all", "--mirror", "--branches")
# git global options that can appear before the `push` subcommand and would otherwise hide it.
_GIT_GLOBAL_VALUE_OPTS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")
_GIT_GLOBAL_FLAG_OPTS = ("--no-pager", "-P", "--no-optional-locks")
_REDIR_RE = re.compile(r"^\d*[<>]{1,2}(&\d+)?$")
# `VAR=value` prefixes sit between the segment start and the command word, exactly like
# env/command/sudo do: `GIT_SSH=x git push` is still a push.
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Words that can stand between the start of a segment and the command word without changing
# what the command is, and that take no arguments of their own. The shell keywords matter
# because `if git push origin main; then …` and `while ! git push …; do …; done` are shapes an
# agent writes unprompted — `if`/`while`/`until` sit in COMMAND position, so a segment starting
# with one is a real command with a keyword bolted on the front.
_WRAPPERS = ("then", "do", "else", "elif", "if", "while", "until", "{", "}", "!")
# These take their OWN arguments before the command word (`timeout 30 …`, `sudo -u x …`,
# `env -i …`), so stripping the wrapper word alone leaves `30 git push …` and the segment reads
# as "not a git command". The parser skips ahead to the first token that could be the real
# command word — a bare `git`, or an interpreter whose argument it can parse one level deep.
_ARG_WRAPPERS = ("env", "command", "sudo", "nohup", "time", "timeout", "xargs")
_SHELLS = ("bash", "sh", "zsh", "dash", "ksh")

def _join_continuations(cmd):
    r"""Fold a `\`-newline line continuation back into one line. `git \<newline>push origin main`
    is one command to Bash, and both the gate and the segment splitter read a newline as a break."""
    return _CONTINUATION_RE.sub(" ", cmd or "")

def looks_like_push(cmd):
    """Cheap "is this worth parsing at all" test, shared by the PreToolUse gate and its prepare
    phase. Deliberately permissive — `push_targets` is what decides, and it returns [] for a
    command that merely mentions a push."""
    # Two linear token searches per separator-split segment. A single lazy regex spanning
    # both tokens is quadratic on a long separator-free line, and this runs on every Bash call.
    for seg in _GATE_SPLIT_RE.split(_join_continuations(cmd)):
        m = _GIT_TOKEN_RE.search(seg)
        if m and _PUSH_TOKEN_RE.search(seg, m.end()):
            return True
    return False

def _mentions_push(text):
    """`git` token followed later by a `push` token, linear time (see looks_like_push)."""
    m = _GIT_TOKEN_RE.search(text or "")
    return bool(m and _PUSH_TOKEN_RE.search(text, m.end()))
# A segment that is a `git push` the parser cannot resolve to concrete branch names. It is a
# TARGET, not a branch: `on_pre_tool_use` denies on it outright. The distinction matters — the
# obvious "conservative fallback", the current branch, is exactly the value both deny rules
# treat as permitted (`t != expected` is false when `branch:` frontmatter matches the checked-out
# branch, which is what /brain sync writes), so returning it was behaviourally an ALLOW.
UNPARSED = "<unparsed>"

_SEPARATORS = ";|&\n()"

def split_segments(cmd):
    """Split a Bash command into command segments on UNQUOTED separators.

    `||`/`&&` count as one separator each (not two bare `|`/`&`); `;`, a bare pipe, a bare `&`
    (backgrounding), a newline — a multi-line body hides a push on its second line otherwise —
    and `(`/`)`, so a subshell's or a `$(…)`'s body becomes its own segment.

    Quote-aware, which a regex split cannot be: a plain `re.split` cut
    `git push origin main --push-option="ref (x)"` in half at the paren INSIDE the quoted
    argument, and the resulting half-segment no longer tokenised — turning a push the guard used
    to catch into one it could not read.

    Command substitution is the exception to that quote-awareness, and it has to be: `"` does not
    suppress `$(…)` or a backtick in Bash, so `echo "$(git push origin main)"` and
    `out="$(git push …)"` really do run the push. Those two open a segment whatever the quote
    state (single quotes excepted — there they are literal), which is why `--push-option="ref (x)"`
    survives: its paren has no `$` in front of it.
    """
    segs, buf, quote = [], [], ""
    stack = []                          # ("(" or "`", quote state to restore on close)
    i, n = 0, len(cmd or "")

    def cut():
        segs.append("".join(buf))
        del buf[:]

    while i < n:
        ch = cmd[i]
        escaped = i > 0 and cmd[i - 1] == "\\" and (i < 2 or cmd[i - 2] != "\\")
        if quote != "'" and not escaped and cmd.startswith("$(", i):
            cut(); stack.append(("(", quote)); quote = ""; i += 2; continue
        if quote != "'" and not escaped and ch == "`":
            cut()
            if stack and stack[-1][0] == "`":
                quote = stack.pop()[1]
            else:
                stack.append(("`", quote)); quote = ""
            i += 1; continue
        if quote == "" and ch == ")" and stack and stack[-1][0] == "(":
            cut(); quote = stack.pop()[1]; i += 1; continue
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(cmd[i + 1]); i += 2; continue     # \" inside "…" is a literal quote
            if ch == quote:
                quote = ""
            i += 1; continue
        if ch == "\\" and i + 1 < n:
            buf.append(ch); buf.append(cmd[i + 1]); i += 2; continue
        if ch in "'\"":
            quote = ch; buf.append(ch); i += 1; continue
        if cmd.startswith("||", i) or cmd.startswith("&&", i):
            cut(); i += 2; continue
        if ch in _SEPARATORS:
            cut(); i += 1; continue
        buf.append(ch); i += 1
    cut()
    return segs

def _is_redir(t):
    return bool(_REDIR_RE.match(t)) or t in ("&>", "&>>")

# `<<WORD`, `<<-WORD`, `<<'WORD'`. The lookarounds keep a `<<<` herestring out of it on BOTH
# sides: `(?!<)` alone still matched the 2nd and 3rd `<` of `<<<WORD`, so `git push <<< x`
# swallowed the rest of the command.
_HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*[\"']?(\w+)[\"']?")

def _strip_heredocs(cmd):
    """Drop heredoc bodies: their lines are data for the command, not commands themselves, so
    `cat <<EOF ... git push origin main ... EOF` is not a push. A `<<` with no matching
    terminator line is not a heredoc (it is a `<<` inside a quoted string) — nothing is dropped
    then, because swallowing lines would blind the push guard."""
    lines = (cmd or "").split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for word in _HEREDOC_RE.findall(line):
            j = i
            # `.strip()`, not an exact match: real Bash only allows a leading-tab-indented
            # terminator for the `<<-` form. Being lenient for plain `<<WORD` can only ever
            # end a heredoc EARLY, which un-hides commands — the safe direction for a guard.
            while j < len(lines) and lines[j].strip() != word:
                j += 1
            if j < len(lines):
                i = j + 1               # skip the body and its terminator
    return "\n".join(out)

def _nested_payload(toks):
    """The command string a segment hands to another interpreter, or None.

    `bash -c '…'` (and `sh -lc '…'`, combined short flags included) and `eval …` both run their
    argument as a command. `eval`'s arguments are concatenated by the shell, so joining them back
    is the same string it would run — losing a layer of quoting, which can only cost a false DENY.
    """
    if not toks:
        return None
    if toks[0] == "eval":
        return " ".join(toks[1:])
    if os.path.basename(toks[0]) in _SHELLS:
        for i, t in enumerate(toks[1:], 1):
            if t.startswith("-") and not t.startswith("--") and "c" in t[1:]:
                return toks[i + 1] if i + 1 < len(toks) else ""
    return None

def _is_command_word(t):
    """Could this token be the command an arg-taking wrapper is about to run?"""
    return t == "git" or t == "eval" or os.path.basename(t) in _SHELLS

def push_targets(cmd, current_branch, _depth=0):
    """Branch names a Bash command would push to. Parses real `git push` segments only (never
    quoted/echoed text).

    Two rules govern every judgement call below: a false DENY costs the user one confirmation,
    a false ALLOW lets a forbidden push land. So a segment that is plainly a `git push` but whose
    targets cannot be resolved yields `UNPARSED` rather than [] — `on_pre_tool_use` reads an
    empty list as "not a push at all", and reads `UNPARSED` as "deny and say why".
    """
    targets = []

    def add(names):
        for n in names:
            if n and n not in targets:
                targets.append(n)

    for seg in split_segments(_strip_heredocs(_join_continuations(cmd))):
        try:
            toks = shlex.split(seg.strip(), comments=True)
        except ValueError:
            # Unbalanced quotes the segment splitter could not keep together. Dropping the
            # segment silently is exactly the false ALLOW this guard exists to prevent.
            if _mentions_push(seg):
                add([UNPARSED])
            continue
        opaque = wrapped = False
        while toks:
            if toks[0] in _WRAPPERS or _ASSIGN_RE.match(toks[0]):
                toks = toks[1:]; continue
            if toks[0] in _ARG_WRAPPERS:
                # Skip the wrapper AND its own arguments (`-u x`, `30`, `-i`) to the first token
                # that could be the command it runs. Nothing else in the segment can be it, so
                # a segment with no such token is opaque rather than "not a push".
                nxt = next((i for i, t in enumerate(toks[1:], 1) if _is_command_word(t)), None)
                if nxt is None:
                    toks, opaque = [], True
                else:
                    toks, wrapped = toks[nxt:], True
                    continue                    # the new head may be another wrapper
            break
        if opaque:
            add([UNPARSED] if _mentions_push(seg) else [])
            continue
        payload = _nested_payload(toks)
        if payload is not None:
            # Exactly one level deep: the nested string is parsed as a command in its own right
            # (so `bash -c 'git push origin main'` reports main, not a guess), and anything the
            # nested parse cannot see through is unresolved — never "no push".
            nested = push_targets(payload, current_branch, _depth + 1) if _depth < 1 else []
            add(nested or ([UNPARSED] if _mentions_push(payload) else []))
            continue
        if not toks or toks[0] != "git":
            # `wrapped` means the first-candidate scan above picked the command word, and it was
            # not a push after all — `sudo -u git git push …` picks the OPTION VALUE `git`. The
            # scan cannot tell the two apart, so the segment is unresolved, not "no push".
            if wrapped and _mentions_push(seg):
                add([UNPARSED])
            continue
        idx = 1
        while idx < len(toks) and toks[idx] != "push":
            t = toks[idx]
            if t in _GIT_GLOBAL_VALUE_OPTS:
                idx += 2; continue
            if any(t.startswith(p + "=") for p in _GIT_GLOBAL_VALUE_OPTS):
                idx += 1; continue
            if t in _GIT_GLOBAL_FLAG_OPTS:
                idx += 1; continue
            break
        if idx >= len(toks) or toks[idx] != "push":
            if wrapped and _mentions_push(seg):
                add([UNPARSED])
            continue
        positional, skip, broad = [], False, False
        for t in toks[idx + 1:]:
            if skip:
                skip = False; continue
            if _is_redir(t):
                if t.endswith(">") or t.endswith("<"):
                    skip = True     # drop the redirection's filename too
                continue
            # An attached redirection token (`>out.log`, `<<EOF`, `2>&1`) is shell syntax, not a
            # refspec — `git push <<EOF` used to be read as a push to a branch named "<<EOF".
            if t.startswith(("<", ">")) or re.match(r"^\d+[<>]", t):
                continue
            if t in _PUSH_VALUE_OPTS:
                skip = True; continue
            if t.startswith("-"):
                # `--all`/`--mirror` push every local branch, `main` among them, without naming
                # one. The "no refspec means the current branch" rule below is simply wrong for
                # them, and wrong in the allow direction.
                broad = broad or t in _BROAD_PUSH_OPTS
                continue
            positional.append(t)
        refspecs = positional[1:] if positional else []
        names = []
        for r in refspecs:
            r = r.lstrip("+")
            dst = r.split(":", 1)[1] if ":" in r else r
            dst = current_branch if dst == "HEAD" else dst
            if dst.startswith("refs/tags/"):
                continue        # a tag push targets no branch; the branch-mismatch rule cannot apply
            names.append(dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst)
        if not refspecs:
            names.append(UNPARSED if broad else current_branch)
        add(names)
    return targets

def _prepare_pre_tool_use(ctx):
    """Pre-lock: the branch lookup for a push, and the whole graph hint for a Grep/Glob.
    PreToolUse fires on every matching tool call, so its locked body must stay trivial."""
    ti = ctx.payload.get("tool_input") or {}
    tool = str(ctx.payload.get("tool_name") or "")
    if tool == "Bash" and looks_like_push(str(ti.get("command") or "")):
        return {"branch": gitinfo.current_branch(ctx.cwd)}
    if tool in ("Grep", "Glob"):
        term = _search_term(str(ti.get("pattern") or ""))
        if not term:
            return {}
        try:
            g = graph.load(ctx.vault, ctx.project.slug, ctx.project.project_dir)
        except Exception as e:
            config.log_error("pretool graph load failed: %r" % e); return {}
        out = graph.render_find(g, graph.find(g, term, limit=9), limit=9)
        return {"hint": "Brain: graph already knows —\n" + out.rstrip("\n")} if out else {}
    return {}

def _deny(reason):
    return HookResult(json={"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}})

def _search_term(pattern):
    toks = [t.strip("./-") for t in re.sub(r"[^\w./-]+", " ", pattern or "").split()]
    toks = [t for t in toks if len(t) >= 3]
    return max(toks, key=len) if toks else ""

def on_pre_tool_use(ctx):
    tool = str(ctx.payload.get("tool_name") or ""); ti = ctx.payload.get("tool_input") or {}
    if tool == "Bash":
        cmd = str(ti.get("command") or "")
        if not looks_like_push(cmd):
            return EMPTY
        targets = push_targets(cmd, ctx.pre.get("branch", ""))
        if not targets:
            return EMPTY
        if UNPARSED in targets:
            # Checked BEFORE the two branch rules, which compare against the expected branch and
            # would let this through the moment the sentinel happened to look permitted.
            return _deny("Brain: could not parse the push target — run the push as a plain "
                         "`git push <remote> <branch>` so the branch rules can be checked.")
        text = vault.read(ctx.context_path); fm, _ = vault.parse_frontmatter(text)
        expected = fm.get("branch", "")
        bad = [t for t in targets if expected and t != expected]
        if bad:
            return _deny("Brain: this push targets '%s' but ## Active Work expects '%s' (context.md frontmatter branch:). Confirm with the user or update context.md before pushing." % (bad[0], expected))
        protected = [t for t in targets if t in ("main", "master")]
        if protected and _MAIN_RULE_RE.search(vault.get_section(text, "Hard Rules")):
            return _deny("Brain: Hard Rules forbid pushing directly to '%s'. Push a feature branch and open a PR." % protected[0])
        return EMPTY
    if tool in ("Grep", "Glob"):
        hint = ctx.pre.get("hint")                # rendered pre-lock by _prepare_pre_tool_use
        if not hint:
            return EMPTY
        return HookResult(json={"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": hint}})
    return EMPTY

on_pre_tool_use.prepare = _prepare_pre_tool_use

def on_subagent_start(ctx):
    if not ctx.payload.get("agent_id"):
        return EMPTY
    return HookResult(json={"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": briefing.text(ctx)}})

# SubagentStop is deliberately NOT handled. SMOKE.md check 10 measured it: neither
# additionalContext nor systemMessage reaches the PARENT turn — the text is fed back into the
# finished subagent's own loop, so the reminder lands where nobody can act on it. The two
# channels that DO reach the parent replace it: PostToolUse on a foreground `Agent` call, and
# the `<task-notification>` prompt a background agent's completion submits.

# One registry, defined after every handler. hooks/hooks.json registers exactly these eight
# events; the parity test in tests/test_hooks_agent_notes.py keeps the two in step.
_HANDLERS = {
    "SessionStart": on_session_start,
    "SessionEnd": on_session_end,
    "UserPromptSubmit": on_user_prompt_submit,
    "PreToolUse": on_pre_tool_use,
    "PostToolUse": on_post_tool_use,
    "Stop": on_stop,
    "PreCompact": on_pre_compact,
    "SubagentStart": on_subagent_start,
}
