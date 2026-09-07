"""Generated code layer: files, exported symbols, relative imports, manifest deps.
Deterministic; never touches the curated block of codemap.md (rendering lives in part 2)."""
import json, os, re, subprocess, time

SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".rb", ".java", ".kt", ".swift",
               ".vue", ".svelte", ".c", ".cpp", ".cs", ".php", ".scala", ".m", ".mm", ".h")
MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml", "Package.swift")
EXCLUDE_DIRS = ("node_modules", ".git", "dist", "build", "target", ".venv", "venv", "vendor", "__pycache__",
                ".next", "coverage", ".brain")
MAX_SYMBOLS = 8

def _keep(rel):
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts[:-1]):
        return False
    base = parts[-1]
    return base.endswith(SOURCE_EXTS) or base in MANIFESTS or base.endswith(".csproj") or base.endswith(".md")

def list_files(project_dir):
    try:
        r = subprocess.run(["git", "-C", project_dir, "ls-files", "-z"], capture_output=True, timeout=10)
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
    "swift": re.compile(r"^(?:(?:public|open|internal|final|private)\s+)*(?:class|struct|enum|protocol|func|actor)\s+([A-Za-z_]\w*)", re.M),
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

_TS_IMPORT_RE = re.compile(r"""(?:^|\n)\s*(?:import|export)\b[^'"\n]*?from\s*['"](\.{1,2}/[^'"]+)['"]|require\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)|(?:^|\n)\s*import\s*['"](\.{1,2}/[^'"]+)['"]""")
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
        for m in _TS_IMPORT_RE.finditer(text):
            target = _norm(base, m.group(1) or m.group(2) or m.group(3))
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
    gm = _read(os.path.join(project_dir, "go.mod"))
    for m in re.finditer(r"^\s*([\w.\-/]+\.[a-z]+/[\w.\-/]+)\s+v[\w.\-+]+", gm, re.M):
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

def build_layer(project_dir):
    files = list_files(project_dir)
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
    return {"sha": fingerprint(project_dir), "files": entries, "deps": manifest_deps(project_dir), "generated_at": int(time.time())}

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

def ensure(project_dir, pdir):
    """Create codemap.md if missing. Placeholder until the renderer lands (next task): reports nothing created."""
    return False
