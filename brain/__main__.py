#!/usr/bin/env python3
"""Entry point for hooks (`hook <Event>`, stdin JSON) and the CLI (Plan 3 adds subcommands).
Invoked directly by path, so bootstrap sys.path to import the `brain` package."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _run(argv):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: brain hook <Event> | brain <command> ...")
        return 1
    if argv[0] == "hook":
        from brain import hooks
        event = argv[1] if len(argv) > 1 else ""
        raw = sys.stdin.read() if sys.stdin is not None else ""   # stdin can be closed
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except ValueError:
            payload = {}
        result = hooks.dispatch(event, payload)
        if result.json is not None:
            sys.stdout.write(json.dumps(result.json))
        elif result.stdout:
            sys.stdout.write(result.stdout)
        return result.exit_code
    from brain import cli
    return cli.run(argv)

def main(argv=None):
    """Never raise and never emit anything Claude Code would surface: any failure below
    the dispatch layer (unreadable stdin, broken config, import error) is logged and
    exits 0 silently. The hook contract is 'silent unless it has something to say'."""
    try:
        return _run(argv)
    except Exception as e:
        try:
            from brain import config
            config.log_error("main: %r" % e)
        except Exception:
            pass
        return 0

if __name__ == "__main__":
    sys.exit(main())
