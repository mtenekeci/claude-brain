"""Read-only adapter for an existing graphify graph.

The `/graphify` skill writes `graphify-out/graph.json` (a networkx node-link dump) plus
`.graphify_python` (the interpreter it ran under) and `.graphify_root`. This module only ever
*consumes* those: it never builds, updates, or clusters a graph — a build costs minutes and
tokens, so triggering one from a hook or a `graph` command would be a trap.

The on-disk shape drifts between graphify versions, so every field is read tolerantly:
edges live under `edges` or `links`, endpoints under `source`/`target` or `from`/`to`, and
most real nodes carry no `type` at all — only `label` + `source_file`.
"""
import json, os, shutil, subprocess, time

from brain import backends, codemap, config

OUT_DIR = "graphify-out"
MAX_SYMBOLS = codemap.MAX_SYMBOLS
MAX_IMPORTS = 5
ASK_TIMEOUT = 20
ASK_LINES = 60
DEFAULT_BUDGET = 1500

FILE_TYPES = ("file",)
SYMBOL_TYPES = ("function", "class", "method", "symbol", "interface", "struct", "trait", "enum", "const", "variable")
# `contains`, `references`, `cites`… say nothing about the file graph; these two do.
IMPORT_RELATIONS = ("imports", "import", "imports_from", "imports-from", "re_exports", "re-exports",
                    "calls", "call", "invokes", "depends_on", "depends-on")
# graphify tags every node with the corpus it came from; only `code` belongs in a code layer.
# Nodes predating the field (no `file_type` at all) fall back to the basename heuristic.
CODE_FILE_TYPE = "code"

# Paths already reported this process. A broken graph.json is broken on every load, and
# `graph.load` runs on the hook hot path — one line per problem, not one per load.
_LOGGED = set()


def _log_once(path, msg):
    if path in _LOGGED:
        return
    _LOGGED.add(path)
    config.log_error(msg)


def out_dir(project_dir):
    return os.path.join(project_dir or "", OUT_DIR)


def graph_json(project_dir):
    return os.path.join(out_dir(project_dir), "graph.json")


def source_key(project_dir):
    """Content key for the graph, computed without reading it. Matches the `sha` that
    `code_layer` puts on the layer it returns — both are `backends.digest` of the same file."""
    return backends.digest(graph_json(project_dir), "graphify:")


def interpreter(project_dir):
    """The interpreter graphify recorded, when it still exists. '' otherwise.

    Written to `graphify-out/.graphify_python`; older layouts left it in the project root.
    """
    for path in (os.path.join(out_dir(project_dir), ".graphify_python"),
                 os.path.join(project_dir or "", ".graphify_python")):
        try:
            with open(path, encoding="utf-8") as f:
                p = f.read().strip()
        except OSError:
            continue
        if p and os.path.exists(p):
            return p
    return ""


def command(project_dir):
    """argv prefix that runs graphify, or [] when nothing can."""
    exe = shutil.which("graphify")
    if exe:
        return [exe]
    interp = interpreter(project_dir)
    return [interp, "-m", "graphify"] if interp else []


def available(project_dir):
    """A graph to read AND a way to run graphify. Both, or the backend is not usable."""
    if not project_dir or not os.path.isfile(graph_json(project_dir)):
        return False
    return bool(command(project_dir))


# ---------------------------------------------------------------- graph.json → code layer

def _text(d, *keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _ident(v):
    """Node ids are strings in every graphify build seen so far, but a hand-rolled or
    exported graph can carry integer ids — they still have to line up across nodes/edges."""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    return ""


def _ref(d, *keys):
    for k in keys:
        v = _ident(d.get(k))
        if v:
            return v
    return ""


def _rel(project_dir, path):
    """Repo-relative POSIX path, or '' for anything outside the repo / unusable."""
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return ""
    if os.path.isabs(p):
        try:
            p = os.path.relpath(p, project_dir)
        except ValueError:
            return ""
    p = os.path.normpath(p).replace(os.sep, "/")
    return "" if p in (".", "..") or p.startswith("../") else p


def _nodes(data):
    ns = data.get("nodes")
    if isinstance(ns, dict):        # id -> node mapping instead of a list
        ns = [dict(v, id=v.get("id", k)) for k, v in ns.items() if isinstance(v, dict)]
    if not isinstance(ns, list):
        raise ValueError("nodes is %s, not a list" % type(ns).__name__)
    return ns


def _edges(data):
    for key in ("edges", "links"):
        e = data.get(key)
        if isinstance(e, list):
            return e
    return []


def _endpoints(e):
    if isinstance(e, (list, tuple)):
        return (_ident(e[0] if len(e) > 0 else ""), _ident(e[1] if len(e) > 1 else ""),
                (e[2] if len(e) > 2 else "imports"))
    if not isinstance(e, dict):
        return "", "", ""
    return _ref(e, "source", "from", "src"), _ref(e, "target", "to", "dst"), _text(e, "type", "relation", "edge_type")


def parse_graph(project_dir, data):
    """{path: file entry} in the shape `codemap.build_layer` produces. Raises on a bad shape."""
    files, owner = {}, {}

    def entry(path):
        return files.setdefault(path, {"path": path, "lines": 0, "symbols": [], "imports": []})

    for n in _nodes(data):
        if not isinstance(n, dict):
            continue
        ftype = _text(n, "file_type").lower()
        if ftype and ftype != CODE_FILE_TYPE:
            continue                                # a doc/paper/image node is not a source file
        path = _rel(project_dir, _text(n, "path", "file", "source_file", "source", "filename"))
        if not path:
            continue
        name = _text(n, "label", "name", "title")
        ntype = _text(n, "type", "kind", "node_type").lower()
        # Most real nodes have no type: the file node is the one whose label IS the filename.
        # (A typed `module` node can be an *imported* module — "Foundation" carrying the
        # importing file's source_file — so it goes through the same name test, not into
        # FILE_TYPES.)
        is_symbol = ntype in SYMBOL_TYPES or (ntype not in FILE_TYPES and name and name != os.path.basename(path))
        e = entry(path)
        if is_symbol and name and name not in e["symbols"] and len(e["symbols"]) < MAX_SYMBOLS:
            e["symbols"].append(name)
        nid = _ref(n, "id")
        if nid:
            owner[nid] = path                       # symbols resolve to their file for edge lifting

    for raw in _edges(data):
        src, dst, rel = _endpoints(raw)
        if str(rel or "").lower() not in IMPORT_RELATIONS:
            continue
        a, b = owner.get(src), owner.get(dst)       # a symbol→symbol call becomes a file→file import
        if not a or not b or a == b:
            continue
        imports = files[a]["imports"]
        if b not in imports and len(imports) < MAX_IMPORTS:
            imports.append(b)

    for f in files.values():
        f["imports"].sort()
    return files


def code_layer(project_dir):
    """The graphify graph as a code layer, or None (logged) when it cannot be used."""
    path = graph_json(project_dir)
    try:
        with open(path, "rb") as f:
            raw = f.read()
        data = json.loads(raw.decode("utf-8", "replace"))
        if not isinstance(data, dict):
            raise ValueError("graph.json is not an object")
        files = parse_graph(project_dir, data)
        if not files:
            # A graph with no source files (docs-only corpus, or a shape we did not
            # recognise) would silently erase the code layer — hand the builtin one back.
            raise ValueError("no file nodes")
        # Inside the try as well: manifest parsing and the digest touch the disk too, and a
        # failure there is the same "backend unusable" outcome, not a traceback.
        layer = {"sha": source_key(project_dir),
                 "files": sorted(files.values(), key=lambda f: f["path"]),
                 "deps": codemap.manifest_deps(project_dir),
                 "generated_at": int(time.time()),
                 "backend": "graphify"}
    except FileNotFoundError:
        return None                                 # no graph here: normal, and never logged
    except (OSError, ValueError, TypeError, AttributeError, IndexError) as e:
        _log_once(path, "graphify: cannot use %s (%s) — using the builtin code layer" % (path, e))
        return None
    return layer


# ---------------------------------------------------------------- ask

def ask(project_dir, question, budget=DEFAULT_BUDGET):
    """`graphify query "<question>"` output, capped. '' when graphify cannot answer.

    `query` is the only subcommand ever run: it reads the existing graph and never rebuilds.
    """
    q = (question or "").strip()
    cmd = command(project_dir)
    if not q or not cmd:
        return ""
    try:
        r = subprocess.run(cmd + ["query", q, "--budget", str(int(budget))], cwd=project_dir,
                           capture_output=True, text=True, timeout=ASK_TIMEOUT)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        config.log_error("graphify: query failed (%s)" % e)
        return ""
    out = r.stdout or ""
    if r.returncode != 0:
        config.log_error("graphify: query exited %s (%s)" % (r.returncode, (r.stderr or "").strip()[:200]))
    lines = out.splitlines()[:ASK_LINES]
    return "\n".join(lines) + "\n" if lines else ""
