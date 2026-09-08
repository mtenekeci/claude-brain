"""Pure text helpers for vault markdown. Keep them regex-simple and format-preserving."""
import os, re
from collections import OrderedDict

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)

def parse_frontmatter(text):
    """{key: value} for the leading YAML block. Values stay raw strings — the only structure
    understood is YAML's block-list form, which Obsidian writes for `aliases:`:

        aliases:
          - Postgres
          - pg

    Those indented `- item` continuation lines are folded into the flow form `[Postgres, pg]`
    so downstream `graph.parse_aliases` sees one shape regardless of how the note was authored.
    """
    m = _FM_RE.match(text)
    fm = OrderedDict()
    if not m:
        return fm, text
    key = None
    block = []
    def flush():
        if key is not None and block:
            fm[key] = "[%s]" % ", ".join(block)
    for line in m.group(1).splitlines():
        item = line.strip()
        if key is not None and line[:1] in (" ", "\t") and item.startswith("- "):
            block.append(item[2:].strip().strip('"\''))
            continue
        flush()
        key, block = None, []
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip().strip('"')
            fm[k] = v
            if not v:
                key = k        # a bare `key:` may be followed by an indented block list
    flush()
    return fm, text[m.end():]

def set_frontmatter(text, key, value):
    m = _FM_RE.match(text)
    if not m:
        return "---\n%s: %s\n---\n" % (key, value) + text
    block = m.group(1)
    line_re = re.compile(r"^%s:.*$" % re.escape(key), re.M)
    if line_re.search(block):
        block = line_re.sub("%s: %s" % (key, value), block, count=1)
    else:
        block = block + "\n%s: %s" % (key, value)
    return "---\n%s\n---\n" % block + text[m.end():]

_FENCE_MARKS = ("```", "~~~")

def _heading_starts(text):
    """Return character offsets of lines starting with '## ' outside code fences.

    Both CommonMark fence markers count: a log entry pasted inside a `~~~` block used to open
    a section the caller never wrote, silently swallowing everything after it.
    """
    offsets = []
    in_fence = False
    char_pos = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(_FENCE_MARKS):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            offsets.append(char_pos)
        char_pos += len(line)
    return offsets

def _section_span(text, heading):
    # O(lines + headings): the offsets are re-walked once to find the matching heading LINE
    # (offsets alone cannot tell `## Decisions` from `## Decisions (old)`). Vault files are
    # capped at ~150 lines, so the second walk is not worth indexing away.
    offsets = _heading_starts(text)
    target_heading = "## %s" % heading
    start_idx = None
    char_pos = 0

    # Find the heading line that matches exactly
    for line in text.splitlines(keepends=True):
        if char_pos in offsets:
            # This is a real heading line; check if it matches exactly
            if line.rstrip("\r\n").rstrip() == target_heading:
                start_idx = offsets.index(char_pos)
                start_pos = char_pos + len(line)
                break
        char_pos += len(line)

    if start_idx is None:
        return None

    # End at next heading or EOF
    end = offsets[start_idx + 1] if start_idx + 1 < len(offsets) else len(text)

    return start_pos, end

def get_section(text, heading):
    span = _section_span(text, heading)
    return text[span[0]:span[1]].strip("\n") if span else ""

def replace_section(text, heading, body):
    span = _section_span(text, heading)
    if not span:
        return text.rstrip("\n") + "\n\n## %s\n%s\n" % (heading, body.strip("\n"))
    return text[:span[0]] + body.strip("\n") + "\n\n" + text[span[1]:]

def bullets(section_body):
    return [l[2:].strip() for l in section_body.splitlines() if l.startswith("- ")]

def count_log_entries(text):
    return len(_heading_starts(text))

def last_log_entry(text):
    offsets = _heading_starts(text)
    return text[offsets[-1]:].rstrip("\n") if offsets else ""

def last_entry_is_placeholder(text):
    head = last_log_entry(text).split("\n", 1)[0]
    return "(pre-compact)" in head or "(auto-close)" in head

def format_log_entry(date, n, completed, changed, decided, nxt, tag=""):
    suffix = " (%s)" % tag if tag else ""
    return "\n## %s · Session %d%s\nCompleted: %s\nChanged: %s\nDecided: %s\nNext: %s\n" % (
        date, n, suffix, completed, changed, decided, nxt)

def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, ValueError):
        return ""

def _discard(tmp):
    """Best-effort removal of a scratch file. Never raises: it runs in a `finally`, where a
    second exception would mask the write failure the caller actually needs to see."""
    try:
        os.remove(tmp)
    except OSError:
        pass

def write(path, text):
    """Atomic tmp+replace. Hooks rewrite context.md from inside a session that Claude Code can
    kill at any moment; a truncated context.md is worse than a stale one."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        _discard(tmp)           # replace failed — never leave a stray .tmp in the vault

def append(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
