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

def save_config(data):
    """Atomic tmp+replace write of the full config dict to the config path."""
    path = _config_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)

def set_value(key, value):
    """Minimal `brain config set` mechanics. `vault` is expanduser+realpath'd and must already
    exist as a directory — callers (e.g. `brain init --vault`) create it first. Task 3 extends
    this with more keys/validation; keep additions here self-contained."""
    data = load_config()
    if key == "vault":
        v = os.path.realpath(os.path.expanduser(value))
        if not os.path.isdir(v):
            raise ValueError("brain: vault directory does not exist: %s" % v)
        value = v
    data[key] = value
    save_config(data)
    return value

def gate_mode():
    """'all' (default) | 'commits' | 'off' — Stop-gate setting (spec §7.7)."""
    return str(load_config().get("gate", "all"))

def async_regen():
    """False disables the detached codemap regeneration hooks spawn on SessionStart/source edits.
    Default True; tests and users who want no background processes set "async_regen": false."""
    return bool(load_config().get("async_regen", True))

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
