"""Identify the brain project for a working directory from its CLAUDE.md."""
import os, re

_BRAIN_RE = re.compile(r"^brain:\s*([A-Za-z0-9._-]+)\s*$", re.M)
_LEGACY_RE = re.compile(r"^vault:\s*(\S.*?)\s*$", re.M)

class Project(object):
    def __init__(self, slug, legacy, project_dir, claude_md):
        self.slug = slug
        self.legacy = legacy
        self.project_dir = project_dir
        self.claude_md = claude_md

def split_brain_block(text):
    """Return (brain_block, rest). brain_block runs from the top through the first
    line that is exactly '---' (inclusive, with its newline). If no separator, block = whole text."""
    m = re.search(r"^---\s*$\n?", text, re.M)
    if not m:
        return text, ""
    return text[:m.end()], text[m.end():]

def _from_dir(d):
    path = os.path.join(d, "CLAUDE.md")
    try:
        with open(path) as f:
            text = f.read()
    except (OSError, ValueError):
        return None
    head, _ = split_brain_block(text)
    m = _BRAIN_RE.search(head)
    if m:
        return Project(m.group(1), False, d, path)
    m = _LEGACY_RE.search(head)
    if m:
        slug = m.group(1).rstrip("/").split("/")[-1]
        if slug:
            return Project(slug, True, d, path)
    return None

def resolve_project(cwd):
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        p = _from_dir(env_dir)
        if p:
            return p
    home = os.path.expanduser("~")
    d = os.path.abspath(cwd)
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
    return os.path.join(vault, "projects", slug)
