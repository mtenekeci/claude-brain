"""`brain init` mechanics: vault bootstrap, project scaffold, index row, slim CLAUDE.md, permissions, seeding packet.
Writes templates and mechanical rows only — never prose."""
import json, os, subprocess, time
from brain import codemap, config, graph, migrate, project, vault

TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
MANIFESTS = ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "composer.json", "pom.xml", "build.gradle", "Package.swift")
INDEX_HEADER = "# Project Index\n\n| project | type | path | last-active |\n|---------|------|------|-------------|\n"
PACKET_SECTIONS = ("manifest", "readme", "git", "claude-md", "memory", "deps", "entry-points")


def slugify_name(name):
    return graph.slugify(name)


def _tpl(name):
    return vault.read(os.path.join(TEMPLATES, name))


def ensure_vault(vault_root):
    made = []
    for d in ("_system", "projects", "concepts"):
        p = os.path.join(vault_root, d)
        if not os.path.isdir(p):
            os.makedirs(p); made.append(d + "/")
    brain_md = os.path.join(vault_root, "_system", "BRAIN.md")
    if not os.path.exists(brain_md):
        vault.write(brain_md, _tpl("BRAIN.md")); made.append("_system/BRAIN.md")
    idx = os.path.join(vault_root, "_system", "project-index.md")
    if not os.path.exists(idx):
        vault.write(idx, INDEX_HEADER); made.append("_system/project-index.md")
    return made


def slug_exists(vault_root, slug):
    if os.path.exists(os.path.join(vault_root, "projects", slug, "context.md")):
        return True
    idx = vault.read(os.path.join(vault_root, "_system", "project-index.md"))
    return ("/%s/context" % slug) in idx


def _git(project_dir, *args):
    try:
        r = subprocess.run(["git", "-C", project_dir] + list(args), capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _head(path, n):
    text = vault.read(path)
    return "\n".join(text.splitlines()[:n]) if text else ""


def _memory_dir(project_dir):
    # Claude Code keeps the leading dash: /Users/x/p -> -Users-x-p. No lstrip("/") here.
    enc = os.path.realpath(project_dir).replace("/", "-")
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", enc, "memory")


def _packet_sections(project_dir):
    man = next((m for m in MANIFESTS if os.path.exists(os.path.join(project_dir, m))), None)
    manifest = ("%s\n%s" % (man, _head(os.path.join(project_dir, man), 80))) if man else ""

    readme = next((f for f in ("README.md", "README.rst", "README") if os.path.exists(os.path.join(project_dir, f))), None)
    readme_text = _head(os.path.join(project_dir, readme), 60) if readme else ""

    git = "\n".join(x for x in [
        _git(project_dir, "log", "--oneline", "-30"),
        "commits (90 days): %s" % (_git(project_dir, "rev-list", "--count", "--since=90 days ago", "HEAD") or "0"),
        "branches: " + _git(project_dir, "branch", "-a").replace("\n", " "),
        "remote: " + (_git(project_dir, "remote", "get-url", "origin") or "—")] if x)

    _, rest = project.split_brain_block(vault.read(os.path.join(project_dir, "CLAUDE.md")))
    claude_md = "\n".join(rest.splitlines()[:120])

    mdir = _memory_dir(project_dir)
    mem = []
    if os.path.isdir(mdir):
        for f in sorted(os.listdir(mdir))[:10]:
            if f.endswith(".md"):
                mem.append("### %s\n%s" % (f, _head(os.path.join(mdir, f), 40)))
    memory = "\n".join(mem)

    deps = ", ".join(codemap.manifest_deps(project_dir))

    entries = [f for f in codemap.list_files(project_dir)
               if os.path.splitext(os.path.basename(f))[0] in ("index", "main", "app", "server", "cli")
               and f.endswith(codemap.SOURCE_EXTS)][:10]
    entry_points = "\n".join(entries)

    return list(zip(PACKET_SECTIONS, (manifest, readme_text, git, claude_md, memory, deps, entry_points)))


def seeding_packet(project_dir, limit=6000):
    """Every section header always appears, even once the budget is exhausted — later sections
    fall back to a `(truncated)` placeholder body rather than being dropped, so the packet stays
    legible about what it is (and isn't) showing."""
    sections = _packet_sections(project_dir)
    # Reserve enough of the budget for a bare "## <name>\n(cut)\n" placeholder in every section
    # that follows the one that trips the cap, so no header is ever dropped outright.
    reserve = sum(len("## %s\n(cut)\n" % n) for n, _ in sections)
    out = []
    total = 0
    truncated = False
    for name, content in sections:
        content = (content or "").strip() or "(none)"
        if truncated:
            piece = "## %s\n(cut)\n" % name
        else:
            piece = "## %s\n%s\n\n" % (name, content)
            reserve -= len("## %s\n(cut)\n" % name)
            if total + len(piece) > limit - reserve:
                truncated = True
                budget = max(limit - reserve - total - len(name) - 20, 0)
                piece = "## %s\n%s\n… (truncated)\n" % (name, content[:budget])
        out.append(piece)
        total += len(piece)
    return "".join(out)


def _fill(text, **kw):
    for k, v in kw.items():
        text = text.replace("{%s}" % k, v)
    return text


def create_project(vault_root, slug, name, ptype, project_dir, repo_url):
    pdir = os.path.join(vault_root, "projects", slug)
    os.makedirs(pdir, exist_ok=True)
    date = time.strftime("%Y-%m-%d")
    path = os.path.realpath(project_dir) if ptype == "code" and project_dir else "—"
    written = {}

    ctx = os.path.join(pdir, "context.md")
    if not os.path.exists(ctx):
        vault.write(ctx, _fill(_tpl("context.md"), slug=slug, type=ptype, path=path, date=date, repo=repo_url or "—", name=name))
        written["context"] = ctx

    arch = os.path.join(pdir, "architecture.md")
    if not os.path.exists(arch):
        vault.write(arch,
            "---\nproject: %s\ntype: architecture\nupdated: %s\nup: \"[[projects/%s/context|%s]]\"\n---\n\n"
            "← [[projects/%s/context|%s context]] | [[projects/%s/log|Session Log]]\n\n"
            "# %s — Architecture Reference\n\n> Living document. Update when a new major component, pattern, or constraint is added.\n\n---\n\n"
            "## Technology Stack\n\n(populated on first sync)\n"
            % (slug, date, slug, slug, slug, slug, slug, name))
        written["architecture"] = arch

    log = os.path.join(pdir, "log.md")
    if not os.path.exists(log):
        vault.write(log, _fill(_tpl("log.md"), slug=slug, date=date))
        written["log"] = log

    idx = os.path.join(vault_root, "_system", "project-index.md")
    if ("/%s/context" % slug) not in vault.read(idx):
        vault.append(idx, "| [[projects/%s/context\\|%s]] | %s | %s | %s |\n" % (slug, slug, ptype, path, date))
        written["index"] = idx

    if ptype == "code" and project_dir:
        files = codemap.list_files(project_dir)
        if len(files) >= codemap.LARGE_REPO_FILES:
            codemap.ensure_stub(project_dir, pdir)
        else:
            codemap.ensure(project_dir, pdir, files=files)
        written["codemap"] = os.path.join(pdir, "codemap.md")

        cm = os.path.join(project_dir, "CLAUDE.md")
        if project.resolve_project(project_dir) is None:
            # v1 rule: absent -> slim_block; present with no brain line -> slim_block + existing
            # (the slim block already ends with "---\n", which becomes the separator). A leading
            # YAML frontmatter block stays on top — rewrite_block puts the slim block below it,
            # or the frontmatter stops being frontmatter. No backup: nothing is dropped here.
            migrate.rewrite_block(cm, lambda head: migrate.slim_block(name, slug),
                                  replace_existing=False, backup=False)
            written["claude_md"] = cm

    return written


def settings_path():
    return os.environ.get("BRAIN_USER_SETTINGS") or os.path.expanduser("~/.claude/settings.json")


def settings_shape_error(path=None):
    """None when the user settings file is absent, empty, or a well-shaped JSON object; else a
    single, uniform message (unparsable JSON and wrong-shaped JSON are indistinguishable to the
    caller — both mean 'fix it or pass --no-permissions'). Never writes."""
    path = path or settings_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return "brain: %s is not in the expected shape — fix it or pass --no-permissions" % path
    if not raw.strip():
        return None                                # 0-byte/whitespace-only file: benign, treat as absent
    try:
        data = json.loads(raw)
    except ValueError:
        return "brain: %s is not in the expected shape — fix it or pass --no-permissions" % path
    bad_shape = (not isinstance(data, dict)
                 or ("permissions" in data and not isinstance(data["permissions"], dict))
                 or (isinstance(data.get("permissions"), dict) and "allow" in data["permissions"]
                     and not isinstance(data["permissions"]["allow"], list)))
    if bad_shape:
        return "brain: %s is not in the expected shape — fix it or pass --no-permissions" % path
    return None


def preflight(vault_root, slug, ptype, project_dir, want_permissions=True):
    if slug_exists(vault_root, slug):
        return "Project '%s' already exists in the vault. Use `brain status` to see its state, or choose a different name." % slug
    if ptype == "code":
        if not project_dir or not os.path.isdir(project_dir):
            return "brain: project dir does not exist: %s" % project_dir
        existing = project.resolve_project(project_dir)
        if existing is not None and existing.slug != slug:
            return "brain: this folder is already connected to '%s' — run /brain status there, or /brain disconnect %s first" % (existing.slug, existing.slug)
    if want_permissions:
        return settings_shape_error()
    return None


def grant_permissions(vault_root, settings_path_override=None):
    path = settings_path_override or settings_path()
    if settings_shape_error(path):
        return 0                                   # preflight should have caught this; never rewrite what we cannot parse
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw) if raw.strip() else {}
    except OSError:
        raw, data = "", {}
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    wanted = ["Read(%s/**)" % vault_root, "Write(%s/**)" % vault_root, "Edit(%s/**)" % vault_root,
              'Bash(python3 "${CLAUDE_PLUGIN_ROOT}/brain/__main__.py" *)', 'Bash(python3 "*/brain/__main__.py" *)']
    added = 0
    for w in wanted:
        if w not in allow:
            allow.append(w); added += 1
    if added:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        bak = path + ".brain-bak"
        if raw and not os.path.exists(bak):
            vault.atomic_write(bak, raw)
        vault.atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return added
