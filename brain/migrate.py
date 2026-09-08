"""One-shot, idempotent upgrade of a v1 project to the v2 layout (spec §12)."""
import json, os, re
from brain import project, vault

_LEGACY_MARKERS = ("/brain-session-start.sh", "/brain-post-tool-use.sh", "/brain-precompact.sh", "/brain-session-end.sh")
_SEP_RE = re.compile(r"^---\s*$", re.M)

def slim_block(project_name, slug):
    """The CLAUDE.md brain block. `templates/CLAUDE.md` is this text with `{project-name}`
    and `{slug}` placeholders, kept for readers browsing the plugin's templates;
    `tests/test_migration.py::test_slim_block_matches_template` holds the two byte-identical,
    which is why the template file itself carries no explanatory comment."""
    return ("# Brain: %s\n\nbrain: %s\n\nVault context, protocol, and code map for this project are injected "
            "automatically by the claude-brain plugin at session start. If this session shows no \"Brain:\" block, "
            "run `/brain status`.\n---\n" % (project_name, slug))

def _display_name(head, slug):
    for line in head.splitlines():
        if line.startswith("# Brain:"):
            return line[len("# Brain:"):].strip() or slug
    return slug

def _has_separator(text):
    return bool(_SEP_RE.search(text, project.body_start(text)))   # frontmatter's closing --- is not it

def strip_legacy_hooks(settings_path):
    try:
        with open(settings_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 0
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    removed = 0
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue                                   # unknown shape: leave untouched
        kept_groups = []
        event_removed = 0
        for g in groups:
            if not isinstance(g, dict) or not isinstance(g.get("hooks"), list):
                kept_groups.append(g)                  # preserve irregular entries verbatim
                continue
            keep = [h for h in g["hooks"] if not (isinstance(h, dict) and any(m in str(h.get("command", "")) for m in _LEGACY_MARKERS))]
            event_removed += len(g["hooks"]) - len(keep)
            g["hooks"] = keep
            if keep:
                kept_groups.append(g)
        removed += event_removed
        hooks[event] = kept_groups
        if event_removed and not hooks[event]:
            del hooks[event]                           # only drop events that actually lost a hook
    if removed:
        if not hooks:
            del data["hooks"]
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return removed

def _settings_has_legacy(settings_path):
    try:
        with open(settings_path, encoding="utf-8") as f:
            return any(m in f.read() for m in _LEGACY_MARKERS)
    except (OSError, ValueError):
        return False

def _stale_path(proj, vault_root):
    fm, _ = vault.parse_frontmatter(vault.read(os.path.join(project.vault_project_dir(vault_root, proj.slug), "context.md")))
    p = fm.get("path", "")
    return bool(p) and p != "—" and not os.path.isdir(p) and os.path.isdir(proj.project_dir)

def needs_migration(proj, vault_root):
    return proj.legacy or _settings_has_legacy(os.path.join(proj.project_dir, ".claude", "settings.json")) or _stale_path(proj, vault_root)

def _backup_path(claude_md):
    """Never clobber an existing backup: a re-run (or an earlier migration) already holds
    content we cannot reproduce, so fall back to .brain-bak.1, .2, …"""
    base = claude_md + ".brain-bak"
    if not os.path.exists(base):
        return base
    n = 1
    while os.path.exists("%s.%d" % (base, n)):
        n += 1
    return "%s.%d" % (base, n)

def rewrite_block(claude_md, make_block, replace_existing=True, backup=True):
    """Rewrite a CLAUDE.md's brain block in place. Returns (head, rest, backup_path).

    The one place that knows how to do this safely, because there are four callers
    (`migrate_project`, `cli._cmd_repair`, `cli._strip_brain_block`, `initproj.create_project`)
    and every earlier copy of the logic lost something:

    - A leading YAML frontmatter block is part of `head` for `project.split_brain_block` (that
      is what `body_start` exists for), so splitting the RAW text and writing `block + rest`
      deletes the frontmatter. The prefix is carved off first and put back verbatim.
    - `backup` writes a `.brain-bak` copy of the original before anything is rewritten. The
      brain block can hold hand-written notes we cannot distinguish from boilerplate.
    - `replace_existing` says whether the current head IS a brain block to replace (True) or
      content to keep BELOW the new block (False — the v1 "no recognizable brain line" rule).
    - `make_block(head)` builds the replacement from the old head (the display name lives there).
      Returning "" strips the block; if nothing but whitespace is left, the file is removed.
    """
    text = vault.read(claude_md)
    fm_prefix = text[:project.body_start(text)]
    body = text[len(fm_prefix):]
    head, rest = project.split_brain_block(body) if replace_existing else ("", body)
    bak = None
    if backup and os.path.exists(claude_md):
        bak = _backup_path(claude_md)
        vault.write(bak, text)
    new_text = fm_prefix + make_block(head) + rest
    if new_text.strip():
        vault.write(claude_md, new_text)
    elif os.path.exists(claude_md):
        os.remove(claude_md)
    return head, rest, bak

def migrate_project(proj, vault_root, project_dir):
    actions = []
    if proj.legacy:
        text = vault.read(proj.claude_md)
        _, rest, bak = rewrite_block(
            proj.claude_md, lambda head: slim_block(_display_name(head, proj.slug), proj.slug))
        note = ""
        if not rest and not _has_separator(text):
            # No `---` separator: split_brain_block treated the whole file as the brain block,
            # so anything below it would otherwise be silently dropped.
            note = " — review it for your own notes"
        actions.append("claude-md (original backed up to %s%s)" % (os.path.basename(bak), note))
    n = strip_legacy_hooks(os.path.join(project_dir, ".claude", "settings.json"))
    if n:
        actions.append("hooks:%d" % n)
    if _stale_path(proj, vault_root):
        cpath = os.path.join(project.vault_project_dir(vault_root, proj.slug), "context.md")
        vault.write(cpath, vault.set_frontmatter(vault.read(cpath), "path", project_dir))
        actions.append("path")
    try:
        from brain import codemap            # Plan 2
        pdir = project.vault_project_dir(vault_root, proj.slug)
        files = codemap.list_files(project_dir)
        # Same size guard as the SessionStart path: a huge repo gets the scaffold now and the
        # generated block later, never a multi-second build inside the migration.
        made = (codemap.ensure_stub(project_dir, pdir) if len(files) >= codemap.LARGE_REPO_FILES
                else codemap.ensure(project_dir, pdir, files=files))
        if made:
            actions.append("codemap")
    except ImportError:
        pass
    return actions
