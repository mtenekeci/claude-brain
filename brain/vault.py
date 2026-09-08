"""Pure text helpers for vault markdown. Keep them regex-simple and format-preserving."""
import os, re, stat, tempfile
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

    Known ambiguity: the fold joins on ", " and `parse_aliases` splits on ",", so a block item
    that itself contains a comma round-trips as two aliases — `- Postgres, the DB` becomes
    `Postgres` and `the DB`. Accepted rather than escaped: an alias is a lookup key, so the
    worst case is one extra harmless key, and quoting rules that survive both directions would
    cost more than the ambiguity does. Do not reuse this fold for a field where an item's exact
    text matters.
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

# The two budgets a vault note injected at SessionStart has to respect.
#
# CONTEXT_LINE_CAP is the documented, advisory one — `/brain sync` reports it and asks the
# model to compress. INJECT_BYTE_CAP is the hard one, and it exists because lines are a
# terrible proxy for size: a real project's context.md measured 81 KB in 128 lines (very long
# lines), passed the line cap, and its 86 KB injection buried the migration, graph and health
# lines that follow it. Bytes are what actually costs context, so bytes are what is enforced.
CONTEXT_LINE_CAP = 150
INJECT_BYTE_CAP = 16 * 1024

def size_kb(text):
    """Whole KB of UTF-8 `text` — the unit both the truncation marker and `/brain status` use."""
    return len((text or "").encode("utf-8")) // 1024

def for_injection(text, cap=INJECT_BYTE_CAP):
    """(text_to_inject, over_kb). `over_kb` is 0 when the note fits and its whole size in KB
    when it does not, so the caller can both mark the cut and name the file to trim.

    The cut lands on the last `## ` section boundary that fits — a half-section reads as a
    complete one — falling back to the last whole line when there is no heading to cut at.
    """
    data = (text or "").encode("utf-8")
    if len(data) <= cap:
        return text, 0
    head = data[:cap].decode("utf-8", "ignore")
    idx = head.rfind("\n## ")
    if idx <= 0:
        idx = head.rfind("\n")
    return (head[:idx + 1] if idx > 0 else head), len(data) // 1024

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
    """Best-effort removal of a scratch file. Never raises: it runs on a failure path, where a
    second exception would mask the write failure the caller actually needs to see."""
    try:
        os.remove(tmp)
    except OSError:
        pass

NEW_FILE_MODE = 0o644

def atomic_write(path, text):
    """Write `text` to `path` via a temp file in the same directory, then `os.replace`.

    Hooks rewrite context.md from inside a session Claude Code can kill at any moment, so a
    reader must never see a half-written note: `os.replace` is atomic within a filesystem, and
    the temp file is created in the target's own directory to guarantee that.

    The temp name comes from `tempfile.mkstemp`, NOT `path + ".tmp"`. Two brain processes can
    write the same file concurrently — two sessions in one project, or `graph lint
    --all-projects` touching a shared concept note — and a shared temp name lets one process
    unlink the other's in-flight file or publish a half-written one. The name is removed only
    on the failure path; a successful replace has already consumed it.

    This is the ONLY temp-file dance in the package: config, session state, the graph cache,
    the dismissed-candidate list, the code layer and every vault note all land through here, so
    the naming and cleanup rules live in exactly one place. Callers that write JSON serialise it
    themselves and hand over text — that keeps each site's own `json.dumps` options (indent,
    ensure_ascii, trailing newline) instead of pushing them all through one signature.

    What "atomic" does NOT buy you: `os.replace` puts a *fresh regular file* at `path`, so
    ownership, extended attributes and hard links to the old inode are not carried over, and a
    symlink at `path` is replaced rather than written through. Permission bits ARE carried over
    when the file already exists (mkstemp would otherwise tighten every note to 0600); a new
    file gets NEW_FILE_MODE. Do not reuse this for a path someone deliberately symlinked or
    hard-linked.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        try:
            f = os.fdopen(fd, "w", encoding="utf-8")        # from here the file object owns fd
        except BaseException:
            os.close(fd)                                    # …but only if fdopen itself succeeded
            raise
        with f:
            f.write(text)
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)      # rewrite: keep the note's own bits
        except OSError:
            mode = NEW_FILE_MODE                            # brand-new file
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        _discard(tmp)
        raise

def write(path, text):
    """The vault-facing name for `atomic_write` — every call site that writes a note uses it."""
    return atomic_write(path, text)

def append(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
