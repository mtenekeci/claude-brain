"""Subagent briefing text — delivered via SubagentStart additionalContext (Task 10)."""
from brain import vault

MARK = "Brain briefing:"

def text(ctx):
    rules = vault.bullets(vault.get_section(vault.read(ctx.context_path), "Hard Rules"))
    rules = [r for r in rules if r and not r.lower().startswith("none")][:8]
    lines = ["%s this project is \"%s\". Vault: %s/ (context.md, architecture.md, codemap.md)." % (MARK, ctx.project.slug, ctx.pdir)]
    if rules:
        lines.append("Hard Rules:")
        lines += ["- " + r for r in rules]
    # `hooks` is imported here, not at module scope, to avoid a cycle: hooks needs `briefing`
    # only from Task 10's SubagentStart handler.
    from brain import hooks
    lines.append("Before searching the codebase run: %s graph find <term>  (then `graph near <id>`)." % hooks.cli_command())
    lines.append("Do not write to the vault. Report new patterns, conventions, or decisions in your final message under a \"Vault notes:\" heading.")
    return "\n".join(lines[:14])
