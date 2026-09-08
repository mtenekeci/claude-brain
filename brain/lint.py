"""Deterministic concept reconciliation.

Writes only two things, ever: `uses::` lines in a project's `context.md ## Architecture`
and `- [[projects/<slug>/context|<slug>]] — <note>` lines in a concept note's `## Used by`.
Everything else it touches is read-only. Never raises on missing files — it runs on the
SessionStart path, where an exception would cost the user their context injection.
"""
import json, os, re
from brain import config, vault, graph, codemap

AUTO_APPLY_LIMIT = 5    # auto-apply edits shared concept notes: bound how many one pass rewrites
CANDIDATE_LIMIT = 5
DANGLING_RENDER_LIMIT = 8
RENDER_LINE_LIMIT = 40

def _brain_dir(pdir):
    d = os.path.join(pdir, ".brain")
    os.makedirs(d, exist_ok=True)
    return d

def load_dismissed(pdir):
    try:
        with open(os.path.join(pdir, ".brain", "dismissed.json"), encoding="utf-8") as f:
            return set(json.load(f).get("candidates", []))
    except (OSError, ValueError, AttributeError):
        return set()

def dismiss(pdir, slug):
    d = load_dismissed(pdir)
    d.add(slug)
    # atomic: a torn write here silently un-dismisses, and two sessions in one project can
    # dismiss at the same moment — vault.atomic_write owns both problems.
    vault.atomic_write(os.path.join(_brain_dir(pdir), "dismissed.json"),
                       json.dumps({"candidates": sorted(d)}, indent=1))

def _concepts(g):
    """Concept nodes, sorted by id — Node has no ordering, and matching must be deterministic."""
    return sorted((n for n in g.nodes.values() if n.type == "concept"), key=lambda n: n.id)

def _concept_keys(n):
    """Literal, lowercased identities of a concept: slug, display name, aliases."""
    keys = {n.id.split(":", 1)[1].lower(), (n.name or "").lower()} | {a.lower() for a in n.aliases}
    return {k for k in keys if k}

def _norm(s):
    """Fold a package/concept name to comparable form: lowercase, alphanumerics only.

    Package names carry separators the concept slug drops ("next-auth" vs `nextauth.md`),
    so literal equality alone misses the match the whole auto-apply rule depends on.
    """
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

def _match_keys(n):
    return {k for k in (_norm(x) for x in _concept_keys(n)) if k}

def match_deps_to_concepts(deps, g):
    """dep name -> concept id. Case- and separator-insensitive; `@scope/name` also tries `name`."""
    concepts = _concepts(g)
    out = {}
    for dep in deps or []:
        forms = {_norm(dep), _norm(dep.split("/")[-1])}
        forms.discard("")
        for n in concepts:
            if forms & _match_keys(n):
                out[dep] = n.id
                break
    return out

def typed_targets(g, slug):
    """Concept ids reachable by a TYPED edge from the project node or any node it contains.

    A typed link written on a module, section, decision or question is the project's link —
    requiring it on the project node itself would flag every properly-documented concept.
    """
    pid = graph.node_id("project", slug)
    owned = {pid} | {o for o, t, d in g.edges_of(pid) if t == "contains" and d == "out"}
    return {e.dst for e in g.edges
            if e.src in owned and e.type in graph.TYPED and e.dst.startswith("concept:")}

def apply_auto(vault_root, slug, concept_slug, name, note, add_link, apply=True):
    """Append the `uses::` line (when `add_link`) and the `## Used by` row. True if anything was
    (or, with `apply=False`, would be) written — `apply=False` computes the same condition
    without touching either file, for a display-only caller like `brain status`."""
    pdir = os.path.join(vault_root, "projects", slug)
    ctx_path = os.path.join(pdir, "context.md")
    text = vault.read(ctx_path)
    wrote = False
    link = "uses:: [[concepts/%s|%s]]" % (concept_slug, name)
    if add_link and text and link not in text:
        if apply:
            lines = vault.get_section(text, "Architecture").splitlines()
            # The `Full reference:` pointer is the section's last line by convention — stay above it.
            idx = next((i for i, l in enumerate(lines) if l.startswith("Full reference:")), len(lines))
            lines.insert(idx, link)
            vault.write(ctx_path, vault.replace_section(text, "Architecture", "\n".join(lines)))
        wrote = True
    cpath = os.path.join(vault_root, "concepts", concept_slug + ".md")
    ctext = vault.read(cpath)
    marker = "[[projects/%s/context|%s]]" % (slug, slug)
    if ctext and marker not in vault.get_section(ctext, "Used by"):
        if apply:
            body = vault.get_section(ctext, "Used by").rstrip("\n")
            body = (body + "\n" if body else "") + "- %s — %s" % (marker, note)
            vault.write(cpath, vault.replace_section(ctext, "Used by", body))
        wrote = True
    return wrote

SHORT_SLUG = 6

def _edit_distance(a, b, cap):
    """Levenshtein, but only accurate up to `cap` — anything further returns `cap + 1`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1                              # cheap reject: cannot be within `cap` edits
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]

def _near_threshold(sa, sb):
    """Edits allowed before two slugs count as near-duplicates, relative to the shorter one.

    A flat 2 is far too loose on short names: `jest`/`jwt` and `next`/`nuxt` are 2 apart and
    entirely unrelated. Below `SHORT_SLUG` chars a single edit is all the evidence there is.
    """
    return 1 if min(len(sa), len(sb)) < SHORT_SLUG else 2

def duplicates(g):
    """Concept pairs that share an identity key or sit within a length-relative edit distance.

    O(n²) over concepts, so it is computed only for the CLI report — never on the hook path.
    """
    concepts = _concepts(g)
    out = []
    for i, a in enumerate(concepts):
        for b in concepts[i + 1:]:
            sa, sb = a.id.split(":", 1)[1], b.id.split(":", 1)[1]
            cap = _near_threshold(sa, sb)
            if (_concept_keys(a) & _concept_keys(b)) or _edit_distance(sa, sb, cap) <= cap:
                out.append(tuple(sorted((sa, sb))))
    return sorted(set(out))

def _project_slugs(vault_root):
    pr = os.path.join(vault_root, "projects")
    try:
        return sorted(d for d in os.listdir(pr) if os.path.isfile(os.path.join(pr, d, "context.md")))
    except OSError:
        return []

def run(vault_root, slug, project_dir, g, all_projects=False, want_duplicates=False, apply=True):
    """Reconcile concepts for `slug` (or every project). Auto-applies manifest-dep links unless
    `apply=False`, in which case it computes the same `auto_applied` list — what it would write —
    without touching `context.md` or any concept note. `status` is display-only by contract and
    passes `apply=False`; SessionStart (`hooks.py`) and `sync-prepare` keep applying.

    `duplicates` is left empty unless `want_duplicates` — it is an O(n²) scan that only the CLI
    report displays, and `run()` is on the SessionStart path. `render(res, g)` fills it in on
    demand from the graph the caller already holds; the result dict stays plain JSON-safe data
    so it can be printed, logged or serialised without a live Graph object riding along.

    Every entry carries the project it came from as its own field; `render` is what turns that
    into the `<slug>: ` prefix, and only when the report covers more than one project. The
    stored slug stays bare on purpose — it is the argument the user pastes into
    `graph dismiss <slug>`, and a prefixed one is not a slug any more.
    """
    slugs = _project_slugs(vault_root) if all_projects else [slug]
    if slug not in slugs:
        slugs = [slug] + slugs
    result = {"auto_applied": [], "auto_pending": 0, "candidates": [], "stale": [], "dangling": [],
              "duplicates": duplicates(g) if want_duplicates else [], "projects": slugs, "applied": apply}
    for s in slugs:
        # Other projects build from their own vault dir; build()/load() tolerate project_dir=None
        # because the code layer is read from the vault's codelayer.json, not the repo.
        gg = g if s == slug else graph.load(vault_root, s, None)
        pdir = os.path.join(vault_root, "projects", s)
        pid = graph.node_id("project", s)
        typed = typed_targets(gg, s)
        dismissed = load_dismissed(pdir)
        layer = codemap.read_layer(pdir) or {}
        dep_matches = match_deps_to_concepts(layer.get("deps", []), gg)
        dep_concepts = set(dep_matches.values())
        for dep, cid in sorted(dep_matches.items()):
            n = gg.nodes[cid]
            if cid.split(":", 1)[1] in dismissed:
                continue        # dismissal is a standing "no" — auto-apply edits shared concept notes
            if [s, cid.split(":", 1)[1]] in result["auto_applied"]:
                continue        # two deps → one concept (jest + @types/jest): count the link once
            if len(result["auto_applied"]) >= AUTO_APPLY_LIMIT:
                result["auto_pending"] += 1     # deferred to the next run, and reported meanwhile
                continue
            try:
                wrote = apply_auto(vault_root, s, cid.split(":", 1)[1], n.name,
                                   "dependency `%s`" % dep, add_link=(cid not in typed), apply=apply)
            except OSError as e:                    # a read-only vault must not abort the whole report
                config.log_error("lint: could not auto-link %s in %s: %r" % (cid, s, e))
                wrote = False
            if wrote:
                result["auto_applied"].append([s, cid.split(":", 1)[1]])
            typed.add(cid)                          # written or already there: the link now exists
        mentioned = {e.dst for e in gg.edges if e.src == pid and e.type == "mentions"}
        for cid in sorted(mentioned - typed - dep_concepts):
            cslug = cid.split(":", 1)[1]
            if cslug not in dismissed:
                result["candidates"].append({"project": s, "slug": cslug, "name": gg.nodes[cid].name,
                                             "evidence": "mentioned in prose, no typed link"})
        # `used-by` edges are provenance from the concept note's own ## Used by claim.
        claimed = {e.dst for e in gg.edges if e.src == pid and e.type == "used-by"}
        for cid in sorted(claimed - typed - mentioned - dep_concepts):
            result["stale"].append([s, cid.split(":", 1)[1]])
        owned_prefixes = ("project:%s" % s, "section:%s/" % s, "module:", "decision:", "question:")
        # `module:`/`decision:`/`question:` ids are not slug-scoped, so two projects that both
        # contain a `module:api` report the same dangling pair — dedupe, keeping first-seen order.
        for d in gg.dangling:
            if str(d[0]).startswith(owned_prefixes) and d not in result["dangling"]:
                result["dangling"].append(d)
    if result["auto_applied"] and apply:
        graph.load(vault_root, slug, project_dir, force=True)   # our own writes just staled the cache
    return result

def health_line(res):
    """One line, or "" when there is nothing to say. Auto-applied writes are reported too:
    they edit shared concept notes, so the user has to be able to see them happen. When `res`
    came from a `run(..., apply=False)` display-only pass, the same `auto_applied` list is
    reported as pending instead — nothing was actually written."""
    n = len(res.get("candidates") or [])
    m = len(res.get("stale") or [])
    k = len(res.get("dangling") or [])
    a = len(res.get("auto_applied") or [])
    p = int(res.get("auto_pending") or 0)
    applied = res.get("applied", True)
    if not (n or m or k or a or p):
        return ""
    parts = []
    if n or m or k:
        parts.append("%d unlinked concept%s, %d stale Used-by entr%s, %d dangling link%s" % (
            n, "" if n == 1 else "s", m, "y" if m == 1 else "ies", k, "" if k == 1 else "s"))
    if a:
        if applied:
            parts.append("%d concept link%s auto-applied" % (a, "" if a == 1 else "s"))
        else:
            parts.append("%d link%s pending" % (a, "" if a == 1 else "s"))
    if p:
        parts.append("%d pending" % p)
    return "Brain: graph health — " + ", ".join(parts) + " (run /brain sync)"

def _labeller(res):
    """`(project, value) -> display string`. Prefixes `<project>: ` only when the report spans
    more than one project — a single-project report would just repeat the same slug on every
    line. Labelling lives here so `run()`'s data keeps bare, dismissable slugs."""
    if len(res.get("projects") or []) > 1:
        return lambda project, value: "%s: %s" % (project, value)
    return lambda project, value: value

def render(res, g=None):
    """`g` is only needed for the on-demand duplicate scan `run()` deliberately skipped."""
    label = _labeller(res)
    lines = ["lint: projects %s" % ", ".join(res.get("projects") or [])]
    if res.get("auto_applied"):
        pending = res.get("auto_pending") or 0
        verb = "auto-linked (manifest deps)" if res.get("applied", True) else "links pending (manifest deps, run /brain sync)"
        lines.append(verb + ": " + ", ".join(label(p, x) for p, x in res["auto_applied"])
                     + (" (+%d deferred to the next run)" % pending if pending else ""))
    c = res.get("candidates") or []
    if c:
        lines.append("candidates (confirm with a typed link, or dismiss):")
        lines += ["  - %s — %s (%s)" % (label(x.get("project", ""), x["slug"]), x["name"], x["evidence"])
                  for x in c[:CANDIDATE_LIMIT]]
        if len(c) > CANDIDATE_LIMIT:
            lines.append("  … and %d more" % (len(c) - CANDIDATE_LIMIT))
    if res.get("stale"):
        lines.append("stale Used-by (concept claims this project, no reference found): "
                     + ", ".join(label(p, x) for p, x in res["stale"]))
    dang = res.get("dangling") or []
    if dang:
        lines.append("dangling links:")
        lines += ["  - %s → [[%s]]" % (d[0], d[1]) for d in dang[:DANGLING_RENDER_LIMIT]]
        if len(dang) > DANGLING_RENDER_LIMIT:
            lines.append("  … and %d more" % (len(dang) - DANGLING_RENDER_LIMIT))
    # run() skips the O(n²) duplicate scan; pay for it here, where it is actually displayed.
    dups = res.get("duplicates") or (duplicates(g) if g is not None else [])
    if dups:
        lines.append("possible duplicate concepts: " + ", ".join("%s ~ %s" % d for d in dups))
    if len(lines) == 1:
        lines.append("clean")
    if len(lines) > RENDER_LINE_LIMIT:
        # Backstop only: every section above caps itself (CANDIDATE_LIMIT, DANGLING_RENDER_LIMIT),
        # so a full report lands around 20 lines and this never fires today. It exists so that a
        # future uncapped section degrades into a marked truncation rather than a silent one —
        # same reason as those caps: a report cut without a marker reads as a clean bill of health.
        lines = lines[:RENDER_LINE_LIMIT - 1] + ["… and %d more lines (run `graph lint` per project)" % (len(lines) - (RENDER_LINE_LIMIT - 1))]
    return "\n".join(lines) + "\n"
