import json, os

def make_vault(tmp, slug="demo", context_extra="", log_entries=None):
    """Create <tmp>/vault with _system/, concepts/, projects/<slug>/{context,architecture,log}.md."""
    # realpath: brain canonicalises every path it stores, and macOS tmpdirs are symlinked.
    vault = os.path.realpath(os.path.join(tmp, "vault"))
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
    repo = os.path.realpath(os.path.join(tmp, "repo"))
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
    # async_regen off by default: no fixture may spawn a real detached `map --regen` process.
    # The two tests that assert on the spawn re-enable it via extra={"async_regen": True}.
    cfg = {"vault": vault, "async_regen": False}
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

def make_source_tree(repo):
    """Small mixed TS/Python tree with a manifest, relative imports, and noise dirs."""
    import subprocess
    def w(rel, text):
        p = os.path.join(repo, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f: f.write(text)
    w("package.json", '{"name":"demo","dependencies":{"next-auth":"^4","pg":"^8"},"devDependencies":{"jest":"^29"}}')
    w("src/auth/session.ts", "import { verify } from './verify';\nimport x from '../db';\nexport class SessionStore {}\nexport function refresh() {}\nexport const TTL = 1;\n")
    w("src/auth/verify.ts", "export function verify() { return true }\nexport default function main() {}\n")
    w("src/db.ts", "export interface Conn {}\nexport type Row = {}\n")
    w("lib/util.py", "import os\nfrom .helpers import h\n\nclass Util:\n    pass\n\ndef run():\n    pass\n\ndef _private():\n    pass\n")
    w("lib/helpers.py", "def h():\n    return 1\n")
    w("node_modules/junk/index.js", "export function junk() {}\n")
    w("dist/out.js", "export function built() {}\n")
    w("README.md", "# Demo\n")
    w(".gitignore", "node_modules/\ndist/\n")
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "tree"], check=True)

def payload(event, cwd, session_id="s1", **kw):
    d = {"session_id": session_id, "cwd": cwd, "hook_event_name": event,
         "transcript_path": "/dev/null", "permission_mode": "default"}
    d.update(kw)
    return d

def make_graph_vault(tmp, slug="demo"):
    """make_vault + two concept notes (one with aliases, one used by another project) + richer architecture.md."""
    vault = make_vault(tmp, slug=slug)
    cdir = os.path.join(vault, "concepts")
    with open(os.path.join(cdir, "postgresql.md"), "w") as f:
        f.write("---\nconcept: PostgreSQL\ntype: infra\nupdated: 2026-01-01\naliases: [Postgres, pg]\n---\n\n# PostgreSQL\n\nRelational store.\n\n## Used by\n- [[projects/%s/context|%s]] — primary store\n- [[projects/other/context|other]] — also\n" % (slug, slug))
    with open(os.path.join(cdir, "nextauth.md"), "w") as f:
        f.write("---\nconcept: NextAuth\ntype: library\nupdated: 2026-01-01\n---\n\n# NextAuth\n\nAuth library.\n\n## Used by\n- [[projects/other/context|other]] — sessions\n")
    arch = os.path.join(vault, "projects", slug, "architecture.md")
    with open(arch, "w") as f:
        f.write("---\nproject: %s\ntype: architecture\n---\n\n# Arch\n\n## Auth\nSessions live in `src/auth/`. decided-by:: [[projects/%s/context#Decisions]]\nuses:: [[concepts/nextauth|NextAuth]]\n\n%s\n## not a heading\n%s\n\n## Storage\nAll DB calls go through `db.ts`; Postgres is the only store. see:: [[concepts/postgresql|PostgreSQL]]\n\n### Migrations\nRun with pg.\n" % (slug, slug, "`" * 3, "`" * 3))
    ctx = os.path.join(vault, "projects", slug, "context.md")
    with open(ctx, "a") as f:
        f.write("\nuses:: [[concepts/postgresql|PostgreSQL]] [[concepts/missing-one|Missing]]\n")
    return vault

def stub_popen(calls):
    """Intercept only the detached `map --regen` spawn, recording its argv tuple in `calls`.
    subprocess.run() (gitinfo) resolves Popen through the same module global, so every other
    call must still reach the real Popen. Returns the original for restoration."""
    from brain import hooks
    orig = hooks.subprocess.Popen
    def fake(*a, **k):
        if a and "--regen" in list(a[0]):
            calls.append(a)
            return type("P", (), {"pid": 1})()
        return orig(*a, **k)
    hooks.subprocess.Popen = fake
    return orig
