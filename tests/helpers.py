import json, os, tempfile

def make_vault(tmp, slug="demo", context_extra="", log_entries=None):
    """Create <tmp>/vault with _system/, concepts/, projects/<slug>/{context,architecture,log}.md."""
    vault = os.path.join(tmp, "vault")
    proj = os.path.join(vault, "projects", slug)
    os.makedirs(os.path.join(vault, "_system"), exist_ok=True)
    os.makedirs(os.path.join(vault, "concepts"), exist_ok=True)
    os.makedirs(proj, exist_ok=True)
    with open(os.path.join(vault, "_system", "project-index.md"), "w") as f:
        f.write("# Project Index\n\n| project | type | path | last-active |\n|---|---|---|---|\n"
                "| [[projects/%s/context\\|%s]] | code | /old/path | 2026-01-01 |\n" % (slug, slug))
    with open(os.path.join(proj, "context.md"), "w") as f:
        f.write("---\nproject: %s\ntype: code\npath: /old/path\nrepo: —\nupdated: 2026-01-01\n"
                "up: \"[[_system/project-index]]\"\n---\n\n← [[_system/project-index|Project Index]]\n\n"
                "## State\nAlpha works.\n\n## Architecture\n- Uses Postgres.\nFull reference: [[projects/%s/architecture|Architecture]]\n\n"
                "## Active Work\nBuilding beta on branch feat/beta.\n\n## Decisions\n- **Use Postgres (2026-01-02)**: because.\n\n"
                "## Open Questions\n- Should we cache?\n\n## Hard Rules\n- Never commit directly to `main`.\n\n"
                "## Constraints\n- Node 20.\n%s" % (slug, slug, context_extra))
    with open(os.path.join(proj, "architecture.md"), "w") as f:
        f.write("---\nproject: %s\ntype: architecture\n---\n\n# Arch\n\n## Key Patterns & Conventions\n- All DB calls go through `db.ts`.\n" % slug)
    entries = log_entries or ["## 2026-01-01 · Session 1\nCompleted: init\nChanged: —\nDecided: none\nNext: start\n"]
    with open(os.path.join(proj, "log.md"), "w") as f:
        f.write("← [[projects/%s/context|%s context]]\n\n" % (slug, slug) + "\n".join(entries))
    return vault

def make_project(tmp, slug="demo", legacy=False, vault=None, git=True, extra_after_sep="# Repo notes\n"):
    """Create <tmp>/repo with CLAUDE.md (v2 `brain:` or legacy `vault:` line) and optionally a git repo."""
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, ".claude"), exist_ok=True)
    if legacy:
        head = "# Brain: %s\n\nvault: %s/projects/%s\n\n## Context protocol\nold text\n---\n" % (slug, vault, slug)
    else:
        head = "# Brain: %s\n\nbrain: %s\n\nVault context is injected by the claude-brain plugin.\n---\n" % (slug, slug)
    with open(os.path.join(repo, "CLAUDE.md"), "w") as f:
        f.write(head + extra_after_sep)
    if git:
        import subprocess
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        subprocess.run(["git", "-C", repo, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", repo, "config", "user.name", "t"], check=True)
        with open(os.path.join(repo, "a.py"), "w") as f: f.write("def a():\n    return 1\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "init"], check=True)
    return repo

def write_config(tmp, vault, extra=None):
    cfg = {"vault": vault}
    if extra: cfg.update(extra)
    path = os.path.join(tmp, "brain.config")
    with open(path, "w") as f: json.dump(cfg, f)
    os.environ["BRAIN_CONFIG"] = path
    os.environ["CLAUDE_PLUGIN_DATA"] = os.path.join(tmp, "data")
    # A real Claude Code session exports CLAUDE_PROJECT_DIR, which project.resolve_project()
    # consults before walking ancestors. Left set, it would resolve the *host* repo instead of
    # the fixture. Every fixture that configures a vault also isolates this.
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    return path

def payload(event, cwd, session_id="s1", **kw):
    d = {"session_id": session_id, "cwd": cwd, "hook_event_name": event,
         "transcript_path": "/dev/null", "permission_mode": "default"}
    d.update(kw)
    return d
