"""Docs test for the thin /brain skill: SKILL.md router + commands/*.md.

Enforces the size caps, that the router only names files that exist, that every
`{BRAIN} <sub>` invocation mentioned under skills/ is a subcommand the CLI actually
accepts, that templates/protocol.md's rule lines appear verbatim in SKILL.md (so the
two never drift), and that no absolute /Users/ path leaks into shipped docs.
"""
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(ROOT, "skills", "brain")
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")
COMMANDS_DIR = os.path.join(SKILL_DIR, "commands")
PROTOCOL_MD = os.path.join(ROOT, "templates", "protocol.md")

SKILL_MAX_LINES = 150
COMMAND_MAX_LINES = 120

COMMAND_FILES = ["init", "load", "sync", "status", "map", "graph", "config", "remove"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _subparser_choices():
    """Every subcommand string the CLI parser accepts, recursively (graph/config nested)."""
    from brain import cli
    parser = cli.build_parser()
    out = set()

    def walk(p):
        for action in p._subparsers._group_actions if p._subparsers else []:
            for name, sub in action.choices.items():
                out.add(name)
                walk(sub)

    walk(parser)
    return out


class SkillDocsTests(unittest.TestCase):
    def test_skill_md_line_cap(self):
        n = len(_read(SKILL_MD).splitlines())
        self.assertLessEqual(n, SKILL_MAX_LINES, "SKILL.md is %d lines (cap %d)" % (n, SKILL_MAX_LINES))

    def test_command_files_exist_and_under_cap(self):
        for name in COMMAND_FILES:
            path = os.path.join(COMMANDS_DIR, "%s.md" % name)
            self.assertTrue(os.path.exists(path), "missing commands/%s.md" % name)
            n = len(_read(path).splitlines())
            self.assertLessEqual(n, COMMAND_MAX_LINES, "commands/%s.md is %d lines (cap %d)" % (name, n, COMMAND_MAX_LINES))

    def test_router_targets_all_exist(self):
        text = _read(SKILL_MD)
        for m in re.finditer(r"commands/([a-zA-Z0-9_-]+)\.md", text):
            path = os.path.join(COMMANDS_DIR, "%s.md" % m.group(1))
            self.assertTrue(os.path.exists(path), "SKILL.md references missing commands/%s.md" % m.group(1))

    def test_every_brain_invocation_is_a_real_subcommand(self):
        choices = _subparser_choices()
        skill_texts = {SKILL_MD: _read(SKILL_MD)}
        for name in COMMAND_FILES:
            p = os.path.join(COMMANDS_DIR, "%s.md" % name)
            if os.path.exists(p):
                skill_texts[p] = _read(p)
        pattern = re.compile(r"\{BRAIN\}\s+([a-zA-Z][a-zA-Z0-9_-]*)")
        for path, text in skill_texts.items():
            for m in pattern.finditer(text):
                sub = m.group(1)
                if sub == "ask":
                    continue  # Task 5 adds `graph ask` in a parallel worktree; allowed even if absent here
                self.assertIn(sub, choices, "%s invokes `{BRAIN} %s` which is not a CLI subcommand" % (path, sub))

    def test_protocol_rule_lines_appear_verbatim_in_skill_md(self):
        skill_text = _read(SKILL_MD)
        protocol_lines = _read(PROTOCOL_MD).splitlines()
        for line in protocol_lines[1:]:
            if not line.strip():
                continue
            self.assertIn(line.strip(), skill_text, "protocol.md line missing from SKILL.md: %r" % line)

    def test_no_absolute_user_paths(self):
        for base in (SKILL_DIR, os.path.join(ROOT, "templates")):
            for dirpath, _, files in os.walk(base):
                for f in files:
                    path = os.path.join(dirpath, f)
                    text = _read(path)
                    self.assertNotIn("/Users/", text, "%s contains an absolute /Users/ path" % path)


if __name__ == "__main__":
    unittest.main()
