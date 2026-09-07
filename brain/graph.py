"""Knowledge graph derived from the vault (+ code layer, part 2). A read-only index — never writes markdown."""
import json, os, re
from collections import deque
from brain import codemap
from brain import vault as vt

NODE_TYPES = ("project", "concept", "decision", "question", "module", "section", "file", "symbol")
TYPED = ("uses", "depends-on", "decided-by", "implements", "see")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]*))?(?:\|([^\]]*))?\]\]")
TYPED_LINK_RE = re.compile(r"\b(uses|depends-on|decided-by|implements|see)::\s*((?:\[\[[^\]]+\]\][ \t,]*)+)")
_FENCE = "`" * 3
# The trailing newline is deliberately left in place: removing a block must not pull the
# following line up onto the one before the fence.
_FENCE_RE = re.compile("^" + _FENCE + ".*?^" + _FENCE + r"[ \t]*$", re.S | re.M)

def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower())
    return s.strip("-")

def node_id(t, slug):
    return "%s:%s" % (t, slug)

def strip_fences(text):
    return _FENCE_RE.sub("", text)

def parse_aliases(value):
    v = (value or "").strip().strip("[]")
    return [a.strip().strip('"\'') for a in v.split(",") if a.strip()]

class Node(object):
    def __init__(self, id, type, name, path="", aliases=None, meta=None):
        self.id, self.type, self.name, self.path = id, type, name, path
        self.aliases = list(aliases or []); self.meta = dict(meta or {})
    def to_dict(self):
        return {"id": self.id, "type": self.type, "name": self.name, "path": self.path, "aliases": self.aliases, "meta": self.meta}
    @classmethod
    def from_dict(cls, d):
        return cls(d["id"], d["type"], d["name"], d.get("path", ""), d.get("aliases"), d.get("meta"))

class Edge(object):
    def __init__(self, src, dst, type):
        self.src, self.dst, self.type = src, dst, type

class Graph(object):
    def __init__(self):
        self.nodes, self.edges, self.dangling = {}, [], []
        self._seen = set(); self._adj = {}
    def has(self, id):
        return id in self.nodes
    def add_node(self, node):
        cur = self.nodes.get(node.id)
        if cur is None:
            self.nodes[node.id] = node; self._adj.setdefault(node.id, [])
            return node
        # A stub was created by a link before the real note was read: let the real one win
        # (name/path/meta), keeping the union of aliases. Merging would strand `external: True`.
        if cur.meta.get("external") and not node.meta.get("external"):
            cur.name, cur.path, cur.meta = node.name, node.path, dict(node.meta)
        for a in node.aliases:
            if a not in cur.aliases:
                cur.aliases.append(a)
        for k, v in node.meta.items():
            cur.meta.setdefault(k, v)
        return cur
    def record_dangling(self, src, target):
        """One shape for every unresolved reference: (src, raw target as written). Deduped."""
        if (src, target) not in self.dangling:
            self.dangling.append((src, target))
    def add_edge(self, src, dst, type):
        if src == dst:
            return                                  # self-loops carry no information and skew degree
        if dst not in self.nodes or src not in self.nodes:
            self.record_dangling(src, dst)
            return
        key = (src, dst, type)
        if key in self._seen:
            return
        self._seen.add(key); self.edges.append(Edge(src, dst, type))
        self._adj.setdefault(src, []).append((dst, type, "out")); self._adj.setdefault(dst, []).append((src, type, "in"))
    def edges_of(self, id):
        return list(self._adj.get(id, []))
    def degree(self, id):
        return len(self._adj.get(id, []))
    def neighbors(self, id, depth=1):
        dist, q = {}, deque([(id, 0)])
        while q:
            cur, d = q.popleft()
            if d >= depth:
                continue
            for other, _, _ in self._adj.get(cur, []):
                if other != id and other not in dist:
                    dist[other] = d + 1; q.append((other, d + 1))
        return dist
    def to_dict(self):
        return {"nodes": [n.to_dict() for n in self.nodes.values()], "edges": [[e.src, e.dst, e.type] for e in self.edges], "dangling": [list(x) for x in self.dangling]}
    @classmethod
    def from_dict(cls, d):
        g = cls()
        for n in d.get("nodes", []):
            g.add_node(Node.from_dict(n))
        for s, t, ty in d.get("edges", []):
            g.add_edge(s, t, ty)
        g.dangling = [tuple(x) for x in d.get("dangling", [])]
        return g

def _target(m):
    """Raw link target of a WIKILINK_RE match: 'page' or 'page#Heading'."""
    return m.group(1).strip() + ("#" + m.group(2) if m.group(2) else "")

def parse_links(text):
    """[(edge_type, raw_target)] in document order. Typed fields win; other wikilinks are links-to."""
    found, spans = [], []
    for m in TYPED_LINK_RE.finditer(text):
        for w in WIKILINK_RE.finditer(m.group(2)):
            found.append((m.start(2) + w.start(), m.group(1), _target(w)))
        spans.append((m.start(), m.end()))
    for w in WIKILINK_RE.finditer(text):
        if any(a <= w.start() < b for a, b in spans):
            continue
        found.append((w.start(), "links-to", _target(w)))
    # Position comes from the match itself — a target repeated in the document must keep
    # its own place, and a padded target ("[[ x ]]") has no stripped form to search for.
    found.sort(key=lambda item: item[0])
    return [(etype, raw) for _, etype, raw in found]

def resolve_link(raw, project_slug):
    target, _, heading = raw.partition("#")
    parts = target.strip("/").split("/")
    if parts[0] == "concepts" and len(parts) == 2:
        return node_id("concept", slugify(parts[1]))    # same normalisation as the note's filename stem
    if parts[0] == "projects" and len(parts) == 3:
        slug, page = parts[1], parts[2]
        if page == "architecture" and heading:
            return node_id("section", "%s/%s" % (slug, slugify(heading)))
        return node_id("project", slug)
    return None

def _headings(text):
    """(level, heading, line_no) for ##/### headings outside fences, 1-based line numbers."""
    out, in_fence = [], False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith(_FENCE):
            in_fence = not in_fence; continue
        if in_fence:
            continue
        m = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if m:
            out.append((len(m.group(1)), m.group(2), i))
    return out

def _section_bodies(text):
    """heading slug -> body text (until next ##/### heading), fences stripped.

    Keyed by slug and *accumulated*: two `## Notes` sections collapse to one section node,
    so both bodies must contribute their links instead of the last one winning.
    """
    lines = text.splitlines(); heads = _headings(text); bodies = {}
    for idx, (lvl, h, ln) in enumerate(heads):
        end = heads[idx + 1][2] - 1 if idx + 1 < len(heads) else len(lines)
        body = strip_fences("\n".join(lines[ln:end]))
        key = slugify(h)
        bodies[key] = bodies[key] + "\n" + body if key in bodies else body
    return bodies

def _bullet_title(b):
    m = re.match(r"\*\*(.+?)\*\*", b)
    return m.group(1).strip() if m else None

def _link_edges(g, src, text, project_slug):
    for etype, raw in parse_links(text):
        dst = resolve_link(raw, project_slug)
        if dst is None:
            continue
        if dst.startswith("section:") and not g.has(dst):
            other = dst.split(":", 1)[1].split("/", 1)[0]
            if other != project_slug:
                dst = node_id("project", other)        # a heading in another project's architecture → that project
        if dst.startswith("project:") and not g.has(dst):
            g.add_node(Node(dst, "project", dst.split(":", 1)[1], meta={"external": True}))
        if not g.has(dst):
            g.record_dangling(src, raw); continue
        g.add_edge(src, dst, etype)

def mention_edges(g, texts, project_slug):
    prose = strip_fences("\n".join(texts))
    prose = WIKILINK_RE.sub(" ", prose)
    src = node_id("project", project_slug)
    for n in list(g.nodes.values()):
        if n.type != "concept":
            continue
        for term in [n.name] + n.aliases:
            if len(term) < 4:
                continue
            if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(term), prose, re.I):
                g.add_edge(src, n.id, "mentions"); break

def build_vault_layer(g, vault_root, slug):
    pdir = os.path.join(vault_root, "projects", slug)
    ctx_path, arch_path = os.path.join(pdir, "context.md"), os.path.join(pdir, "architecture.md")
    ctx = vt.read(ctx_path); arch = vt.read(arch_path)
    fm, _ = vt.parse_frontmatter(ctx)
    pid = node_id("project", slug)
    # meta["vault"] lives on the project node so renderers can shorten vault paths without a global.
    g.add_node(Node(pid, "project", fm.get("project") or slug, path=ctx_path,
                    meta={"path": fm.get("path", ""), "vault": vault_root}))
    # concepts first so links/mentions can resolve
    cdir = os.path.join(vault_root, "concepts")
    concept_files = sorted(f for f in (os.listdir(cdir) if os.path.isdir(cdir) else []) if f.endswith(".md"))
    for f in concept_files:
        text = vt.read(os.path.join(cdir, f)); cfm, _ = vt.parse_frontmatter(text)
        cslug = slugify(f[:-3])
        g.add_node(Node(node_id("concept", cslug), "concept", cfm.get("concept") or cslug, path=os.path.join(cdir, f),
                        aliases=parse_aliases(cfm.get("aliases", "")), meta={"ctype": cfm.get("type", "")}))
    for f in concept_files:
        cid = node_id("concept", slugify(f[:-3])); text = vt.read(os.path.join(cdir, f))
        for w in WIKILINK_RE.finditer(vt.get_section(text, "Used by")):
            other = resolve_link(w.group(1), slug)
            if other and other.startswith("project:"):
                if not g.has(other):
                    g.add_node(Node(other, "project", other.split(":", 1)[1], meta={"external": True}))
                g.add_edge(other, cid, "used-by")       # provenance: the concept note's claim, not the project's own link
        body = strip_fences(re.sub(r"(?s)## Used by.*", "", text))
        _link_edges(g, cid, body, slug)
    # decisions / questions
    for sec, ntype in (("Decisions", "decision"), ("Open Questions", "question")):
        for b in vt.bullets(vt.get_section(ctx, sec)):
            title = _bullet_title(b) or (b.split(":")[0].strip() if ntype == "question" else None)
            if not title:
                continue
            nid = node_id(ntype, slugify(title))
            g.add_node(Node(nid, ntype, title, path=ctx_path, meta={"section": sec}))
            g.add_edge(pid, nid, "contains"); _link_edges(g, nid, b, slug)
    # architecture sections
    for lvl, h, ln in _headings(arch):
        sid = node_id("section", "%s/%s" % (slug, slugify(h)))
        g.add_node(Node(sid, "section", h, path=arch_path, meta={"line": ln, "level": lvl}))
        g.add_edge(pid, sid, "contains")
    for hslug, body in _section_bodies(arch).items():
        _link_edges(g, node_id("section", "%s/%s" % (slug, hslug)), body, slug)
    # context.md links (outside decisions/questions bullets → attributed to the project)
    _link_edges(g, pid, strip_fences(ctx), slug)
    mention_edges(g, [ctx, arch], slug)
    return g

# ---------------------------------------------------------------- code layer

def build_code_layer(g, project_slug, layer, modules):
    """File/symbol nodes from the generated layer + curated module rows bound to path prefixes."""
    pid = node_id("project", project_slug)
    files = (layer or {}).get("files", [])
    for f in files:
        fid = node_id("file", f["path"])
        g.add_node(Node(fid, "file", os.path.basename(f["path"]), path=f["path"], meta={"lines": f.get("lines", 0)}))
        for s in f.get("symbols", []):
            sid = node_id("symbol", "%s#%s" % (f["path"], s))
            g.add_node(Node(sid, "symbol", s, path=f["path"])); g.add_edge(fid, sid, "contains")
    for f in files:                                     # second pass: every import target now exists
        for imp in f.get("imports", []):
            g.add_edge(node_id("file", f["path"]), node_id("file", imp), "imports")
    for row in modules or []:
        mid = node_id("module", slugify(row["module"]))
        g.add_node(Node(mid, "module", row["module"], path=row["path"], meta={"responsibility": row.get("responsibility", "")}))
        g.add_edge(pid, mid, "contains")
        prefix = row["path"].rstrip("/")
        for f in files:
            if f["path"] == prefix or f["path"].startswith(prefix + "/"):
                g.add_edge(mid, node_id("file", f["path"]), "contains")
        _link_edges(g, mid, row.get("links", ""), project_slug)
    return g

def build(vault_root, slug, project_dir=None):
    """Full graph for one project. `project_dir` is accepted but unused — the code layer is read
    from the vault's own `.brain/codelayer.json`, so other projects' graphs build without their repo."""
    g = Graph()
    build_vault_layer(g, vault_root, slug)
    pdir = os.path.join(vault_root, "projects", slug)
    layer = codemap.read_layer(pdir)
    _, _, curated = codemap.split_codemap(vt.read(os.path.join(pdir, "codemap.md")))
    build_code_layer(g, slug, layer, codemap.parse_modules(curated))
    return g

# ---------------------------------------------------------------- cache

def inputs_mtime(vault_root, slug):
    """Newest mtime across every file the graph is derived from. The cache itself lives in
    `.brain/` and is deliberately not an input, so writing it cannot invalidate itself."""
    pdir = os.path.join(vault_root, "projects", slug)
    paths = [os.path.join(pdir, n) for n in ("context.md", "architecture.md", "codemap.md")] + [os.path.join(pdir, ".brain", "codelayer.json")]
    cdir = os.path.join(vault_root, "concepts")
    if os.path.isdir(cdir):
        paths.append(cdir); paths += [os.path.join(cdir, f) for f in os.listdir(cdir)]
    m = 0.0
    for p in paths:
        try:
            m = max(m, os.path.getmtime(p))
        except OSError:
            pass
    return m

def load(vault_root, slug, project_dir=None, force=False):
    """Cached build. Never raises: a missing/corrupt/stale cache falls back to a fresh build,
    and a cache that cannot be written is not fatal."""
    pdir = os.path.join(vault_root, "projects", slug)
    cache = os.path.join(pdir, ".brain", "graph.json")
    stamp = inputs_mtime(vault_root, slug)
    if not force:
        try:
            with open(cache, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("built_at", -1) >= stamp:
                return Graph.from_dict(d["graph"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    g = build(vault_root, slug, project_dir)
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        tmp = cache + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"built_at": stamp, "graph": g.to_dict()}, f)
        os.replace(tmp, cache)
    except OSError:
        pass
    return g

# ---------------------------------------------------------------- queries

FIND_LIMIT, NEAR_LIMIT, TOP_LIMIT = 15, 40, 12

def _haystack(n):
    base = os.path.basename(n.path or "")
    return [(n.name or "").lower(), n.id.split(":", 1)[1].lower(), base.lower(), os.path.splitext(base)[0].lower()] + [a.lower() for a in n.aliases]

def _score(n, term):
    """3 = exact id/name/alias/filename match, 2 = prefix, 1 = substring (path included), 0 = no match."""
    t = term.lower(); names = _haystack(n)
    if t in names:
        return 3
    if any(x.startswith(t) for x in names):
        return 2
    if any(t in x for x in names + [(n.path or "").lower()]):
        return 1
    return 0

def find(g, term, type=None, limit=FIND_LIMIT):
    term = (term or "").strip()
    if not term:
        return []
    scored = []
    for n in g.nodes.values():
        if type and n.type != type:
            continue
        s = _score(n, term)
        if s:
            scored.append((-s, -g.degree(n.id), n.id, n))
    scored.sort(key=lambda x: x[:3])
    return [x[3] for x in scored[:limit]]

def path(g, a, b):
    """Shortest undirected hop path a→b as node ids, [] if unreachable or unknown."""
    if a not in g.nodes or b not in g.nodes:
        return []
    prev, q = {a: None}, deque([a])
    while q:
        cur = q.popleft()
        if cur == b:
            break
        for other, _, _ in g.edges_of(cur):
            if other not in prev:
                prev[other] = cur; q.append(other)
    if b not in prev:
        return []
    out, cur = [], b
    while cur is not None:
        out.append(cur); cur = prev[cur]
    return list(reversed(out))

def top(g, n=TOP_LIMIT, exclude=("file", "symbol")):
    nodes = [x for x in g.nodes.values() if x.type not in exclude and not x.meta.get("external")]
    nodes.sort(key=lambda x: (-g.degree(x.id), x.id))
    return nodes[:n]

# ---------------------------------------------------------------- renderers

def _vault_root(g):
    for n in g.nodes.values():
        if n.type == "project" and n.meta.get("vault"):
            return n.meta["vault"]
    return ""

def _short_path(g, n):
    """Repo-relative for code nodes (already stored that way); vault-relative for vault notes."""
    p = n.path or "-"
    if p == "-" or n.type in ("file", "symbol", "module"):
        return p
    vault = _vault_root(g)
    if not vault:
        return p
    try:
        rel = os.path.relpath(p, vault)
    except ValueError:
        return p
    return p if rel.startswith("..") else rel

def _line(g, n):
    return "%s %s  %s  — %s" % (n.type, n.id.split(":", 1)[1], _short_path(g, n), n.name)

def render_find(g, nodes, limit=FIND_LIMIT):
    return "".join(_line(g, n) + "\n" for n in nodes[:limit])

def render_near(g, id, depth=1, limit=NEAR_LIMIT):
    """Node header, then one line per incident edge grouped by (type, direction)."""
    if id not in g.nodes:
        return ""
    n = g.nodes[id]
    lines = [_line(g, n)]
    if n.type == "section":
        lines.append("  architecture.md § %s (line %s)" % (n.name, n.meta.get("line", "?")))
    if n.meta.get("responsibility"):
        lines.append("  %s" % n.meta["responsibility"])
    groups = {}
    for other, etype, direction in g.edges_of(id):
        groups.setdefault((etype, direction), []).append(other)
    for (etype, direction), others in sorted(groups.items()):
        arrow = "→" if direction == "out" else "←"
        for o in sorted(others, key=lambda x: (-g.degree(x), x)):
            on = g.nodes[o]
            lines.append("  %s %s %s %s  %s" % (etype, arrow, on.type, o.split(":", 1)[1], _short_path(g, on)))
    if depth > 1:
        for o, d in sorted(g.neighbors(id, depth).items(), key=lambda kv: (kv[1], kv[0])):
            if d > 1:
                lines.append("  ·· %s" % _line(g, g.nodes[o]))
    return "\n".join(lines[:limit]) + "\n"

def render_path(g, ids):
    if not ids:
        return ""
    return " → ".join("%s %s" % (g.nodes[i].type, i.split(":", 1)[1]) for i in ids) + "\n"

def render_top(g, nodes, limit=TOP_LIMIT):
    return "".join("%s  (%d)\n" % (_line(g, n), g.degree(n.id)) for n in nodes[:limit])
