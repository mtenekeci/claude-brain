"""CLI subcommands. Plan 2: graph, map. Plan 3 adds init/sync-prepare/sync-finish/status/load/
config/remove/disconnect/map --annotate."""
import argparse, glob, json, os, re, shutil, sys, time
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


def _curated_text(pdir):
    from brain import codemap
    _, _, curated = codemap.split_codemap(vault.read(os.path.join(pdir, "codemap.md")))
    return curated


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
    if args.cmd == "path":
        sys.stdout.write(graph.render_path(g, graph.path(g, args.a, args.b)) or "no path\n"); return 0
    if args.cmd == "top":
        sys.stdout.write(graph.render_top(g, graph.top(g, n=args.n)) or "graph is empty\n"); return 0
    if args.cmd == "lint":
        try:
            from brain import lint
        except ImportError:
            print("lint: not available"); return 0
        sys.stdout.write(lint.render(lint.run(vault, proj.slug, proj.project_dir, g, all_projects=args.all_projects))); return 0
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
            for d, cnt in dirs[:10]:
                print("  %s/  (%d files)" % (d, cnt))
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
    # Grant permissions against the vault path as configured (not the realpath'd canonical form
    # used for internal filesystem/comparison work) — that's what the user actually sees/expects
    # in their settings.json, and it's what a fresh `--vault` install just saved verbatim.
    raw_vault = config.load_config().get("vault") or vault_root
    granted = 0 if args.no_permissions else initproj.grant_permissions(raw_vault)
    print("Brain initialized for %s (%s)\n\nVault:          %s\nContext:        %s\nLog:            %s" % (
        name, slug, vault_root, os.path.join(vault_root, "projects", slug, "context.md"), os.path.join(vault_root, "projects", slug, "log.md")))
    if args.type == "code":
        print("CLAUDE.md:      %s\nCodemap:        %s\nHooks:          shipped by the plugin (no per-project registration)" % (
            written.get("claude_md", "(already had a brain line)"), written.get("codemap", "")))
    print("Permissions:    %s" % ("%d entries added to user settings" % granted if granted else "already present"))
    if args.type == "topic":
        print("To load this project in any session: /brain load %s" % slug)
    if args.packet and args.type == "code":
        print("\n=== SEEDING PACKET ===\n" + initproj.seeding_packet(pdir_repo))
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
    sys.stdout.write(lint.render(lint.run(vault_root, proj.slug, proj.project_dir, g, want_duplicates=False)))
    dirs = codemap.unannotated_dirs(proj.project_dir, _curated_text(pdir))
    print("unannotated dirs:")
    for d, cnt in dirs[:5]:
        print("  - %s/ (%d files)" % (d, cnt))
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


def _orphan_scripts(vault_root, proj):
    """[(basename, path-that-references-it-or-None), ...] for every `~/.claude/brain-*.sh`
    orphaned from the old (v1) per-project hook registration. Referenced = the current
    project's `.claude/settings.json`, or any project-index `path:` column that mentions it."""
    paths = sorted(glob.glob(os.path.expanduser("~/.claude/brain-*.sh")))
    if not paths:
        return []
    settings_paths = [os.path.join(proj.project_dir, ".claude", "settings.json")]
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
    removed, kept = [], []
    for name, ref in orphans:
        if ref:
            kept.append(name)
            continue
        try:
            os.remove(os.path.join(os.path.expanduser("~/.claude"), name))
        except OSError:
            pass
        removed.append(name)
    return removed, kept


def _cmd_status(args):
    from brain import codemap, graph, lint
    vault_root = resolve_vault()
    if vault_root is None:
        return 2
    proj = project.resolve_project(os.getcwd())
    if proj is None:
        print("brain: no project resolved for this directory. Known projects:")
        print(vault.read(os.path.join(vault_root, "_system", "project-index.md")))
        return 2
    pdir = project.vault_project_dir(vault_root, proj.slug)
    ctx_text = vault.read(os.path.join(pdir, "context.md"))
    fm, _ = vault.parse_frontmatter(ctx_text)
    log_text = vault.read(os.path.join(pdir, "log.md"))
    try:
        from brain import backends
        backend = backends.select()
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
        removed, kept = _clean_orphans(orphans)
        if removed:
            print("removed: %s" % ", ".join(removed))
        if kept:
            print("kept (referenced): %s" % ", ".join(kept))
    print("── State " + "─" * 32)
    print(vault.get_section(ctx_text, "State"))
    print("── Active Work " + "─" * 26)
    print(vault.get_section(ctx_text, "Active Work"))
    print("── Open Questions " + "─" * 23)
    print(vault.get_section(ctx_text, "Open Questions"))
    print("── Last Session " + "─" * 25)
    print(vault.last_log_entry(log_text))
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
                if os.path.exists(os.path.join(vault_root, "projects", s, "context.md")):
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
        print(_concept_description(vault.read(cpath)))
    for slug in resolved:
        pdir = os.path.join(vault_root, "projects", slug)
        print("=== %s context.md ===" % slug)
        print(vault.read(os.path.join(pdir, "context.md")))
        print("=== %s log.md (last entry) ===" % slug)
        print(vault.last_log_entry(vault.read(os.path.join(pdir, "log.md"))))
    return 0


def _cmd_config(args):
    if getattr(args, "config_action", None) == "set":
        try:
            config.set_value(args.key, args.value)
        except ValueError as e:
            print(str(e)); return 1
        data = config.load_config()
        shown = data.get("graph", {}).get("backend") if args.key == "graph.backend" else data.get(args.key)
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
    text = vault.read(claude_md)
    _, rest = project.split_brain_block(text)
    if rest.strip():
        vault.write(claude_md, rest)
    else:
        os.remove(claude_md)


def _cmd_remove(args):
    from brain import migrate
    vault_root = resolve_vault()
    if vault_root is None:
        return 2
    slug = args.slug
    pdir = os.path.join(vault_root, "projects", slug)
    if not os.path.isdir(pdir):
        print("Project '%s' not found in vault." % slug); return 1
    if args.confirm != slug:
        print("This will permanently delete vault project '%s'.\nType '%s' to confirm." % (slug, slug))
        return 1
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


def build_parser():
    p = argparse.ArgumentParser(prog="brain", add_help=True)
    sub = p.add_subparsers(dest="top")
    g = sub.add_parser("graph"); gs = g.add_subparsers(dest="cmd")
    f = gs.add_parser("find"); f.add_argument("term"); f.add_argument("--type"); f.add_argument("--limit", type=int, default=15)
    n = gs.add_parser("near"); n.add_argument("node"); n.add_argument("--depth", type=int, default=1); n.add_argument("--limit", type=int, default=40)
    pa = gs.add_parser("path"); pa.add_argument("a"); pa.add_argument("b")
    t = gs.add_parser("top"); t.add_argument("--n", type=int, default=12)
    gs.add_parser("rebuild")
    l = gs.add_parser("lint"); l.add_argument("--all-projects", action="store_true")
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
    return p


def run(argv):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    if args.top == "graph" and args.cmd:
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
    parser.print_usage(); return 1
