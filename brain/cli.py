"""CLI subcommands. Plan 2: graph, map. Plan 3 adds init/sync-prepare/sync-finish/status/load/
config/remove/disconnect/map --annotate."""
import argparse, json, os, re, shutil, sys, time
from brain import config, project, vault


def resolve():
    vault_root = config.vault_root()
    if not vault_root:
        print("brain: not configured — run /brain init"); return None
    proj = project.resolve_project(os.getcwd())
    if proj is None:
        print("brain: not a brain project (no CLAUDE.md with a brain: line)"); return None
    return vault_root, proj


def resolve_vault():
    v = config.vault_root()
    if not v:
        print("brain: not configured — run /brain init"); return None
    return v


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write_block(text):
    """Emit a multi-line block that already carries its own newlines.

    The convention across this module: `print()` for a single line the CLI composes itself,
    `sys.stdout.write` for pre-rendered text. Passing file content to `print()` appends a
    second newline, which is why `/brain load`'s context.md dumps used to gain a blank line
    between every section and the next heading."""
    if text:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _curated_text(pdir):
    from brain import codemap
    _, _, curated = codemap.split_codemap(vault.read(os.path.join(pdir, "codemap.md")))
    return curated


def _print_unannotated_dirs(dirs, limit):
    """Shared `<dir>/  (<n> files)` line format for `sync-prepare` and `map --annotate`."""
    for d, cnt in dirs[:limit]:
        print("  %s/  (%d files)" % (d, cnt))


def _require_valid_slug(value):
    """None on a valid slug; the exit-1 message otherwise. Every entry point that turns a
    user-supplied slug into a vault filesystem path must call this BEFORE building that path —
    an unchecked '../x' can walk out of <vault>/projects/."""
    if not project.valid_slug(value):
        return "brain: invalid slug '%s'" % value
    return None


def _graph(args):
    from brain import graph
    r = resolve()
    if r is None:
        return 2
    vault, proj = r
    g = graph.load(vault, proj.slug, proj.project_dir, force=(args.cmd == "rebuild"))
    if args.cmd == "rebuild":
        print("graph: %d nodes, %d edges, %d dangling" % (len(g.nodes), len(g.edges), len(g.dangling))); return 0
    if args.cmd == "find":
        nodes = graph.find(g, args.term, type=args.type, limit=args.limit)
        sys.stdout.write(graph.render_find(g, nodes, limit=args.limit) or "no matches\n"); return 0
    if args.cmd == "near":
        nid = args.node if args.node in g.nodes else (graph.find(g, args.node, limit=1) or [None])[0]
        nid = nid if isinstance(nid, str) or nid is None else nid.id
        sys.stdout.write(graph.render_near(g, nid, depth=args.depth, limit=args.limit) if nid else "no matches\n"); return 0
    if args.cmd == "ask":
        from brain import backends
        # Two different failures, two different messages: "the backend is off" is a config
        # answer, "the query came back empty" is a question-shape answer.
        msg = "graph: graphify backend not active (config graph.backend, or run /graphify first)"
        if backends.select(proj.project_dir) == backends.GRAPHIFY:
            from brain.backends import graphify
            out = graphify.ask(proj.project_dir, args.question, budget=args.budget)
            if out.strip():
                sys.stdout.write(out if out.endswith("\n") else out + "\n"); return 0
            msg = "graph: graphify query returned nothing (timeout or error) — try a narrower question"
        print(msg)
        hit = (graph.find(g, args.question, limit=1) or [None])[0]
        sys.stdout.write(graph.render_near(g, hit.id) if hit else "no matches\n"); return 0
    if args.cmd == "path":
        sys.stdout.write(graph.render_path(g, graph.path(g, args.a, args.b)) or "no path\n"); return 0
    if args.cmd == "top":
        sys.stdout.write(graph.render_top(g, graph.top(g, n=args.n)) or "graph is empty\n"); return 0
    if args.cmd == "lint":
        try:
            from brain import lint
        except ImportError:
            print("lint: not available"); return 0
        sys.stdout.write(lint.render(lint.run(vault, proj.slug, proj.project_dir, g, all_projects=args.all_projects), g)); return 0
    if args.cmd == "dismiss":
        from brain import lint
        pdir = project.vault_project_dir(vault, proj.slug)
        lint.dismiss(pdir, args.slug)
        print("dismissed: %s" % args.slug)
        return 0
    return 1


def _map(args):
    from brain import codemap
    r = resolve()
    if r is None:
        return 2
    vault_root, proj = r
    pdir = project.vault_project_dir(vault_root, proj.slug)
    if getattr(args, "annotate", False):
        dirs = codemap.unannotated_dirs(proj.project_dir, _curated_text(pdir))
        if not dirs:
            print("all major directories have a Modules row")
        else:
            print("unannotated dirs:")
            _print_unannotated_dirs(dirs, 10)
        return 0
    if args.regen or args.force:
        changed = codemap.regenerate(proj.project_dir, pdir, force=args.force)
        if not args.quiet:
            print("codemap: %s" % ("regenerated" if changed else "up to date"))
        return 0
    layer = codemap.read_layer(pdir)
    stored = (layer or {}).get("sha", "")
    current = codemap.freshness_key(proj.project_dir)
    if not current:
        status = "unknown (not a git repo)"      # no HEAD and nothing to hash — cannot compare
    elif current != stored:
        status = "stale — run map --regen"
    else:
        status = "fresh"
    if not args.quiet:
        print("codemap: %s (%d files, head %s)" % (status, len((layer or {}).get("files", [])), (stored or "-")[:7]))
    return 0


def _init(args):
    from brain import initproj, gitinfo
    vault_root = config.vault_root()
    if not vault_root and args.vault:
        newv = os.path.realpath(os.path.expanduser(args.vault)); os.makedirs(newv, exist_ok=True)
        config.set_value("vault", newv); vault_root = newv
    if not vault_root:
        print("brain: not configured — run: brain config set vault <path>"); return 2
    name = args.name.strip(); slug = initproj.slugify_name(name)
    if not slug:
        print("brain: could not derive a slug from %r" % name); return 1
    pdir_repo = os.path.realpath(args.project_dir or os.getcwd())
    err = initproj.preflight(vault_root, slug, args.type, pdir_repo if args.type == "code" else None, want_permissions=not args.no_permissions)
    if err:
        print(err); return 1
    initproj.ensure_vault(vault_root)
    repo_url = gitinfo._git(pdir_repo, "remote", "get-url", "origin").strip() if args.type == "code" else ""
    written = initproj.create_project(vault_root, slug, name, args.type, pdir_repo if args.type == "code" else None, repo_url)
    granted = 0 if args.no_permissions else initproj.grant_permissions(vault_root)
    print("Brain initialized for %s (%s)\n\nVault:          %s\nContext:        %s\nLog:            %s" % (
        name, slug, vault_root, os.path.join(vault_root, "projects", slug, "context.md"), os.path.join(vault_root, "projects", slug, "log.md")))
    if args.type == "code":
        print("CLAUDE.md:      %s\nCodemap:        %s\nHooks:          shipped by the plugin (no per-project registration)" % (
            written.get("claude_md", "(already had a brain line)"), written.get("codemap", "")))
    print("Permissions:    %s" % ("%d entries added to user settings" % granted if granted else "already present"))
    if args.type == "topic":
        print("To load this project in any session: /brain load %s" % slug)
    if args.packet and args.type == "code":
        print("\n=== SEEDING PACKET ===")
        _write_block(initproj.seeding_packet(pdir_repo))
    return 0


def _index_row_cells(line):
    """Cells of one project-index table row, or None if `line` is not a data row
    (header/separator). Splits on the LAST '|...|' segment separately from the rest so an
    escaped '\\|' inside a wikilink alias earlier in the row cannot confuse the last-column edit."""
    s = line.strip()
    if not s.startswith("|") or set(s.strip("|")) <= set("- "):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    return None if not cells or cells[0] == "project" else cells


def _set_index_last_active(text, slug, date):
    marker = "projects/%s/context" % slug
    out = []
    for line in text.splitlines(keepends=True):
        if marker in line and line.lstrip().startswith("|"):
            stripped = line.rstrip("\n")
            new = re.sub(r"\|[^|]*\|\s*$", "| %s |" % date, stripped)
            line = new + "\n"
        out.append(line)
    return "".join(out)


def _remove_index_row(text, slug):
    marker = "projects/%s/context" % slug
    return "".join(l for l in text.splitlines(keepends=True) if marker not in l)


def _cmd_sync_prepare(args):
    from brain import codemap, graph, lint
    r = resolve()
    if r is None:
        return 2
    vault_root, proj = r
    pdir = project.vault_project_dir(vault_root, proj.slug)
    ctx_text = vault.read(os.path.join(pdir, "context.md"))
    log_text = vault.read(os.path.join(pdir, "log.md"))
    n_entries = vault.count_log_entries(log_text)
    placeholder = vault.last_entry_is_placeholder(log_text)
    print("slug: %s" % proj.slug)
    print("context.md: %d lines (cap 150)" % len(ctx_text.splitlines()))
    print("last log entry: Session %d [%s]" % (n_entries, "placeholder" if placeholder else "real"))
    print("next session: %d" % (n_entries if placeholder else n_entries + 1))
    from brain import gitinfo
    print("today's commits:")
    for c in gitinfo.commits_today(proj.project_dir)[:5]:
        print("  - %s" % c)
    print("modified files:")
    for f in gitinfo.changed_files_today(proj.project_dir)[:8]:
        print("  - %s" % f)
    layer = codemap.read_layer(pdir)
    current = codemap.freshness_key(proj.project_dir)
    stored = (layer or {}).get("sha", "")
    print("codemap: %s" % ("unknown" if not current else ("fresh" if current == stored else "stale")))
    g = graph.load(vault_root, proj.slug, proj.project_dir)
    print("graph: %d nodes, %d edges" % (len(g.nodes), len(g.edges)))
    sys.stdout.write(lint.render(lint.run(vault_root, proj.slug, proj.project_dir, g, want_duplicates=False), g))
    dirs = codemap.unannotated_dirs(proj.project_dir, _curated_text(pdir))
    print("unannotated dirs:")
    _print_unannotated_dirs(dirs, 5)
    return 0


def _cmd_sync_finish(args):
    from brain import codemap, graph
    r = resolve()
    if r is None:
        return 2
    vault_root, proj = r
    pdir = project.vault_project_dir(vault_root, proj.slug)
    ctx_path = os.path.join(pdir, "context.md")
    today = time.strftime("%Y-%m-%d")
    vault.write(ctx_path, vault.set_frontmatter(vault.read(ctx_path), "updated", today))
    idx_path = os.path.join(vault_root, "_system", "project-index.md")
    vault.write(idx_path, _set_index_last_active(vault.read(idx_path), proj.slug, today))
    codemap.regenerate(proj.project_dir, pdir)
    graph.load(vault_root, proj.slug, proj.project_dir, force=True)
    n_lines = len(vault.read(ctx_path).splitlines())
    print("context.md: %d lines (cap 150)" % n_lines)
    if n_lines > 150:
        print("WARNING: over cap — compress ## Decisions beyond the 5 most recent")
    print("Brain synced: %s" % proj.slug)
    return 0


def _v1_script_names():
    """The four script basenames v1 installed. `migrate._LEGACY_MARKERS` is the single source
    of truth — it is also what `strip_legacy_hooks` matches settings entries against."""
    from brain import migrate
    return tuple(m.lstrip("/") for m in migrate._LEGACY_MARKERS)


def _orphan_scripts(vault_root, proj):
    """[(basename, path-that-references-it-or-None), ...] for the v1 per-project hook scripts
    still sitting in `~/.claude/`. Referenced = the user's own `settings.json` (v1 hooks could
    be registered globally), the current project's `.claude/settings.json`, or any
    project-index `path:` column that mentions it.

    Deliberately NOT a `~/.claude/brain-*.sh` glob: `--clean-orphans` deletes with no backup
    and no per-file confirmation, and that namespace belongs to the user too — a
    `brain-notes.sh` of their own is not ours to remove."""
    from brain import initproj
    paths = sorted(p for p in (os.path.expanduser("~/.claude/" + n) for n in _v1_script_names()) if os.path.exists(p))
    if not paths:
        return []
    settings_paths = [initproj.settings_path(), os.path.join(proj.project_dir, ".claude", "settings.json")]
    idx_text = vault.read(os.path.join(vault_root, "_system", "project-index.md"))
    for line in idx_text.splitlines():
        cells = _index_row_cells(line)
        if cells and len(cells) >= 3 and cells[2] and cells[2] != "—" and os.path.isdir(cells[2]):
            settings_paths.append(os.path.join(cells[2], ".claude", "settings.json"))
    texts = [vault.read(p) for p in settings_paths]
    out = []
    for sp in paths:
        name = os.path.basename(sp)
        ref = next((settings_paths[i] for i, t in enumerate(texts) if t and sp in t), None)
        out.append((name, ref))
    return out


def _clean_orphans(orphans):
    """(removed, kept, failed). A deletion that raises (e.g. the "script" is actually a
    directory) must NOT be reported as removed — that would tell the user something is gone
    when it is still on disk."""
    removed, kept, failed = [], [], []
    for name, ref in orphans:
        if ref:
            kept.append(name)
            continue
        path = os.path.join(os.path.expanduser("~/.claude"), name)
        try:
            os.remove(path)
            removed.append(name)
        except OSError as e:
            failed.append("%s (%s)" % (name, e.strerror or str(e)))
    return removed, kept, failed


def _cmd_status(args):
    from brain import codemap, graph, lint
    vault_root = resolve_vault()
    if vault_root is None:
        return 2
    proj = project.resolve_project(os.getcwd())
    if proj is None:
        print("brain: no project resolved for this directory. Known projects:")
        _write_block(vault.read(os.path.join(vault_root, "_system", "project-index.md")))
        return 2
    pdir = project.vault_project_dir(vault_root, proj.slug)
    ctx_text = vault.read(os.path.join(pdir, "context.md"))
    fm, _ = vault.parse_frontmatter(ctx_text)
    log_text = vault.read(os.path.join(pdir, "log.md"))
    try:
        from brain import backends
        backend = backends.select(proj.project_dir)     # effective backend, not the configured mode
    except Exception:
        backend = config.load_config().get("graph", {}).get("backend", "auto")
    n_hooks = 0
    try:
        with open(os.path.join(_repo_root(), "hooks", "hooks.json"), encoding="utf-8") as f:
            n_hooks = len(json.load(f).get("hooks", {}))
    except (OSError, ValueError):
        pass
    layer = codemap.read_layer(pdir)
    current = codemap.freshness_key(proj.project_dir)
    stored = (layer or {}).get("sha", "")
    codemap_status = "unknown" if not current else ("fresh" if current == stored else "stale")
    g = graph.load(vault_root, proj.slug, proj.project_dir)
    cache_path = os.path.join(pdir, ".brain", "graph.json")
    try:
        age = int(time.time() - os.stat(cache_path).st_mtime)
    except OSError:
        age = 0
    health = lint.health_line(lint.run(vault_root, proj.slug, proj.project_dir, g)) or "clean"
    print("Brain status: %s (%s)" % (fm.get("project", proj.slug), proj.slug))
    print("Type: %s" % fm.get("type", "?"))
    print("Vault: %s" % vault_root)
    print("Backend: %s" % backend)
    print("Updated: %s" % fm.get("updated", "?"))
    print("Sessions: %d" % vault.count_log_entries(log_text))
    print("Context size: %d / 150 lines" % len(ctx_text.splitlines()))
    print("Hooks: plugin-shipped (%d events)" % n_hooks)
    print("Codemap: %s" % codemap_status)
    print("Graph: %d nodes, %d edges (cache %ds old)" % (len(g.nodes), len(g.edges), age))
    print("Concept health: %s" % health)
    orphans = _orphan_scripts(vault_root, proj)
    if orphans:
        print("Orphan v1 hook scripts: %s" % ", ".join(
            n + (" (still referenced by %s)" % r if r else "") for n, r in orphans))
    else:
        print("Orphan v1 hook scripts: none")
    if getattr(args, "clean_orphans", False):
        removed, kept, failed = _clean_orphans(orphans)
        if removed:
            print("removed: %s" % ", ".join(removed))
        if kept:
            print("kept (referenced): %s" % ", ".join(kept))
        if failed:
            print("failed: %s" % ", ".join(failed))
    print("── State " + "─" * 32)
    _write_block(vault.get_section(ctx_text, "State"))
    print("── Active Work " + "─" * 26)
    _write_block(vault.get_section(ctx_text, "Active Work"))
    print("── Open Questions " + "─" * 23)
    _write_block(vault.get_section(ctx_text, "Open Questions"))
    print("── Last Session " + "─" * 25)
    _write_block(vault.last_log_entry(log_text))
    return 0


def _concept_description(text):
    _, body = vault.parse_frontmatter(text)
    paras = [p for p in body.strip().split("\n\n") if p.strip()]
    if not paras:
        return ""
    return paras[1] if paras[0].startswith("#") and len(paras) > 1 else paras[0]


_USED_BY_LINK_RE = re.compile(r"\[\[projects/([^/\]]+)/context[^\]]*\]\]")


def _cmd_load(args):
    vault_root = resolve_vault()
    if vault_root is None:
        return 2
    for entry in args.slugs:
        err = _require_valid_slug(entry)
        if err:
            print(err); return 1
    missing, resolved, seen, expansions = [], [], set(), []
    for entry in args.slugs:
        proj_ctx = os.path.join(vault_root, "projects", entry, "context.md")
        if os.path.exists(proj_ctx):
            if entry not in seen:
                seen.add(entry); resolved.append(entry)
            continue
        cpath = os.path.join(vault_root, "concepts", entry + ".md")
        if os.path.exists(cpath):
            ctext = vault.read(cpath)
            used_by = vault.get_section(ctext, "Used by")
            valid = []
            for s in _USED_BY_LINK_RE.findall(used_by):
                # Vault-authored, but the same class as a user-supplied slug: the link regex's
                # `[^/\]]+` admits `..`, and these slugs go straight into a vault path below.
                if _require_valid_slug(s) is None and os.path.exists(os.path.join(vault_root, "projects", s, "context.md")):
                    valid.append(s)
                    if s not in seen:
                        seen.add(s); resolved.append(s)
                else:
                    missing.append("%s (stale link in concept '%s')" % (s, entry))
            if valid:
                expansions.append((entry, valid, cpath))
            else:
                missing.append(entry)
            continue
        missing.append(entry)
    if not resolved:
        print("Not found: %s. Available projects are listed in %s; concept groups are in %s." % (
            ", ".join(missing), os.path.join(vault_root, "_system", "project-index.md"), os.path.join(vault_root, "concepts")))
        return 1
    if missing:
        print("Not found: %s" % ", ".join(missing))
    print("Loaded: %s" % ", ".join(resolved))
    for entry, slugs, cpath in expansions:
        print("Via concept '%s': %s" % (entry, ", ".join(slugs)))
        _write_block(_concept_description(vault.read(cpath)))
    for slug in resolved:
        pdir = os.path.join(vault_root, "projects", slug)
        print("=== %s context.md ===" % slug)
        _write_block(vault.read(os.path.join(pdir, "context.md")))
        print("=== %s log.md (last entry) ===" % slug)
        _write_block(vault.last_log_entry(vault.read(os.path.join(pdir, "log.md"))))
    return 0


def _cmd_config(args):
    if getattr(args, "config_action", None) == "set":
        try:
            config.set_value(args.key, args.value)
        except ValueError as e:
            print(str(e)); return 1
        data = config.load_config()
        if args.key == "graph.backend":
            shown = data.get("graph", {}).get("backend")
        elif args.key == "async_regen":
            shown = "on" if data.get("async_regen") else "off"          # echo on/off, not True/False
        else:
            shown = data.get(args.key)
        print("%s: %s" % (args.key, shown))
        return 0
    data = config.load_config()
    print("vault: %s" % data.get("vault", "(not set)"))
    print("gate: %s" % config.gate_mode())
    print("async_regen: %s" % ("on" if config.async_regen() else "off"))
    print("graph.backend: %s" % data.get("graph", {}).get("backend", "auto"))
    print("config path: %s" % config._config_path())
    return 0


def _connected_folder(path, want_slug):
    """(ok, other_slug_or_None). `ok` is True only if `path` is a real directory whose
    CLAUDE.md brain block resolves to `want_slug` — the shared guard `remove`/`disconnect`
    use before ever touching a project folder."""
    if not path or path == "—" or not os.path.isdir(path):
        return False, None
    p = project.resolve_project(path)
    if p is None or p.slug != want_slug:
        return False, (p.slug if p else None)
    return True, None


def _strip_brain_block(claude_md):
    """Remove the brain block, keeping the user's frontmatter and everything below it, after a
    `.brain-bak` copy. `remove`/`disconnect` are documented as touching only the brain block."""
    from brain import migrate
    migrate.rewrite_block(claude_md, lambda head: "")


def _cmd_remove(args):
    from brain import migrate
    vault_root = resolve_vault()
    if vault_root is None:
        return 2
    slug = args.slug
    err = _require_valid_slug(slug)
    if err:
        print(err); return 1
    pdir = os.path.join(vault_root, "projects", slug)
    if not os.path.isdir(pdir):
        print("Project '%s' not found in vault." % slug); return 1
    if args.confirm != slug:
        print("This will permanently delete vault project '%s'.\nType '%s' to confirm." % (slug, slug))
        return 1
    # Defense-in-depth: valid_slug() already rules out a path-shaped slug, but a real rmtree
    # is destructive enough to double-check the resolved dir actually landed inside projects/.
    projects_root = os.path.realpath(os.path.join(vault_root, "projects"))
    if os.path.commonpath([os.path.realpath(pdir), projects_root]) != projects_root:
        print("brain: refusing to delete outside vault projects/: %s" % pdir); return 1
    fm, _ = vault.parse_frontmatter(vault.read(os.path.join(pdir, "context.md")))
    path = fm.get("path", "")
    touched, warn = False, None
    if path and path != "—" and os.path.isdir(path):
        ok, other = _connected_folder(path, slug)
        if ok:
            _strip_brain_block(os.path.join(path, "CLAUDE.md"))
            migrate.strip_legacy_hooks(os.path.join(path, ".claude", "settings.json"))
            touched = True
        else:
            warn = "warning: %s is connected to '%s' — CLAUDE.md left untouched" % (path, other or "none")
    shutil.rmtree(pdir)
    idx_path = os.path.join(vault_root, "_system", "project-index.md")
    vault.write(idx_path, _remove_index_row(vault.read(idx_path), slug))
    print("Removed: %s" % slug)
    print("Vault files deleted.")
    print("Index row removed.")
    if touched:
        print("CLAUDE.md brain section removed from %s" % path)
    if warn:
        print(warn)
    return 0


def _cmd_disconnect(args):
    vault_root = resolve_vault()
    if vault_root is None:
        return 2
    slug = args.slug
    err = _require_valid_slug(slug)
    if err:
        print(err); return 1
    ctx_path = os.path.join(vault_root, "projects", slug, "context.md")
    if not os.path.exists(ctx_path):
        print("Project '%s' not found in vault." % slug); return 1
    fm, _ = vault.parse_frontmatter(vault.read(ctx_path))
    path = fm.get("path", "")
    if not path or path == "—":
        print("This project has no folder path set — nothing to disconnect from. Vault files are untouched.")
        return 1
    if not os.path.isdir(path):
        print("No folder found at %s — project may already be disconnected. Vault files are untouched." % path)
        return 1
    ok, other = _connected_folder(path, slug)
    if not ok:
        if other:
            print("%s/CLAUDE.md is connected to '%s', not '%s' — nothing changed" % (path, other, slug))
        else:
            print("%s/CLAUDE.md has no brain block — project may already be disconnected. Vault files are untouched." % path)
        return 1
    _strip_brain_block(os.path.join(path, "CLAUDE.md"))
    print("Disconnected: %s" % slug)
    print("CLAUDE.md brain section removed from %s" % path)
    print("Vault files untouched — history preserved at %s" % os.path.join(vault_root, "projects", slug))
    return 0


def _cmd_repair(args):
    from brain import codemap, migrate
    vault_root = resolve_vault()
    if vault_root is None:
        return 2
    slug = args.slug
    err = _require_valid_slug(slug)
    if err:
        print(err); return 1
    pdir = project.vault_project_dir(vault_root, slug)
    ctx_path = os.path.join(pdir, "context.md")
    if not os.path.exists(ctx_path):
        print("Project '%s' not found in vault." % slug); return 1
    cwd = os.path.realpath(os.getcwd())
    # resolve_project walks up from cwd — a same-slug hit may live in a parent dir. Never
    # write a nested CLAUDE.md next to it; repair the one that's actually connected.
    existing_proj = project.resolve_project(cwd)
    if existing_proj is not None and existing_proj.slug != slug:
        print("%s is connected to '%s', not '%s' — refusing to overwrite" % (
            existing_proj.claude_md, existing_proj.slug, slug))
        return 1
    target_dir = existing_proj.project_dir if existing_proj is not None else cwd
    claude_md = os.path.join(target_dir, "CLAUDE.md")
    # replace_existing=True: a valid brain block for this slug is replaced in place. False:
    # absent, or present with no recognizable brain line — the v1 rule is block + file verbatim.
    migrate.rewrite_block(claude_md, lambda head: migrate.slim_block(migrate._display_name(head, slug), slug),
                          replace_existing=existing_proj is not None)
    fm, _ = vault.parse_frontmatter(vault.read(ctx_path))
    ctx_path_field = fm.get("path", "")
    if ctx_path_field and ctx_path_field != "—" and os.path.realpath(os.path.expanduser(ctx_path_field)) != target_dir:
        print("warning: context.md path: %s differs from %s — update it with /brain sync if this folder moved" % (
            ctx_path_field, target_dir))
    codemap.ensure(target_dir, pdir)
    print("Repaired: %s" % slug)
    print("CLAUDE.md:      %s" % claude_md)
    print("Codemap:        %s" % os.path.join(pdir, "codemap.md"))
    return 0


# Subparsers whose own usage line is what a bare `brain <top>` should print. Filled in by
# build_parser() so run() can answer "brain graph" with the graph usage, not brain's.
SUBPARSERS = {}


def build_parser():
    p = argparse.ArgumentParser(prog="brain", add_help=True)
    sub = p.add_subparsers(dest="top")
    g = sub.add_parser("graph"); gs = g.add_subparsers(dest="cmd")
    SUBPARSERS["graph"] = g
    f = gs.add_parser("find"); f.add_argument("term"); f.add_argument("--type"); f.add_argument("--limit", type=int, default=15)
    n = gs.add_parser("near"); n.add_argument("node"); n.add_argument("--depth", type=int, default=1); n.add_argument("--limit", type=int, default=40)
    pa = gs.add_parser("path"); pa.add_argument("a"); pa.add_argument("b")
    t = gs.add_parser("top"); t.add_argument("--n", type=int, default=12)
    ak = gs.add_parser("ask"); ak.add_argument("question"); ak.add_argument("--budget", type=int, default=1500)
    gs.add_parser("rebuild")
    l = gs.add_parser("lint"); l.add_argument("--all-projects", action="store_true")
    ds = gs.add_parser("dismiss"); ds.add_argument("slug")
    m = sub.add_parser("map"); m.add_argument("--regen", action="store_true"); m.add_argument("--force", action="store_true"); m.add_argument("--quiet", action="store_true"); m.add_argument("--annotate", action="store_true")
    i = sub.add_parser("init")
    i.add_argument("--name", required=True)
    i.add_argument("--type", choices=["code", "topic"], required=True)
    i.add_argument("--project-dir")
    i.add_argument("--vault")
    i.add_argument("--no-permissions", action="store_true")
    i.add_argument("--packet", action="store_true")
    sub.add_parser("sync-prepare")
    sf = sub.add_parser("sync-finish"); sf.add_argument("--session", type=int)
    st = sub.add_parser("status"); st.add_argument("--clean-orphans", action="store_true")
    ld = sub.add_parser("load"); ld.add_argument("slugs", nargs="+")
    c = sub.add_parser("config"); csub = c.add_subparsers(dest="config_action")
    cs = csub.add_parser("set"); cs.add_argument("key"); cs.add_argument("value")
    rm = sub.add_parser("remove"); rm.add_argument("slug"); rm.add_argument("--confirm")
    dc = sub.add_parser("disconnect"); dc.add_argument("slug")
    rp = sub.add_parser("repair"); rp.add_argument("--slug", required=True)
    return p


def run(argv):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    if args.top == "graph":
        if not args.cmd:
            SUBPARSERS["graph"].print_usage()       # `brain graph` alone: show graph's own usage
            return 1
        return _graph(args)
    if args.top == "map":
        return _map(args)
    if args.top == "init":
        return _init(args)
    if args.top == "sync-prepare":
        return _cmd_sync_prepare(args)
    if args.top == "sync-finish":
        return _cmd_sync_finish(args)
    if args.top == "status":
        return _cmd_status(args)
    if args.top == "load":
        return _cmd_load(args)
    if args.top == "config":
        return _cmd_config(args)
    if args.top == "remove":
        return _cmd_remove(args)
    if args.top == "disconnect":
        return _cmd_disconnect(args)
    if args.top == "repair":
        return _cmd_repair(args)
    parser.print_usage(); return 1
