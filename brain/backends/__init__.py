"""Code-layer backends. `builtin` is the generated codemap layer; `graphify` reads a graph an
external `/graphify` run already produced. Selection is config-driven and always degrades to
builtin — a backend that cannot be read is a logged fallback, never an error."""
import os

from brain import codemap, config

BUILTIN = "builtin"
GRAPHIFY = "graphify"


def digest(path, prefix):
    """'<prefix><mtime_ns>-<size>', '' when the file is missing/unreadable.

    A cache key, not a checksum. It runs on `graph.load`'s cache-HIT path — which is the
    UserPromptSubmit path, once per prompt — so it must not read the file at all: hashing a
    large `graphify-out/graph.json` here was a per-prompt tax on exactly the case the cache
    exists to make free. `(st_mtime_ns, st_size)` changes whenever a rewrite does, which is all
    a staleness check needs; the cost of the rare miss it cannot see (a byte-identical-length
    rewrite within one mtime tick) is one stale graph until the next input changes.
    """
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return "%s%d-%d" % (prefix, st.st_mtime_ns, st.st_size)


def select(project_dir):
    """Backend name for this project. `builtin` unless graph.backend says otherwise.

    `graph.backend` lives in the single global brain.config but graphify graphs are per
    project, so even an explicit `graphify` degrades to builtin — silently — for a project
    that has no `graphify-out/graph.json`. That is the normal case, not a fault: logging it
    would spam brain.log from every hook on every other project.
    """
    mode = config.graph_backend()
    if mode not in (GRAPHIFY, "auto") or not project_dir:
        return BUILTIN
    from brain.backends import graphify
    if mode == GRAPHIFY:
        # Explicit: the graph is enough. `auto` additionally insists graphify can be run,
        # since nobody asked for it and `graph ask` would have nothing to call.
        return GRAPHIFY if os.path.isfile(graphify.graph_json(project_dir)) else BUILTIN
    return GRAPHIFY if graphify.available(project_dir) else BUILTIN


def source_key(project_dir, pdir):
    """(backend name, content key) with nothing parsed — `graph.load`'s cache check.

    The key changes whenever the selected backend's own input file changes, which is what
    makes a re-run of /graphify (or a codemap regeneration) stale a cache no vault mtime moved.
    """
    name = select(project_dir)
    if name == GRAPHIFY:
        from brain.backends import graphify
        return name, graphify.source_key(project_dir)
    return name, digest(os.path.join(pdir, ".brain", "codelayer.json"), "builtin:")


def code_layer(project_dir, pdir):
    """(layer, backend name) for `graph.build`. The graphify layer when it is selected AND
    parseable, else the builtin layer read from the vault's `.brain/codelayer.json`.

    Only `graphify.code_layer` logs, and only for a graph that exists but cannot be used.
    """
    if select(project_dir) == GRAPHIFY and project_dir:
        from brain.backends import graphify
        layer = graphify.code_layer(project_dir)
        if layer:
            return layer, GRAPHIFY
    return codemap.read_layer(pdir), BUILTIN
