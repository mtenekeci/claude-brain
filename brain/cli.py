"""CLI subcommands. Plan 2: graph, map. Plan 3 adds init/sync/status/load/config/remove."""
import argparse, os, sys
from brain import config, project


def resolve():
    vault = config.vault_root()
    if not vault:
        print("brain: not configured — run /brain init"); return None
    proj = project.resolve_project(os.getcwd())
    if proj is None:
        print("brain: not a brain project (no CLAUDE.md with a brain: line)"); return None
    return vault, proj


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
    vault, proj = r
    pdir = project.vault_project_dir(vault, proj.slug)
    if args.regen or args.force:
        changed = codemap.regenerate(proj.project_dir, pdir, force=args.force)
        if not args.quiet:
            print("codemap: %s" % ("regenerated" if changed else "up to date"))
        return 0
    layer = codemap.read_layer(pdir)
    stored = (layer or {}).get("sha", "")
    current = codemap.fingerprint(proj.project_dir)
    if not args.quiet:
        print("codemap: %s (%d files, head %s)" % ("stale — run map --regen" if current and current != stored else "fresh", len((layer or {}).get("files", [])), (stored or "-")[:7]))
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
    m = sub.add_parser("map"); m.add_argument("--regen", action="store_true"); m.add_argument("--force", action="store_true"); m.add_argument("--quiet", action="store_true")
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
    parser.print_usage(); return 1
