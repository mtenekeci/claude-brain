"""Code-layer backends. `builtin` is the generated codemap layer; `graphify` reads a graph an
external `/graphify` run already produced. Selection is config-driven and always degrades to
builtin — a backend that cannot be read is a logged fallback, never an error."""
import hashlib, os

from brain import codemap, config

BUILTIN = "builtin"
GRAPHIFY = "graphify"
_CHUNK = 1 << 16


def digest(path, prefix):
    """'<prefix><md5 of the file bytes>[:8]', '' when the file is missing/unreadable.

    Streamed and parse-free on purpose: this runs on `graph.load`'s cache-HIT path, where
    parsing the layer would be exactly the cost the cache exists to avoid.
    """
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return ""
    return prefix + h.hexdigest()[:8]


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
