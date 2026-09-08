"""Config + plugin data dir. Single source for paths every other module needs."""
import json, os, time

def _config_path():
    return os.environ.get("BRAIN_CONFIG") or os.path.expanduser("~/.claude/brain.config")

def load_config():
    """Return the parsed brain.config dict, or {} if missing/invalid."""
    try:
        with open(_config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def vault_root():
    v = load_config().get("vault")
    # realpath: every path comparison downstream (hooks.under) assumes a canonical vault root.
    return os.path.realpath(os.path.expanduser(v)) if isinstance(v, str) and v else None

def gate_mode():
    """'all' (default) | 'commits' | 'off' — Stop-gate setting (spec §7.7)."""
    return str(load_config().get("gate", "all"))

def async_regen():
    """False disables the detached codemap regeneration hooks spawn on SessionStart/source edits.
    Default True; tests and users who want no background processes set "async_regen": false."""
    return bool(load_config().get("async_regen", True))

def graph_backend():
    """'auto' (default) | 'builtin' | 'graphify' — which backend supplies the graph's code layer."""
    g = load_config().get("graph")
    v = g.get("backend", "auto") if isinstance(g, dict) else "auto"
    return str(v or "auto").strip().lower() if isinstance(v, str) else "auto"

def data_dir():
    d = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.claude/brain-data")
    os.makedirs(d, exist_ok=True)
    return d

def log_error(msg):
    try:
        with open(os.path.join(data_dir(), "brain.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg))
    except OSError:
        pass
