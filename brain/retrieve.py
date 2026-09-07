"""Per-prompt retrieval: match prompt terms against graph nodes and render a compact neighborhood.

Uses graph._score and graph._line — private-by-underscore but shared by design between the
`/brain query` renderers (graph.py) and this per-prompt hook path.
"""
import math, re
from brain import graph

STOP = set("the and for with that this from into what when where which how does your about have will just like also than then them they there their been were was are is it its of to in on at by an as or be do if we you can should would could please make sure".split())
DONE_SIGNALS = ("thanks", "thank you", "done", "ship it", "looks good", "lgtm", "that's all", "close this", "bye", "good job", "perfect")
_SPAN_RE = re.compile(r"`([^`]+)`|\"([^\"]+)\"|'([^']{3,})'")
_WORD_RE = re.compile(r"[A-Za-z_][\w./-]{3,}")

def is_system_prompt(prompt):
    p = (prompt or "").lstrip()
    return p.startswith("<") or p.startswith("/")

def is_done_signal(prompt):
    p = (prompt or "").lower()
    return len(p) < 80 and any(s in p for s in DONE_SIGNALS)

def tokens(prompt, limit=12):
    out = []
    text = prompt or ""
    for m in _SPAN_RE.finditer(text):
        t = (m.group(1) or m.group(2) or m.group(3) or "").strip().lower()
        if t and t not in out:
            out.append(t)
    text = _SPAN_RE.sub(" ", text)
    for m in _WORD_RE.finditer(text):
        t = m.group(0).lower().strip("./-")
        if len(t) >= 4 and t not in STOP and t not in out:
            out.append(t)
    return out[:limit]

def select(g, terms, already, max_nodes=3):
    """Rank by (terms matched, weighted score). Coverage across distinct prompt terms is the
    primary key so a curated module/section that matches several terms outranks a single file
    or symbol node that only happens to score high on one exact term (e.g. its own filename
    stem) — a plain best-score-per-node comparison let low-level file hits crowd out the more
    useful higher-level node. File/symbol nodes are also discounted (0.5, not the 0.8 an
    earlier draft used) so they still lose to a comparably-covering module/section on ties.
    """
    best = {}   # id -> [total weighted score, terms matched, node]
    for term in terms:
        for n in graph.find(g, term, limit=10):
            if n.id in already:
                continue
            s = graph._score(n, term) * (1.0 + math.log1p(g.degree(n.id)))
            if n.type in ("file", "symbol"):
                s *= 0.5
            entry = best.setdefault(n.id, [0.0, 0, n])
            entry[0] += s
            entry[1] += 1
    ranked = sorted(best.values(), key=lambda x: (-x[1], -x[0], x[2].type in ("file", "symbol"), x[2].id))
    return [n for _, _, n in ranked[:max_nodes]]

def _neigh_lines(g, n):
    lines = [graph._line(g, n)]
    if n.meta.get("responsibility"):
        lines.append("  %s" % n.meta["responsibility"])
    if n.type == "section":
        lines.append("  architecture.md § %s (line %s)" % (n.name, n.meta.get("line", "?")))
    files, rels = [], {}
    for other, etype, direction in g.edges_of(n.id):
        on = g.nodes[other]
        if etype == "contains" and direction == "out" and on.type == "file":
            syms = [g.nodes[o].name for o, t, d in g.edges_of(other) if t == "contains" and d == "out"][:3]
            files.append("%s%s" % (on.path, " (%s)" % ", ".join(syms) if syms else ""))
        elif etype in ("uses", "decided-by", "see", "depends-on", "implements", "imports") and direction == "out":
            rels.setdefault(etype, []).append("%s %s" % (on.type, other.split(":", 1)[1]))
        elif etype == "contains" and direction == "in" and on.type in ("module", "section"):
            rels.setdefault("in", []).append("%s %s" % (on.type, other.split(":", 1)[1]))
    if files:
        lines.append("  files: " + " · ".join(files[:3]))
    for k in ("uses", "decided-by", "see", "depends-on", "implements", "imports", "in"):
        if k in rels:
            lines.append("  %s: %s" % (k, ", ".join(rels[k][:4])))
    return lines

def mentioned_ids(g, nodes):
    """Every node id that would appear in render()'s neighborhood text for `nodes` — the
    selected nodes themselves plus their contained files/symbols and relation targets.
    The hook folds these into the per-session dedup set, not just the top-level ids: a file
    contained by an already-shown module still names that module via its own `in:` backlink
    (see _neigh_lines), so without this a later turn re-selecting that file would silently
    re-surface the module's context. Marking descendants as seen too keeps a session from
    repeating the same neighborhood under a different node.
    """
    ids = set()
    for n in nodes:
        ids.add(n.id)
        for other, etype, direction in g.edges_of(n.id):
            on = g.nodes[other]
            if etype == "contains" and direction == "out" and on.type == "file":
                ids.add(other)
                for o2, t2, d2 in g.edges_of(other):
                    if t2 == "contains" and d2 == "out":
                        ids.add(o2)
            elif etype in ("uses", "decided-by", "see", "depends-on", "implements", "imports") and direction == "out":
                ids.add(other)
            elif etype == "contains" and direction == "in" and on.type in ("module", "section"):
                ids.add(other)
    return ids

def render(g, nodes, limit=20):
    if not nodes:
        return ""
    lines = ["Brain: graph hits for \"%s\" —" % ", ".join(n.name for n in nodes)]
    for n in nodes:
        lines += _neigh_lines(g, n)
    return "\n".join(lines[:limit]) + "\n"
