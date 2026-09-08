"""Hook handlers. dispatch() is the only entry point; each on_<event> returns a HookResult.
Contract: never raise, never print outside brain projects."""
import os, re, shlex, subprocess, sys, time, traceback
from brain import briefing, codemap, config, graph, project, retrieve, state, vault, gitinfo

PROTOCOL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "protocol.md")
_SOFT_EDIT_THRESHOLD = 5        # soft-tier Stop gate: uncommitted source edits before nudging
_INJECTED_CAP = 300             # bound on ctx.state.injected — a long session must not grow this file forever
SOURCE_EXTS = codemap.SOURCE_EXTS

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

_REGEN_MIN_INTERVAL = 60.0

def _spawn_regen(ctx, force=False):
    """Fire-and-forget `map --regen` in a detached process. At most once per minute per session,
    and never when the config disables background regeneration."""
    if not config.async_regen():
        return False
    now = time.time()
    if now - ctx.state.last_regen_spawn_at < _REGEN_MIN_INTERVAL:
        return False
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__main__.py")
    argv = [sys.executable, main_py, "map", "--regen"] + (["--force"] if force else []) + ["--quiet"]
    try:
        subprocess.Popen(argv, cwd=ctx.project.project_dir,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception as e:      # Popen can raise more than OSError (bad argv types, ValueError)
        config.log_error("spawn regen failed: %r" % e)
        return False
    ctx.state.last_regen_spawn_at = now
    return True

def _prepare_session_start(ctx):
    """Everything slow or git-touching for SessionStart runs here, BEFORE the session lock."""
    pre = {"migrated_line": "", "large": False, "top": "", "health": "", "head_sha": gitinfo.head_sha(ctx.cwd),
           "log_entries": vault.count_log_entries(vault.read(ctx.log_path)), "branch": gitinfo.current_branch(ctx.cwd)}
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
            # user's first prompt. Write the scaffold; the detached --force regen fills it in.
            codemap.ensure_stub(ctx.project.project_dir, ctx.pdir)
        else:
            codemap.ensure(ctx.project.project_dir, ctx.pdir, files=files)
            codemap.regenerate(ctx.project.project_dir, ctx.pdir, files=files)
    except Exception as e:
        config.log_error("codemap refresh failed: %r" % e)
    g = None
    try:
        g = graph.load(ctx.vault, ctx.project.slug, ctx.project.project_dir)
        pre["top"] = graph.render_top(g, graph.top(g, n=graph.TOP_LIMIT)).rstrip("\n")
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
        lines += ["", "Brain: most-connected nodes — `%s graph near <id>` for a neighborhood, `graph find <term>` before grepping code:" % cli_command(), ctx.pre["top"]]
    if ctx.pre.get("health"):
        lines += ["", ctx.pre["health"]]
    return lines

def on_session_start(ctx):
    """Locked body: state mutation + output assembly only. All heavy work already ran in
    _prepare_session_start(). context.md is read HERE (not in prepare) because lint's
    auto-apply may have just rewritten it."""
    source = str(ctx.payload.get("source") or "startup")
    state.prune(days=7)
    ctx.state.stop_blocks_this_turn = 0
    migrated_line = ctx.pre.get("migrated_line", "")
    if ctx.state.log_entries_at_start < 0:
        ctx.state.log_entries_at_start = ctx.pre.get("log_entries", 0)
    if not ctx.state.last_head_sha:
        ctx.state.last_head_sha = ctx.pre.get("head_sha", "")
    ctx.state.codemap_stale = bool(ctx.pre.get("large"))
    if ctx.pre.get("large"):
        _spawn_regen(ctx, force=True)
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
    parts += _graph_lines(ctx)
    if source in ("compact", "resume"):
        fm, _ = vault.parse_frontmatter(context_text)
        expected = fm.get("branch") or "unset"
        parts += ["", "Brain: context re-injected after %s; branch is %s (expected: %s)" % (
            source, ctx.pre.get("branch") or "?", expected)]
    if migrated_line:
        parts += ["", migrated_line]
    return HookResult("\n".join(parts) + "\n")

on_session_start.prepare = _prepare_session_start

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
            _spawn_regen(ctx)         # no --force: the fingerprint already reflects uncommitted edits
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
    """Pre-lock: tokenise the prompt and build/load the graph. The locked body only reads and
    writes session state and renders what is already in memory."""
    prompt = str(ctx.payload.get("prompt") or "")
    if retrieve.is_system_prompt(prompt):
        return {}
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
    if retrieve.is_system_prompt(prompt):
        return EMPTY
    s = ctx.state
    already = set(s.injected)
    if retrieve.is_done_signal(prompt) and (s.commits_since_vault_write + s.source_edits_since_vault_write) > 0:
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
        return HookResult("BRAIN SYNC: checkpoint written to %s. NOW fill in Completed and Decided with real session detail, then update ## State and ## Active Work in %s before the compact proceeds.\n" % (ctx.log_path, ctx.context_path))
    return HookResult("BRAIN SYNC: a checkpoint already exists in %s — enrich its Completed/Decided fields, then update context.md.\n" % ctx.log_path)

def on_session_end(ctx):
    s = ctx.state
    if s.commits + s.source_edits + s.vault_writes > 0:
        _append_entry(ctx, "auto-close", with_git=False)
    s.discard = True
    s.delete()
    return EMPTY

on_pre_compact.prepare = _prepare_pre_compact

_PUSH_RE = re.compile(r"\bgit\s+push\b")
_MAIN_RULE_RE = re.compile(r"never\s+.*commit.*\bto\b.*\b(main|master)\b", re.I)
_PUSH_VALUE_OPTS = ("-o", "--push-option", "--receive-pack", "--exec")
# git global options that can appear before the `push` subcommand and would otherwise hide it.
_GIT_GLOBAL_VALUE_OPTS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")
_GIT_GLOBAL_FLAG_OPTS = ("--no-pager", "-P", "--no-optional-locks")
_REDIR_RE = re.compile(r"^\d*[<>]{1,2}(&\d+)?$")
# Segment separators: `||` and `&&` first (so they are not split as two bare `|`/`&`), then
# `;`, a bare `|` pipe, a bare `&` (backgrounding), and a newline — a multi-line Bash body
# hides a push on its second line otherwise.
_SEGMENT_RE = re.compile(r"\|\||&&|[;|&\n]")
# `VAR=value` prefixes sit between the segment start and the command word, exactly like
# env/command/sudo do: `GIT_SSH=x git push` is still a push.
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

def _is_redir(t):
    return bool(_REDIR_RE.match(t)) or t in ("&>", "&>>")

def push_targets(cmd, current_branch):
    """Branch names a Bash command would push to. Parses real `git push` segments only (never quoted/echoed text)."""
    targets = []
    for seg in _SEGMENT_RE.split(cmd or ""):
        try:
            toks = shlex.split(seg.strip(), comments=True)
        except ValueError:
            continue
        while toks and (toks[0] in ("env", "command", "sudo") or _ASSIGN_RE.match(toks[0])):
            toks = toks[1:]
        if not toks or toks[0] != "git":
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
            continue
        positional, skip = [], False
        for t in toks[idx + 1:]:
            if skip:
                skip = False; continue
            if _is_redir(t):
                if t.endswith(">") or t.endswith("<"):
                    skip = True     # drop the redirection's filename too
                continue
            if t in _PUSH_VALUE_OPTS:
                skip = True; continue
            if t.startswith("-"):
                continue
            positional.append(t)
        refspecs = positional[1:] if positional else []
        names = []
        for r in refspecs:
            r = r.lstrip("+")
            dst = r.split(":", 1)[1] if ":" in r else r
            dst = current_branch if dst == "HEAD" else dst
            names.append(dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst)
        if not refspecs:
            names.append(current_branch)
        for n in names:
            if n and n not in targets:
                targets.append(n)
    return targets

def _prepare_pre_tool_use(ctx):
    """Pre-lock: the branch lookup for a push, and the whole graph hint for a Grep/Glob.
    PreToolUse fires on every matching tool call, so its locked body must stay trivial."""
    ti = ctx.payload.get("tool_input") or {}
    tool = str(ctx.payload.get("tool_name") or "")
    if tool == "Bash" and _PUSH_RE.search(str(ti.get("command") or "")):
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
        if not _PUSH_RE.search(cmd):
            return EMPTY
        targets = push_targets(cmd, ctx.pre.get("branch", ""))
        if not targets:
            return EMPTY
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

def on_subagent_stop(ctx):
    msg = str(ctx.payload.get("last_assistant_message") or "")
    if "Vault notes:" not in msg:
        return EMPTY
    who = str(ctx.payload.get("agent_type") or "subagent")
    return HookResult(json={"hookSpecificOutput": {"hookEventName": "SubagentStop", "additionalContext":
        "Brain: subagent '%s' reported vault notes — fold them into %s / codemap.md ## Modules now (a concept note only if you'd link it from more than one place)." % (who, ctx.arch_path)}})

# One registry, defined after every handler. hooks/hooks.json registers exactly these nine
# events; the parity test in tests/test_hooks_session.py keeps the two in step.
_HANDLERS = {
    "SessionStart": on_session_start,
    "SessionEnd": on_session_end,
    "UserPromptSubmit": on_user_prompt_submit,
    "PreToolUse": on_pre_tool_use,
    "PostToolUse": on_post_tool_use,
    "Stop": on_stop,
    "PreCompact": on_pre_compact,
    "SubagentStart": on_subagent_start,
    "SubagentStop": on_subagent_stop,
}
