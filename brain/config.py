"""Config + plugin data dir. Single source for paths every other module needs."""
import json, os, time

from brain import vault      # stdlib-only module: importing it here cannot cycle

def _config_path():
    return os.environ.get("BRAIN_CONFIG") or os.path.expanduser("~/.claude/brain.config")

def load_config():
    """Return the parsed brain.config dict, or {} if missing/invalid. Read-only paths (hooks,
    `brain config` display, `vault_root()`) go through this — a malformed file must never raise
    here, or a hand-edited typo would silence every hook."""
    try:
        with open(_config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

_MALFORMED_CONFIG_ERROR = "brain: ~/.claude/brain.config is not valid JSON — fix or remove it before changing settings"

def _load_config_strict():
    """Like `load_config()`, but a mutating path (`set_value`, `init --vault`) needs to tell
    'missing' ({}) apart from 'malformed' — `load_config()` collapses both to {}, and rewriting
    a malformed-but-present file from that empty dict would silently discard every field a user
    hand-edited it to have. Raises ValueError on a present file that is not a JSON object; the
    file itself is never touched here."""
    try:
        with open(_config_path(), encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError(_MALFORMED_CONFIG_ERROR)
    if not isinstance(data, dict):
        raise ValueError(_MALFORMED_CONFIG_ERROR)
    return data

def vault_root():
    v = load_config().get("vault")
    # realpath: every path comparison downstream (hooks.under) assumes a canonical vault root.
    return os.path.realpath(os.path.expanduser(v)) if isinstance(v, str) and v else None

def save_config(data):
    """Atomic write of the full config dict to the config path. The trailing newline is kept:
    brain.config is a file people open and edit by hand."""
    vault.atomic_write(_config_path(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")

_GATE_VALUES = ("all", "commits", "off")
_ON_VALUES = ("on", "true", "1", "yes")
_OFF_VALUES = ("off", "false", "0", "no")
_BACKEND_VALUES = ("builtin", "graphify", "auto")

def set_value(key, value):
    """`brain config set` mechanics. `key` is one of vault|gate|async_regen|graph.backend.
    Raises ValueError on an invalid key or value; callers (the CLI) turn that into exit 1.
    Returns the full config dict after the write."""
    data = _load_config_strict()
    if key == "vault":
        v = os.path.realpath(os.path.expanduser(value))
        if not os.path.isdir(v):
            raise ValueError("brain: vault directory does not exist: %s" % v)
        data["vault"] = v
    elif key == "gate":
        if value not in _GATE_VALUES:
            raise ValueError("brain: gate must be one of %s" % ", ".join(_GATE_VALUES))
        data["gate"] = value
    elif key == "async_regen":
        if isinstance(value, bool):
            data["async_regen"] = value
        elif str(value).lower() in _ON_VALUES:
            data["async_regen"] = True
        elif str(value).lower() in _OFF_VALUES:
            data["async_regen"] = False
        else:
            raise ValueError("brain: async_regen must be on/off")
        # bool JSON round-trips fine, but callers that read it back as True/False rely on `value`
        # being what gets echoed — normalize once so the CLI does not have to re-derive it.
        value = data["async_regen"]
    elif key == "graph.backend":
        if value not in _BACKEND_VALUES:
            raise ValueError("brain: graph.backend must be one of %s" % ", ".join(_BACKEND_VALUES))
        data.setdefault("graph", {})["backend"] = value
    else:
        raise ValueError("brain: unknown config key: %s" % key)
    save_config(data)
    return data

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
