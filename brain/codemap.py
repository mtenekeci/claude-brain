"""Generated code layer: files, exported symbols, relative imports, manifest deps.
Deterministic; never touches the curated block of codemap.md (rendering lives in part 2)."""
import json, os, re, subprocess, time

SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".rb", ".java", ".kt", ".swift",
               ".vue", ".svelte", ".c", ".cpp", ".cs", ".php", ".scala", ".m", ".mm", ".h")
MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml", "Package.swift")
EXCLUDE_DIRS = ("node_modules", ".git", "dist", "build", "target", ".venv", "venv", "vendor", "__pycache__",
                ".next", "coverage", ".brain")
MAX_SYMBOLS = 8
# At or above this many tracked files, callers on the SessionStart path write a stub and let a
# detached `map --regen --force` do the real build — a synchronous one costs seconds.
LARGE_REPO_FILES = 3000

def _keep(rel):
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts[:-1]):
        return False
    base = parts[-1]
    return base.endswith(SOURCE_EXTS) or base in MANIFESTS or base.endswith(".csproj") or base.endswith(".md")

def list_files(project_dir):
    try:
        r = subprocess.run(["git", "-C", project_dir, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, timeout=10)
        if r.returncode == 0:
            rels = [p.decode("utf-8", "replace") for p in r.stdout.split(b"\0") if p]
            return sorted(p for p in rels if _keep(p))
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), project_dir).replace(os.sep, "/")
            if _keep(rel):
                out.append(rel)
    return sorted(out)

_SYMBOL_RES = {
    "ts": re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)", re.M),
    "py": re.compile(r"^(?:class|def)\s+([A-Za-z]\w*)", re.M),
    "go": re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Z]\w*)", re.M),
    "rs": re.compile(r"^pub\s+(?:fn|struct|enum|trait|type)\s+([A-Za-z_]\w*)", re.M),
    "swift": re.compile(r"^(?!\s*(?:private|fileprivate)\b)(?:(?:public|open|internal|final)\s+)*(?:class|struct|enum|protocol|func|actor)\s+([A-Za-z_]\w*)", re.M),
    "cs": re.compile(r"^(?:(?:public|internal|private|protected|static|abstract|sealed|partial)\s+)*(?:class|interface|record|struct|enum)\s+([A-Za-z_]\w*)", re.M),
    "rb": re.compile(r"^\s*(?:class|module|def)\s+(?:self\.)?([A-Za-z_]\w*)", re.M),
}
_EXT_LANG = {".ts": "ts", ".tsx": "ts", ".js": "ts", ".jsx": "ts", ".vue": "ts", ".svelte": "ts", ".py": "py", ".go": "go",
             ".rs": "rs", ".swift": "swift", ".cs": "cs", ".java": "cs", ".kt": "cs", ".scala": "cs", ".rb": "rb"}

def extract_symbols(text, ext):
    rx = _SYMBOL_RES.get(_EXT_LANG.get(ext, ""))
    if rx is None:
        return []
    out = []
    for m in rx.finditer(text):
        name = m.group(1)
        if name.startswith("_") or name in out:
            continue
        out.append(name)
        if len(out) >= MAX_SYMBOLS:
            break
    return out

_TS_FROM_RE = re.compile(r"""(?:^|\n)\s*(?:import|export)\b[^'"]*?from\s*['"](\.{1,2}/[^'"]+)['"]""")
_TS_REQUIRE_RE = re.compile(r"""require\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)""")
_TS_SIDE_EFFECT_RE = re.compile(r"""(?:^|\n)\s*import\s*['"](\.{1,2}/[^'"]+)['"]""")
_GO_IMPORT_RE = re.compile(r'"([^"\s]+)"')
_PY_IMPORT_RE = re.compile(r"^\s*from\s+(\.+)([\w.]*)\s+import", re.M)
_TS_CANDIDATES = ("", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js")

def _norm(base_dir, target):
    return os.path.normpath(os.path.join(base_dir, target)).replace(os.sep, "/")

def go_module(project_dir):
    m = re.search(r"^module\s+(\S+)", _read(os.path.join(project_dir, "go.mod")), re.M)
    return m.group(1) if m else ""

def extract_imports(rel_path, text, all_files, go_module=""):
    base = os.path.dirname(rel_path)
    ext = os.path.splitext(rel_path)[1]
    found = []
    if ext == ".go" and go_module:
        for m in _GO_IMPORT_RE.finditer(text):
            imp = m.group(1)
            if imp == go_module or not imp.startswith(go_module + "/"):
                continue
            pkg = imp[len(go_module) + 1:]
            found += sorted(f for f in all_files if f.startswith(pkg + "/") and f.endswith(".go") and "/" not in f[len(pkg) + 1:])[:5]
    elif _EXT_LANG.get(ext) == "ts":
        for rx in (_TS_FROM_RE, _TS_REQUIRE_RE, _TS_SIDE_EFFECT_RE):
            for m in rx.finditer(text):
                target = _norm(base, m.group(1))
                for cand in _TS_CANDIDATES:
                    if target + cand in all_files:
                        found.append(target + cand); break
    elif ext == ".py":
        for m in _PY_IMPORT_RE.finditer(text):
            dots, mod = m.group(1), m.group(2)
            up = base
            for _ in range(len(dots) - 1):
                up = os.path.dirname(up)
            target = _norm(up, mod.replace(".", "/")) if mod else up
            for cand in (target + ".py", target + "/__init__.py"):
                if cand in all_files:
                    found.append(cand); break
    out = []
    for f in found:
        if f != rel_path and f not in out:
            out.append(f)
    return sorted(out)

def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""

def manifest_deps(project_dir):
    deps = set()
    pj = _read(os.path.join(project_dir, "package.json"))
    if pj:
        try:
            d = json.loads(pj)
            for k in ("dependencies", "devDependencies", "peerDependencies"):
                deps.update((d.get(k) or {}).keys())
        except ValueError:
            pass
    req = _read(os.path.join(project_dir, "requirements.txt"))
    for line in req.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-")):
            deps.add(re.split(r"[<>=!~\[; ]", line, 1)[0])
    py = _read(os.path.join(project_dir, "pyproject.toml"))
    for m in re.finditer(r'^\s*"?([A-Za-z0-9_.\-]+)"?\s*(?:[<>=!~]|$)', re.sub(r"(?s).*?dependencies\s*=\s*\[", "", py, 1).split("]")[0], re.M) if "dependencies" in py else []:
        deps.add(m.group(1))
    for table in re.finditer(r'^\[tool\.poetry\.(?:dependencies|dev-dependencies|group\.[\w-]+\.dependencies)\]\s*\n((?:(?!\[)[^\n]*\n?)*)', py, re.M):
        for m in re.finditer(r'^\s*"?([A-Za-z0-9_.\-]+)"?\s*=', table.group(1), re.M):
            if m.group(1) != "python":
                deps.add(m.group(1))
    gm = _read(os.path.join(project_dir, "go.mod"))
    for m in re.finditer(r"^\s*([\w.\-/]+\.[a-z]+/[\w.\-/]+)\s+v[\w.\-+]+", gm, re.M):
        deps.add(m.group(1))
    for m in re.finditer(r"^\s*require\s+([\w.\-/]+\.[a-z]+/[\w.\-/]+)\s+v[\w.\-+]+", gm, re.M):
        deps.add(m.group(1))
    cargo = _read(os.path.join(project_dir, "Cargo.toml"))
    if "[dependencies]" in cargo:
        for m in re.finditer(r"^([A-Za-z0-9_\-]+)\s*=", cargo.split("[dependencies]", 1)[1].split("\n[", 1)[0], re.M):
            deps.add(m.group(1))
    swift = _read(os.path.join(project_dir, "Package.swift"))
    for m in re.finditer(r'\.package\([^)]*?url:\s*"[^"]*/([^/"]+?)(?:\.git)?"', swift):
        deps.add(m.group(1))
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and root[len(project_dir):].count(os.sep) < 3]
        for name in files:
            if name.endswith(".csproj"):
                for m in re.finditer(r'PackageReference\s+Include="([^"]+)"', _read(os.path.join(root, name))):
                    deps.add(m.group(1))
    return sorted(d for d in deps if d)

def fingerprint(project_dir):
    """'<HEAD sha>:<md5(git status --porcelain)[:8]>' — changes on commits AND on uncommitted edits. '' outside git."""
    import hashlib
    try:
        r = subprocess.run(["git", "-C", project_dir, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3)
        if r.returncode != 0:
            return ""
        st = subprocess.run(["git", "-C", project_dir, "status", "--porcelain"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() + ":" + hashlib.md5((st.stdout if st.returncode == 0 else "").encode("utf-8")).hexdigest()[:8]
    except (OSError, subprocess.SubprocessError):
        return ""

def content_key(project_dir, files=None):
    """Freshness key for a tree git cannot fingerprint: md5 over 'path:size:mtime_ns' lines.

    Without it `regenerate()` sees an empty fingerprint on a non-git repo and rebuilds on
    every call. '' when there is nothing to hash — the caller reports that as unknown.
    """
    import hashlib
    try:
        files = list_files(project_dir) if files is None else files
    except OSError:
        return ""
    h, seen = hashlib.md5(), False
    for rel in sorted(files):
        try:
            st = os.stat(os.path.join(project_dir, rel))
        except OSError:
            continue
        h.update(("%s:%d:%d\n" % (rel, st.st_size, st.st_mtime_ns)).encode("utf-8"))
        seen = True
    return "nogit:" + h.hexdigest()[:16] if seen else ""

def freshness_key(project_dir, files=None):
    """The git fingerprint when there is one, else the content key. '' when neither exists."""
    return fingerprint(project_dir) or content_key(project_dir, files)

def build_layer(project_dir, files=None):
    """`files` is a precomputed list_files() result — SessionStart passes it so `git ls-files`
    runs once per event instead of once per codemap entry point."""
    files = list_files(project_dir) if files is None else files
    fileset = set(files)
    gomod = go_module(project_dir)
    entries = []
    for rel in files:
        ext = os.path.splitext(rel)[1]
        if not rel.endswith(SOURCE_EXTS):
            continue
        text = _read(os.path.join(project_dir, rel))
        entries.append({"path": rel, "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
                        "symbols": extract_symbols(text, ext), "imports": extract_imports(rel, text, fileset, gomod)})
    return {"sha": freshness_key(project_dir, files), "files": entries, "deps": manifest_deps(project_dir), "generated_at": int(time.time())}

def _brain_dir(pdir):
    d = os.path.join(pdir, ".brain")
    os.makedirs(d, exist_ok=True)
    return d

def write_layer(pdir, layer):
    path = os.path.join(_brain_dir(pdir), "codelayer.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(layer, f, indent=1, sort_keys=True)
    os.replace(tmp, path)

def read_layer(pdir):
    try:
        with open(os.path.join(pdir, ".brain", "codelayer.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "codemap.md")
# `\S*` not `[0-9a-f:]*`: the freshness key is a git fingerprint OR a "nogit:<hex>" content key.
GEN_START_RE = re.compile(r"<!-- brain:generated:start sha=(\S*) -->\n?")
GEN_END = "<!-- brain:generated:end -->"

def gen_start(sha):
    return "<!-- brain:generated:start sha=%s -->" % sha

def split_codemap(text):
    m = GEN_START_RE.search(text)
    if not m or GEN_END not in text[m.end():]:
        return "", "", text
    end = text.index(GEN_END, m.end())
    curated = text[end + len(GEN_END):].lstrip("\n")
    return m.group(1), text[m.end():end], curated

def curated_template(slug):
    text = _read(TEMPLATE_PATH)
    return text.replace("{slug}", slug)

DEPS_LIMIT = 20         # a monorepo manifest can list hundreds; the map is a map, not an inventory

def _dir_of(path):
    return path.rsplit("/", 1)[0] if "/" in path else ""

def _file_line(f):
    syms = ", ".join(f["symbols"])
    return "%s  (%s)" % (f["path"], syms) if syms else f["path"]

def render_generated(layer, cap=150):
    deps = list(layer.get("deps") or [])
    if len(deps) > DEPS_LIMIT:
        deps = deps[:DEPS_LIMIT] + ["\u2026 (+%d more)" % (len(deps) - DEPS_LIMIT)]
    header = ["# Code map (generated \u2014 do not edit above the end marker)", "head: %s" % (layer.get("sha") or "-"),
              "deps: %s" % (", ".join(deps) or "-"), ""]
    budget = cap - len(header) - 1
    # key -> (owning directory, rendered line, files represented). A directory "owns" only the
    # lines directly beneath it, so each round collapses the deepest, fattest directory; a
    # parent becomes collapsible only once its children are single lines. The repo root ("")
    # is never a candidate, so top-level files always survive.
    items = dict((f["path"], (_dir_of(f["path"]), _file_line(f), 1)) for f in layer["files"])
    while len(items) > budget:
        owners = {}
        for key, (parent, _, _n) in items.items():
            if parent:
                owners.setdefault(parent, []).append(key)
        cand = sorted((-len(v), d) for d, v in owners.items() if len(v) > 1)
        if not cand:
            break                       # nothing left to fold — the trailer below takes over
        d = cand[0][1]
        total = sum(items[k][2] for k in owners[d])
        for k in owners[d]:
            del items[k]
        items[d + "/"] = (_dir_of(d), "%s/  (%d files, collapsed)" % (d, total), total)
    body = sorted(line for _, line, _ in items.values())
    if len(body) > budget:
        omitted = len(body) - (budget - 1)
        body = body[:budget - 1] + ["\u2026 (%d more files not shown \u2014 see .brain/codelayer.json)" % omitted]
    return "\n".join(header + body) + "\n"

def render_codemap(layer, curated):
    return gen_start(layer.get("sha") or "") + "\n" + render_generated(layer) + GEN_END + "\n\n" + curated.lstrip("\n")

def file_count(project_dir):
    return len(list_files(project_dir))

def _codemap_path(pdir):
    return os.path.join(pdir, "codemap.md")

def _write_codemap(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

def ensure(project_dir, pdir, files=None):
    path = _codemap_path(pdir)
    if os.path.exists(path):
        return False
    layer = build_layer(project_dir, files)
    write_layer(pdir, layer)
    _write_codemap(path, render_codemap(layer, curated_template(os.path.basename(pdir.rstrip("/")))))
    return True

def ensure_stub(project_dir, pdir):
    """Curated template + an EMPTY generated block (markers with `sha=` blank, no tree).

    For a repo too large to walk on the SessionStart path: the user gets the curated
    scaffold immediately and the detached `map --regen --force` fills the block in.
    An empty `sha=` never equals a real freshness key, so the next regenerate rebuilds.
    """
    path = _codemap_path(pdir)
    if os.path.exists(path):
        return False
    os.makedirs(pdir, exist_ok=True)
    _write_codemap(path, gen_start("") + "\n" + GEN_END + "\n\n" + curated_template(os.path.basename(pdir.rstrip("/"))))
    return True

def regenerate(project_dir, pdir, force=False, files=None):
    path = _codemap_path(pdir)
    if not os.path.exists(path):
        return ensure(project_dir, pdir, files)
    text = _read(path)
    stored_sha, _, curated = split_codemap(text)
    current = freshness_key(project_dir, files)
    if not force and current and current == stored_sha:
        return False
    layer = build_layer(project_dir, files)
    write_layer(pdir, layer)
    if not curated.strip():
        curated = curated_template(os.path.basename(pdir.rstrip("/")))
    _write_codemap(path, render_codemap(layer, curated))
    return True

def _split_cells(line):
    """Split a '|'-delimited table row on '|' outside '[[...]]' wikilinks (aliases contain '|')."""
    cells = []
    cur = []
    depth = 0
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if line.startswith("[[", i):
            depth += 1
            cur.append("[[")
            i += 2
            continue
        if line.startswith("]]", i):
            depth = max(0, depth - 1)
            cur.append("]]")
            i += 2
            continue
        if ch == "|" and depth == 0:
            cells.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    cells.append("".join(cur))
    return cells

def _table_rows(curated, heading, ncols):
    from brain import vault
    body = vault.get_section(curated, heading)
    rows = []
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in _split_cells(line.strip().strip("|"))]
        if len(cells) != ncols or set("".join(cells)) <= set("-: ") or cells[0] in ("module", "question"):
            continue
        rows.append(cells)
    return rows

def parse_modules(curated):
    return [{"module": r[0], "path": r[1], "responsibility": r[2], "links": r[3]} for r in _table_rows(curated, "Modules", 4)]

def parse_where(curated):
    return [{"question": r[0], "path": r[1]} for r in _table_rows(curated, "Where to look", 2)]
