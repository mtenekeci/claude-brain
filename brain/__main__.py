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
    """Never raise. What a crash *means*, though, differs by path:

    - `hook <Event>`: silent, exit 0. Any failure below the dispatch layer (unreadable stdin,
      broken config, import error) is logged and swallowed — the hook contract is "silent
      unless it has something to say", and a nonzero exit would surface in the session.
    - a CLI subcommand: the contract is 0 (ok) / 1 (refused) / 2 (not configured). Reporting a
      crash as 0 tells the caller — a user, or the skill — that the command succeeded.
    """
    is_hook = bool(argv is None and sys.argv[1:2] == ["hook"]) or bool(argv and list(argv)[:1] == ["hook"])
    try:
        return _run(argv)
    except Exception as e:
        try:
            from brain import config
            config.log_error("main: %r" % e)
        except Exception:
            pass
        if is_hook:
            return 0
        sys.stderr.write("brain: %s\n" % e)
        return 1

if __name__ == "__main__":
    sys.exit(main())
