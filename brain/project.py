"""Identify the brain project for a working directory from its CLAUDE.md."""
import os, re

_BRAIN_RE = re.compile(r"^brain:\s*([A-Za-z0-9._-]+)\s*$", re.M)
_LEGACY_RE = re.compile(r"^vault:\s*(\S.*?)\s*$", re.M)

def valid_slug(slug):
    """A slug is joined onto <vault>/projects/ as a directory name. `.`, `..` and anything
    with a separator in it would silently resolve outside that directory."""
    return bool(slug) and not slug.startswith(".") and "/" not in slug and os.sep not in slug

class Project(object):
    def __init__(self, slug, legacy, project_dir, claude_md):
        self.slug = slug
        self.legacy = legacy
        self.project_dir = project_dir
        self.claude_md = claude_md

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n.*?^---[ \t]*$\n?", re.S | re.M)

def body_start(text):
    """Offset just past a leading YAML frontmatter block, or 0. The closing '---' of
    frontmatter is not the brain-block separator, so every separator search skips it."""
    m = _FRONTMATTER_RE.match(text)
    return m.end() if m else 0

def split_brain_block(text):
    """Return (brain_block, rest). brain_block runs from the top through the first
    line that is exactly '---' (inclusive, with its newline), ignoring a leading YAML
    frontmatter block. If no separator, block = whole text."""
    start = body_start(text)
    m = re.compile(r"^---\s*$\n?", re.M).search(text, start)
    if not m:
        return text, ""
    return text[:m.end()], text[m.end():]

def _from_dir(d):
    d = os.path.realpath(d)     # canonical project_dir: hooks.under() compares realpaths
    path = os.path.join(d, "CLAUDE.md")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, ValueError):
        return None
    head, _ = split_brain_block(text)
    m = _BRAIN_RE.search(head)
    if m and valid_slug(m.group(1)):
        return Project(m.group(1), False, d, path)
    m = _LEGACY_RE.search(head)
    if m:
        slug = m.group(1).rstrip("/").split("/")[-1]
        if valid_slug(slug):
            return Project(slug, True, d, path)
    return None

def resolve_project(cwd):
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        p = _from_dir(env_dir)
        if p:
            return p
    home = os.path.realpath(os.path.expanduser("~"))
    d = os.path.realpath(cwd)
    while True:
        if d != home:
            p = _from_dir(d)
            if p:
                return p
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent

def vault_project_dir(vault, slug):
    """<vault>/projects/<slug>. Raises ValueError on a slug that is not a bare directory name.

    The check lives HERE, not only in the CLI, because it is the one funnel every entry point
    goes through to turn a slug into a filesystem path — `cli._require_valid_slug` gives the
    user a clean message, and this makes a caller that forgets it fail loudly instead of
    writing outside projects/."""
    if not valid_slug(slug):
        raise ValueError("invalid slug %r" % (slug,))
    return os.path.join(vault, "projects", slug)
