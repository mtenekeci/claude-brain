"""Code-layer backends. `builtin` is the generated codemap layer; `graphify` reads a graph an
external `/graphify` run already produced. Selection is config-driven and always degrades to
builtin — a backend that cannot be read is a logged fallback, never an error."""
from brain import codemap, config

BUILTIN = "builtin"
GRAPHIFY = "graphify"


def select(project_dir):
    """Backend name for this project. `builtin` unless graph.backend says otherwise.

    An explicit `graphify` is taken as the user's stated intent and reported even when the
    tool is not installed — `code_layer` still falls back, and `graph ask` gets to say the
    query was attempted. `auto` only picks graphify when there is actually something to read.
    """
    mode = config.graph_backend()
    if mode == GRAPHIFY:
        return GRAPHIFY
    if mode == "auto" and project_dir:
        from brain.backends import graphify
        if graphify.available(project_dir):
            return GRAPHIFY
    return BUILTIN


def code_layer(project_dir, pdir):
    """(layer, backend name) for `graph.build`. The graphify layer when it is selected AND
    parseable, else the builtin layer read from the vault's `.brain/codelayer.json`."""
    if select(project_dir) == GRAPHIFY and project_dir:
        from brain.backends import graphify
        layer = graphify.code_layer(project_dir)
        if layer:
            return layer, GRAPHIFY
        config.log_error("graph: graphify backend unusable in %s — using the builtin code layer" % project_dir)
    return codemap.read_layer(pdir), BUILTIN
