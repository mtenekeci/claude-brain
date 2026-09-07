"""Per-prompt retrieval: match prompt terms against graph nodes and render a compact neighborhood.

Uses graph._score and graph._line — private-by-underscore but shared by design between the
`/brain query` renderers (graph.py) and this per-prompt hook path.
"""
import math, re
from brain import graph

STOP = set("the and for with that this from into what when where which how does your about have will just like also than then them they there their been were was are is it its of to in on at by an as or be do if we you can should would could please make sure".split())
DONE_SIGNALS = ("thanks", "thank you", "done", "ship it", "looks good", "lgtm", "that's all", "close this", "bye", "good job", "perfect")
_NEGATIONS = ("not", "isn't", "aren't", "don't", "never", "nothing", "isnt", "dont")
_SPAN_RE = re.compile(r"`([^`]+)`|\"([^\"]+)\"|'([^']{3,})'")
_WORD_RE = re.compile(r"[A-Za-z_][\w./-]{3,}")

def is_system_prompt(prompt):
    p = (prompt or "").lstrip()
    return p.startswith("<") or p.startswith("/")

def is_done_signal(prompt):
    """A DONE_SIGNALS phrase on a word boundary, unless negated within 3 words before it
    ("this isn't done yet" must not fire, but "thanks, ship it" must). "no" is a much weaker
    negator than the others ("no problem, ship it" is still a done signal) so it only counts
    when it is the word immediately before the signal ("no thanks" does not fire)."""
    p = (prompt or "").lower()
    if len(p) >= 80:
        return False
    for sig in DONE_SIGNALS:
        m = re.search(r"\b" + re.escape(sig) + r"\b", p)
        if not m:
            continue
        before = re.findall(r"[\w']+", p[:m.start()])[-3:]
        if any(w in _NEGATIONS for w in before):
            continue
        if before and before[-1] == "no":
            continue
        return True
    return False

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
    """[(line, [node ids that line names])] for one node's neighborhood. Every line is paired
    with exactly the ids it puts in front of the user, so a caller that later truncates lines
    (the 20-line render cap) can drop the matching ids too — dedup must track what was
    actually shown, not everything that was merely *considered* (e.g. a module's 6th file,
    never rendered because only files[:3] make the cut, must stay retrievable later)."""
    out = [(graph._line(g, n), [n.id])]
    if n.meta.get("responsibility"):
        out.append(("  %s" % n.meta["responsibility"], []))
    if n.type == "section":
        out.append(("  architecture.md § %s (line %s)" % (n.name, n.meta.get("line", "?")), []))
    files, rels = [], {}
    for other, etype, direction in g.edges_of(n.id):
        on = g.nodes[other]
        if etype == "contains" and direction == "out" and on.type == "file":
            syms = [g.nodes[o].name for o, t, d in g.edges_of(other) if t == "contains" and d == "out"][:3]
            files.append((other, "%s%s" % (on.path, " (%s)" % ", ".join(syms) if syms else "")))
        elif etype in ("uses", "decided-by", "see", "depends-on", "implements", "imports") and direction == "out":
            rels.setdefault(etype, []).append((other, "%s %s" % (on.type, other.split(":", 1)[1])))
        elif etype == "contains" and direction == "in" and on.type in ("module", "section"):
            rels.setdefault("in", []).append((other, "%s %s" % (on.type, other.split(":", 1)[1])))
    if files:
        shown = files[:3]
        out.append(("  files: " + " · ".join(t for _, t in shown), [fid for fid, _ in shown]))
    for k in ("uses", "decided-by", "see", "depends-on", "implements", "imports", "in"):
        if k in rels:
            shown = rels[k][:4]
            out.append(("  %s: %s" % (k, ", ".join(t for _, t in shown)), [rid for rid, _ in shown]))
    return out

def render_with_ids(g, nodes, limit=20):
    """(text, ids) — ids is exactly the set of node ids whose line survived the `limit`-line
    cap, for the hook to fold into its per-session dedup set."""
    if not nodes:
        return "", set()
    pairs = [("Brain: graph hits for \"%s\" —" % ", ".join(n.name for n in nodes), [])]
    for n in nodes:
        pairs += _neigh_lines(g, n)
    pairs = pairs[:limit]
    text = "\n".join(p[0] for p in pairs) + "\n"
    ids = set()
    for _, line_ids in pairs:
        ids.update(line_ids)
    return text, ids

def render(g, nodes, limit=20):
    text, _ = render_with_ids(g, nodes, limit)
    return text
