"""One-shot, idempotent upgrade of a v1 project to the v2 layout (spec §12)."""
import json, os
from brain import project, vault

_LEGACY_MARKERS = ("/brain-session-start.sh", "/brain-post-tool-use.sh", "/brain-precompact.sh", "/brain-session-end.sh")

def slim_block(project_name, slug):
    return ("# Brain: %s\n\nbrain: %s\n\nVault context, protocol, and code map for this project are injected "
            "automatically by the claude-brain plugin at session start. If this session shows no \"Brain:\" block, "
            "run `/brain status`.\n---\n" % (project_name, slug))

def _display_name(head, slug):
    for line in head.splitlines():
        if line.startswith("# Brain:"):
            return line[len("# Brain:"):].strip() or slug
    return slug

def strip_legacy_hooks(settings_path):
    try:
        with open(settings_path) as f:
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
        for g in groups:
            if not isinstance(g, dict) or not isinstance(g.get("hooks"), list):
                kept_groups.append(g)                  # preserve irregular entries verbatim
                continue
            keep = [h for h in g["hooks"] if not (isinstance(h, dict) and any(m in str(h.get("command", "")) for m in _LEGACY_MARKERS))]
            removed += len(g["hooks"]) - len(keep)
            g["hooks"] = keep
            if keep:
                kept_groups.append(g)
        hooks[event] = kept_groups
        if not hooks[event]:
            del hooks[event]
    if removed:
        if not hooks:
            del data["hooks"]
        with open(settings_path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    return removed

def _settings_has_legacy(settings_path):
    try:
        with open(settings_path) as f:
            return any(m in f.read() for m in _LEGACY_MARKERS)
    except OSError:
        return False

def _stale_path(proj, vault_root):
    fm, _ = vault.parse_frontmatter(vault.read(os.path.join(project.vault_project_dir(vault_root, proj.slug), "context.md")))
    p = fm.get("path", "")
    return bool(p) and p != "—" and not os.path.isdir(p) and os.path.isdir(proj.project_dir)

def needs_migration(proj, vault_root):
    return proj.legacy or _settings_has_legacy(os.path.join(proj.project_dir, ".claude", "settings.json")) or _stale_path(proj, vault_root)

def migrate_project(proj, vault_root, project_dir):
    actions = []
    if proj.legacy:
        text = vault.read(proj.claude_md)
        head, rest = project.split_brain_block(text)
        vault.write(proj.claude_md, slim_block(_display_name(head, proj.slug), proj.slug) + rest)
        actions.append("claude-md")
    n = strip_legacy_hooks(os.path.join(project_dir, ".claude", "settings.json"))
    if n:
        actions.append("hooks:%d" % n)
    if _stale_path(proj, vault_root):
        cpath = os.path.join(project.vault_project_dir(vault_root, proj.slug), "context.md")
        vault.write(cpath, vault.set_frontmatter(vault.read(cpath), "path", project_dir))
        actions.append("path")
    try:
        from brain import codemap            # Plan 2
        if codemap.ensure(project_dir, project.vault_project_dir(vault_root, proj.slug)):
            actions.append("codemap")
    except ImportError:
        pass
    return actions
