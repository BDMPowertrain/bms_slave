#!/usr/bin/env python3
"""
BDM board configuration tool.

Run with no arguments for an interactive menu (same script on every OS):

    py configure.py           Windows (or double-click configure.py)
    ./configure.py            Linux/macOS (or: python3 configure.py)

This is the only supported way to change board metadata, rename a freshly
templated project, or change a board's stage (KiBot variant). It owns the
metadata in kibot_yaml/kibot_main.yaml, the `kibot_variant:` and
`release_version:` lines in .github/workflows/ci.yaml, and COMPANY/REVISION in
the .kicad_pro text variables. Don't hand-edit those. It also edits the
fabrication/assembly notes templates in kibot_resources/templates/ (menu, and
as part of releasing).

Python 3 standard library only; no network access, no pip install.

Non-interactive use (for scripts/CI):
    configure.py --stage CHECKED     set the stage directly
    configure.py --stage RELEASED --version 1.0.0
                                     release 1.0.0 on the next push
    configure.py --check             validate config, exit 1 on problems
    configure.py --dry-run           show what any action would change
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
KIBOT_MAIN = PROJECT_DIR / "kibot_yaml" / "kibot_main.yaml"
CI_YAML = PROJECT_DIR / ".github" / "workflows" / "ci.yaml"
CHANGELOG = PROJECT_DIR / "CHANGELOG.md"

PLACEHOLDER_STEM = "BOARD_TEMPLATE"
# Lowercase letters, digits, underscores. No car/year prefix, so the same
# naming carries forward to future cars without renames.
BOARD_NAME_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
# Must match what ci.yaml accepts for release_version.
RELEASE_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

STAGES = [
    ("DRAFT", "Schematic still being drawn.",
     "Generates schematic PDF, netlist and BoM. ERC/DRC not run."),
    ("PRELIMINARY", "Schematic close to final, layout in progress.",
     "Generates all schematic and PCB documents. ERC/DRC not run."),
    ("CHECKED", "Board believed correct; ready for procurement/fab.",
     "Generates all documents and ENFORCES ERC/DRC - CI fails on errors."),
    ("RELEASED", "Board is done; publish a numbered release.",
     "Same as CHECKED, then CI tags the version, updates main and creates the GitHub Release."),
]
STAGE_NAMES = [s[0] for s in STAGES]

# Free-text definitions in kibot_main.yaml. KiBot substitutes @KEY@ as raw
# text *before* parsing YAML, so wherever these land they must be inside
# double quotes, and the value itself must never contain `"` or `\`.
FREE_TEXT_KEYS = ("PROJECT_NAME", "DESCRIPTION", "COMPANY", "DESIGNER")


class ConfigError(Exception):
    pass


_EOL = {}  # Path -> original line ending, restored on write


def read(path):
    """Read with line endings normalized to \\n (so regexes behave the same
    on CRLF and LF files); Plan.apply() restores each file's original style."""
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    _EOL.setdefault(path, "\r\n" if "\r\n" in text else "\n")
    return text.replace("\r\n", "\n")


def _input(prompt_text):
    try:
        return input(prompt_text)
    except EOFError:
        raise SystemExit("\nInput closed - nothing changed.")


# ----------------------------------------------------------------------------
# Console helpers
# ----------------------------------------------------------------------------

def ask(label, default="", validate=None):
    """Prompt until `validate(value)` returns None (ok) or an error string."""
    suffix = f" [{default}]" if default else ""
    while True:
        raw = _input(f"  {label}{suffix}: ").strip()
        value = raw or default
        error = validate(value) if validate else None
        if not error:
            return value
        print(f"    ! {error}")


def ask_yes_no(label, default=False):
    hint = "Y/n" if default else "y/N"
    while True:
        raw = _input(f"  {label} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("    ! Answer y or n.")


def heading(text):
    print(f"\n{text}\n{'-' * len(text)}")


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------

def validate_free_text(value, required=False):
    if required and not value:
        return "This can't be empty."
    if '"' in value or "\\" in value:
        return 'Straight double quotes (") and backslashes (\\) aren\'t allowed - they break KiBot\'s config.'
    if "@" in value:
        return "'@' isn't allowed - KiBot uses it for variable substitution."
    if any(ord(c) < 32 for c in value):
        return "Control characters aren't allowed."
    if len(value) > 300:
        return f"Keep it under 300 characters (currently {len(value)})."
    return None


# Title block fit. Templates/*.kicad_wks draw these fields in Times New
# Roman inside fixed boxes, and KiCad doesn't shrink or wrap them, so a long
# value just runs out of its box. Advance widths per 1000 em for ASCII
# 32..126, read from kibot_resources/fonts/Times New Roman.ttf.
TIMES_WIDTHS = [
    250, 333, 408, 500, 500, 833, 778, 180, 333, 333, 500, 564, 250, 333, 250, 278,
    500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 278, 278, 564, 564, 564, 444,
    921, 722, 667, 667, 722, 611, 556, 722, 722, 333, 389, 722, 611, 889, 722, 722,
    556, 722, 667, 556, 611, 722, 722, 944, 722, 722, 611, 333, 278, 333, 469, 500,
    333, 444, 500, 444, 500, 444, 333, 500, 500, 278, 278, 500, 278, 778, 500, 500,
    500, 500, 333, 389, 278, 500, 500, 722, 500, 500, 444, 480, 200, 480, 541]
OUTLINE_FONT_EM = 1.4  # KiCad draws an outline font's em at 1.4x the text size
TYPICAL_EM_PER_CHAR = 0.44  # mixed-case names in Times New Roman
# key: (field label, text size in mm, usable box width in mm), from the
# .kicad_wks text position to the far edge of its box less a 0.5 mm margin.
TITLE_BLOCK_FIELDS = {
    "DESIGNER": ("Designer", 1.5, 25.0),
    "PROJECT_NAME": ("Project Name", 2.5, 39.0),
}


def title_block_width(text, size):
    em = sum(TIMES_WIDTHS[ord(c) - 32] if 32 <= ord(c) <= 126 else 1000 for c in text) / 1000
    return em * size * OUTLINE_FONT_EM


def title_block_max_chars(key):
    _, size, room = TITLE_BLOCK_FIELDS[key]
    return int(room / (size * OUTLINE_FONT_EM * TYPICAL_EM_PER_CHAR))


def validate_title_block(key, value):
    """Measured rather than a flat character count: 'Jim Li' and 'WILLIAM M'
    differ a lot in width. The message still talks in characters."""
    label, size, room = TITLE_BLOCK_FIELDS[key]
    if title_block_width(value, size) <= room:
        return None
    fits = value
    while fits and title_block_width(fits, size) > room:
        fits = fits[:-1]
    return (f"Too long for the title block's {label} box (about {title_block_max_chars(key)} characters fit, "
            f"fewer in capitals). It would be cut off after \"{fits.rstrip()}\". Shorten it"
            + (" - e.g. surnames or initials for several people." if key == "DESIGNER" else "."))


def validate_board_name(value):
    if not BOARD_NAME_RE.match(value):
        return ("Lowercase letters, digits and single underscores only "
                "(e.g. tim, bse_apps) - no spaces, hyphens or car/year prefix.")
    return None


def validate_release_version(value):
    if not RELEASE_VERSION_RE.match(value):
        return "Use three numbers, like 1.0.0 (no leading 'v')."
    existing = git_version_tags()
    if value in existing:
        return f"{value} is already released. Pick a higher version."
    if existing and version_key(value) <= version_key(existing[0]):
        return f"Must be higher than the last release, {existing[0]}."
    return None


def validate_revision(value):
    if not re.match(r"^[0-9A-Za-z][0-9A-Za-z.\-+]*$", value):
        return "Use something like 0.1.0 or A (letters, digits, '.', '-', '+')."
    return None


# ----------------------------------------------------------------------------
# kibot_main.yaml: reading, writing, linting
# ----------------------------------------------------------------------------

DOC_SEPARATOR = re.compile(r"^\.\.\.\s*$", re.MULTILINE)


def split_definitions(text):
    """Return (imports_part, definitions_part). The real values live in the
    global `definitions:` block after the '...' separator; the import blocks
    above contain KEY: "@KEY@" passthroughs with the same key names, so
    anything keyed by name must be scoped to the definitions part."""
    m = DOC_SEPARATOR.search(text)
    if not m:
        raise ConfigError("kibot_main.yaml has no '...' separator before its definitions block.")
    return text[:m.end()], text[m.end():]


def unquote_yaml_scalar(raw):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return re.sub(r'\\(.)', r"\1", raw[1:-1])
    return re.sub(r"\s+#.*$", "", raw)  # plain scalar: drop trailing comment


def quote_yaml_scalar(value):
    """Always double-quote. Validation already forbids `"` and `\\`, but
    escape anyway so this can never produce invalid YAML on its own."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_definitions(text):
    _, defs = split_definitions(text)
    values = {}
    for m in re.finditer(r"^  ([A-Z0-9_]+):[ \t]*(.*)$", defs, re.MULTILINE):
        values[m.group(1)] = unquote_yaml_scalar(m.group(2))
    return values


def set_definition(text, key, value):
    head, defs = split_definitions(text)
    pattern = re.compile(rf"^(  {re.escape(key)}:)[ \t]*.*$", re.MULTILINE)
    if not pattern.search(defs):
        raise ConfigError(f"'{key}:' not found in kibot_main.yaml's definitions block.")
    new_line = f"  {key}: {quote_yaml_scalar(value)}"
    return head + pattern.sub(lambda _: new_line, defs, count=1)


def quote_passthroughs(text):
    """Make every free-text `@KEY@` substitution in the import blocks sit
    inside double quotes. Unquoted, a value containing ': ' (e.g. a
    description) breaks YAML parsing for every KiBot run."""
    head, defs = split_definitions(text)
    for key in FREE_TEXT_KEYS:
        head = re.sub(rf'^(\s*[A-Za-z_]+:[ \t]*)@{key}@[ \t]*$',
                      rf'\g<1>"@{key}@"', head, flags=re.MULTILINE)
    return head + defs


YAML_INDICATORS = set("'\"&*!|>%@`[]{},#?-")


def lint(text):
    """Simulate KiBot's raw @VAR@ substitution over the import blocks and
    report any line that would no longer be valid YAML. Not a full YAML
    parser - it checks the specific failure modes free text can cause."""
    problems = []
    head, _ = split_definitions(text)
    values = read_definitions(text)
    sources = [("kibot_main.yaml", head)]
    sources += [(p.name, read(p)) for p in sorted(KIBOT_MAIN.parent.glob("*.yaml")) if p != KIBOT_MAIN]
    for name, body in sources:
        problems += lint_lines(name, body, values)
    for key in FREE_TEXT_KEYS:
        if key in values and validate_free_text(values[key]):
            problems.append(f"definitions: {key} - {validate_free_text(values[key])}")
    return problems


def lint_lines(name, body, values):
    problems = []
    for lineno, line in enumerate(body.splitlines(), start=1):
        if line.lstrip().startswith("#") or "@" not in line:
            continue
        tokens = re.findall(r"@([A-Z0-9_]+)@", line)
        if not any(t in FREE_TEXT_KEYS for t in tokens):
            continue
        m = re.match(r"^(\s*-?\s*[A-Za-z_]+:)[ \t]*(.*)$", line)
        if not m:
            continue
        raw_value = re.sub(r"\s+#.*$", "", m.group(2)).strip()
        expanded = re.sub(r"@([A-Z0-9_]+)@", lambda t: values.get(t.group(1), t.group(0)), raw_value)
        where = f"{name} line {lineno}"
        if raw_value.startswith('"') and raw_value.endswith('"'):
            inner = expanded[1:-1]
            if '"' in inner or "\\" in inner:
                problems.append(f"{where}: value contains \" or \\ inside double quotes.")
        elif raw_value.startswith("'") and raw_value.endswith("'"):
            if "'" in expanded[1:-1]:
                problems.append(f"{where}: value contains ' inside single quotes - use double quotes.")
        else:
            broken = ": " in expanded or " #" in expanded or (expanded and expanded[0] in YAML_INDICATORS)
            problems.append(f"{where}: `{m.group(1).strip()} {raw_value}` is unquoted - "
                            + ("its current value already breaks YAML parsing." if broken
                               else "it will break KiBot as soon as the value contains ': ' or ' #'.")
                            + " Wrap it in double quotes.")
    return problems


# ----------------------------------------------------------------------------
# Other files
# ----------------------------------------------------------------------------

def find_project_stem():
    pros = list(PROJECT_DIR.glob("*.kicad_pro"))
    if len(pros) != 1:
        raise ConfigError(f"Expected exactly one .kicad_pro in {PROJECT_DIR}, found {len(pros)}.")
    return pros[0].stem


def read_stage():
    m = re.search(r"^\s*kibot_variant:\s*(\S+)", read(CI_YAML), re.MULTILINE)
    return m.group(1) if m else "DRAFT"


def read_release_version():
    m = re.search(r"^\s*release_version:\s*[\"']?([^\"'\s]*)", read(CI_YAML), re.MULTILINE)
    return m.group(1) if m else ""


def set_stage_lines(text, stage, version):
    """Set `kibot_variant:` and `release_version:` in ci.yaml, adding the
    latter right after the former if this repo's ci.yaml predates it."""
    text = re.sub(r"^(\s*kibot_variant:\s*)\S+", rf"\g<1>{stage}", text, count=1, flags=re.MULTILINE)
    line = f'release_version: "{version}"'
    if re.search(r"^\s*release_version:", text, re.MULTILINE):
        return re.sub(r"^(\s*)release_version:.*$", rf"\g<1>{line}", text, count=1, flags=re.MULTILINE)
    return re.sub(r"^(\s*)(kibot_variant:.*)$", rf"\g<1>\g<2>\n\g<1>{line}", text, count=1, flags=re.MULTILINE)


def version_key(v):
    return tuple(int(n) for n in v.split("."))


def git_version_tags():
    """Release tags known locally, highest first. Tags made elsewhere only
    show up after a `git pull`; CI re-checks against GitHub anyway."""
    try:
        out = subprocess.run(["git", "-C", str(PROJECT_DIR), "tag", "-l"],
                             capture_output=True, text=True, check=True).stdout
    except Exception:
        return []
    return sorted((t for t in out.split() if RELEASE_VERSION_RE.match(t)), key=version_key, reverse=True)


# ----------------------------------------------------------------------------
# CHANGELOG.md: the [Unreleased] section becomes the release notes
# ----------------------------------------------------------------------------

NOTE_CATEGORIES = ("Fixed", "Added", "Changed", "Removed")
# The template's example bullets, which mean "nothing written yet".
NOTE_PLACEHOLDERS = {"Fixes", "Additions", "Changes", "Deletions"}
UNRELEASED_RE = re.compile(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def read_release_notes(text):
    """{category: [bullet, ...]} from the [Unreleased] section, standard
    categories first. Placeholder bullets are dropped; a non-bullet line is
    kept as a continuation of the bullet above it."""
    notes = {c: [] for c in NOTE_CATEGORIES}
    m = UNRELEASED_RE.search(text)
    if not m:
        return notes
    category = "Changed"
    for line in m.group(1).split("\n"):
        if line.startswith("### "):
            category = line[4:].strip()
            notes.setdefault(category, [])
        elif re.match(r"^\s*[-*]\s+", line):
            bullet = re.sub(r"^\s*[-*]\s+", "", line).strip()
            if bullet not in NOTE_PLACEHOLDERS:
                notes[category].append(bullet)
        elif line.strip() and notes[category]:
            notes[category][-1] += "\n    " + line.strip()
    return notes


def write_release_notes(text, notes):
    body = "".join(f"### {c}\n\n" + "".join(f"-   {b}\n" for b in bullets) + "\n"
                   for c, bullets in notes.items() if bullets)
    section = "## [Unreleased]\n\n" + body
    if UNRELEASED_RE.search(text):
        return UNRELEASED_RE.sub(lambda _: section, text, count=1)
    m = re.search(r"^## ", text, re.MULTILINE)
    if m:
        return text[:m.start()] + section + text[m.start():]
    return (text.rstrip("\n") + "\n\n" if text.strip() else "# Changelog\n\n") + section


def print_release_notes(notes):
    if not any(notes.values()):
        print("    (empty)")
    for c, bullets in notes.items():
        if bullets:
            print(f"    {c}:")
            for b in bullets:
                print(f"      - {b}")


def edit_release_notes(plan):
    """Interactive editor for the [Unreleased] section; adds the edit to
    `plan`. Returns False if the user backs out of releasing empty notes."""
    text = plan.text_of(CHANGELOG) if CHANGELOG.exists() else ""
    notes = read_release_notes(text)
    heading("Release notes (CHANGELOG.md [Unreleased])")
    print_release_notes(notes)
    if ask_yes_no("Edit the release notes now?", default=not any(notes.values())):
        for category, bullets in notes.items():
            print(f"\n  {category}:")
            while True:
                for i, b in enumerate(bullets, start=1):
                    print(f"    {i}. {b}")
                hint = f", -1..-{len(bullets)} removes that line" if bullets else ""
                entry = ask(f"Add a line (Enter for next section{hint})", validate=lambda v: validate_note(v, bullets))
                if not entry:
                    break
                if re.match(r"^-\d+$", entry):
                    bullets.pop(int(entry[1:]) - 1)
                else:
                    bullets.append(entry)
        print("\n  Release notes will be:")
        print_release_notes(notes)
    if not any(notes.values()) and not ask_yes_no("The release notes are empty. Release anyway?", default=False):
        print("Cancelled - nothing written.")
        return False
    plan.write(CHANGELOG, write_release_notes(text, notes), "release notes")
    return True


def validate_note(value, bullets):
    if re.match(r"^-\d+$", value):
        n = int(value[1:])
        return None if 1 <= n <= len(bullets) else f"There's no line {n}."
    if value in NOTE_PLACEHOLDERS:
        return "Describe the actual change."
    return None


# ----------------------------------------------------------------------------
# Manufacturing notes: the KiBot report templates spliced into the
# fabrication and assembly drawings
# ----------------------------------------------------------------------------

NOTES_DIR = PROJECT_DIR / "kibot_resources" / "templates"
MANUFACTURING_NOTES = (("Fabrication notes", NOTES_DIR / "fabrication_notes.txt"),
                       ("Assembly notes", NOTES_DIR / "assembly_notes.txt"))
NOTE_START_RE = re.compile(r"^(\d+)\)")
NOTE_WRAP = 48  # matches the hand-wrapped width of the template notes


def parse_notes(text):
    """Split a notes template into its header and numbered notes. Each note
    keeps its raw lines (tabs, ${var} references, KiBot `#?condition` lines),
    so notes the user doesn't touch are written back byte-for-byte. The
    blank and `#?` lines just before a note's `N)` line are its `sep`, so a
    conditional note's condition moves or disappears with it."""
    trailing = text.endswith("\n")
    lines = (text[:-1] if trailing else text).split("\n")
    starts = [i for i, line in enumerate(lines) if NOTE_START_RE.match(line)]

    def sep_start(i):
        while i > 0 and (not lines[i - 1].strip() or lines[i - 1].startswith("#?")):
            i -= 1
        return i
    bounds = [sep_start(s) for s in starts]
    notes = []
    for k, s in enumerate(starts):
        end = bounds[k + 1] if k + 1 < len(starts) else len(lines)
        notes.append({"sep": lines[bounds[k]:s], "body": lines[s:end]})
    return {"header": lines[:bounds[0]] if starts else lines, "notes": notes, "trailing": trailing}


def render_notes(doc):
    """Back to template text, renumbering the notes 1, 2, 3..."""
    lines = list(doc["header"])
    for n, note in enumerate(doc["notes"], start=1):
        lines += note["sep"] + [NOTE_START_RE.sub(f"{n})", note["body"][0], count=1)] + note["body"][1:]
    text = "\n".join(lines)
    return text + "\n" if doc["trailing"] else text


def print_notes(doc):
    if not doc["notes"]:
        print("    (no notes)")
    for n, note in enumerate(doc["notes"], start=1):
        conditions = sorted({line[2:].strip() for line in note["sep"] + note["body"] if line.startswith("#?")})
        body = [line for line in note["body"] if not line.startswith("#?")]
        first = NOTE_START_RE.sub("", body[0]).strip()
        print(f"    {n:>2}) {first}" + (f"   [only if: {', '.join(conditions)}]" if conditions else ""))
        for line in body[1:]:
            print(("    " + line).expandtabs(8).rstrip())


def format_note(text):
    """A typed one-line note, wrapped and indented like the template's."""
    wrapped = textwrap.wrap(text, NOTE_WRAP, break_long_words=False, break_on_hyphens=False) or [""]
    return ["0)\t" + wrapped[0]] + ["\t" + w for w in wrapped[1:]]


def validate_note_text(value):
    if not value:
        return "This can't be empty."
    if value.startswith("#"):
        return "A note can't start with '#' - KiBot reads that as a template directive."
    if any(ord(c) < 32 for c in value):
        return "Control characters aren't allowed."
    return None


def edit_in_text_editor(text, filename):
    """Open `text` in the user's editor ($VISUAL/$EDITOR, else Notepad or
    nano/vi) and return the saved result, or None if no editor could run."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        editor = "notepad" if sys.platform == "win32" else (shutil.which("nano") or shutil.which("vi") or "vi")
    command = [t.strip('"') for t in shlex.split(editor, posix=os.name != "nt")]
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir) / filename
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"  Opening {filename} in {command[0]}.")
        try:
            subprocess.run(command + [str(tmp)], check=False)
        except OSError as e:
            print(f"    ! Couldn't start '{editor}' ({e}). Set the EDITOR environment variable to your editor.")
            return None
        # Some editors (Windows 11's Notepad, `code` without --wait) return
        # immediately, so don't read the file until the user says they're done.
        _input("  Save the file, close the editor, then press Enter here...")
        with open(tmp, encoding="utf-8", newline="") as f:
            edited = f.read().lstrip("﻿").replace("\r\n", "\n")
        if not edited.strip():
            print("    ! The file came back empty - kept it as it was.")
            return None
        return edited


def edit_notes_file(plan, label, path):
    """Interactive editor for one notes template; adds the edit to `plan`."""
    doc = parse_notes(plan.text_of(path))
    print("  Drawing notes are usually written in CAPITALS. Text like ${pcb_finish_cap}\n"
          "  is filled in by KiBot from the board.")
    while True:
        count = len(doc["notes"])

        def validate(v):
            m = re.match(r"^([rd])\s*(\d+)$", v.lower())
            if v.lower() in ("", "a", "o", "s"):
                return None
            if m:
                return None if 1 <= int(m.group(2)) <= count else f"There's no note {m.group(2)}."
            return "Enter a, r N, d N, o, s or just Enter."
        cmd = ask("a = add, r N = reword N, d N = delete N, o = open in text editor, "
                  "s = show, Enter = done", validate=validate).lower()
        if not cmd:
            break
        if cmd == "s":
            print_notes(doc)
        elif cmd == "a":
            text = ask("New note (one line; it's wrapped for you)", validate=validate_note_text)
            doc["notes"].append({"sep": [""], "body": format_note(text)})
            print_notes(doc)
        elif cmd == "o":
            edited = edit_in_text_editor(render_notes(doc), path.name)
            if edited is not None:
                doc = parse_notes(edited)
                print_notes(doc)
        else:
            n = int(cmd[1:].strip())
            note = doc["notes"][n - 1]
            if cmd[0] == "d":
                del doc["notes"][n - 1]
            else:
                if len(note["body"]) > 1:
                    print("    (This replaces the whole note, including any table or sub-items -\n"
                          "     use 'o' to change just part of it.)")
                text = ask(f"New text for note {n} (Enter to keep)", validate=lambda v: v and validate_note_text(v))
                if text:
                    note["body"] = format_note(text)
            print_notes(doc)
    plan.write(path, render_notes(doc), label.lower())


def review_manufacturing_notes(plan, ask_first):
    """Show each notes template and edit it. With `ask_first` (release),
    only edit the ones the user says are wrong."""
    for label, path in MANUFACTURING_NOTES:
        if not path.exists():
            continue
        heading(f"{label} ({path.relative_to(PROJECT_DIR).as_posix()})")
        print_notes(parse_notes(plan.text_of(path)))
        if ask_first and ask_yes_no(f"Are the {label.lower()} correct for this release?", default=True):
            continue
        edit_notes_file(plan, label, path)


# ----------------------------------------------------------------------------
# Impedance table (Tier 2): a hand-written CSV-style template, one row per
# controlled-impedance structure, spliced into the fabrication drawing
# ----------------------------------------------------------------------------

IMPEDANCE_TABLE = NOTES_DIR / "impedance_table.txt"


def impedance_enabled(kibot_text):
    head = split_definitions(kibot_text)[0]
    return bool(re.search(r"^\s*-\s*@CSV_IMPEDANCE_TABLE_OUTPUT@", head, re.MULTILINE))


# The fab drawing's include_table entry for the impedance table. It has to
# follow the switch above too: KiBot generates any output include_table
# names and fills the PCB's kibot_table_csv_impedance_table frame with it,
# whether or not the output is in a group.
PDF_FAB_YAML = KIBOT_MAIN.parent / "kibot_out_pdf_fabrication.yaml"
IMPEDANCE_INCLUDE_RE = re.compile(
    r"^[ \t]*# impedance-table-begin[^\n]*\n(?:[ \t]*#(?! -| {3})[^\n]*\n)*(.*?)^[ \t]*# impedance-table-end",
    re.MULTILINE | re.DOTALL)


def impedance_include_state(text):
    """True/False for the include entry being active/commented out, or None
    if this repo's kibot_out_pdf_fabrication.yaml has no marked entry."""
    m = IMPEDANCE_INCLUDE_RE.search(text)
    if not m:
        return None
    return any(line.strip() and not line.lstrip().startswith("#") for line in m.group(1).split("\n"))


def toggle_impedance_include(text, enabled):
    m = IMPEDANCE_INCLUDE_RE.search(text)
    if not m:
        return text
    out = []
    for line in m.group(1).split("\n"):
        indent = line[:len(line) - len(line.lstrip())]
        body = line[len(indent):]
        if body:
            body = (body[2:] if body.startswith("# ") else body) if enabled else \
                   (body if body.startswith("#") else "# " + body)
        out.append(indent + body)
    return text[:m.start(1)] + "\n".join(out) + text[m.end(1):]


def plan_impedance(plan, enabled):
    """Switch the impedance table on or off everywhere it's wired in."""
    plan.write(KIBOT_MAIN, toggle_impedance(plan.text_of(KIBOT_MAIN), enabled),
               f"impedance table output {'on' if enabled else 'off'}")
    if PDF_FAB_YAML.exists():
        plan.write(PDF_FAB_YAML, toggle_impedance_include(plan.text_of(PDF_FAB_YAML), enabled),
                   "fabrication drawing " + ("fills in" if enabled else "leaves blank") + " the impedance table")


def parse_table(text):
    """{header, rows, trailing}. Rows keep their raw text (the template pads
    columns with tabs) until edited; fields split on commas."""
    trailing = text.endswith("\n")
    lines = [line for line in (text[:-1] if trailing else text).split("\n")]
    rows = [{"raw": line, "fields": [f.strip() for f in line.split(",")]} for line in lines[1:] if line.strip()]
    return {"header": lines[0] if lines else "", "rows": rows, "trailing": trailing}


def table_columns(table):
    return [f.strip() for f in table["header"].split(",")]


def render_table(table):
    lines = [table["header"]] + [r["raw"] if r["raw"] is not None else ",\t".join(r["fields"])
                                 for r in table["rows"]]
    text = "\n".join(lines)
    return text + "\n" if table["trailing"] else text


def print_table(table):
    columns = table_columns(table)
    rows = [r["fields"] + [""] * (len(columns) - len(r["fields"])) for r in table["rows"]]
    widths = [max([len(c)] + [len(r[i]) for r in rows]) for i, c in enumerate(columns)]
    print("        " + "  ".join(c.ljust(w) for c, w in zip(columns, widths)).rstrip())
    if not rows:
        print("        (no rows)")
    for n, r in enumerate(rows, start=1):
        print(f"    {n:>2}) " + "  ".join(f.ljust(w) for f, w in zip(r, widths)).rstrip())


def validate_cell(value):
    if not value:
        return "This can't be empty."
    if "," in value:
        return "Commas aren't allowed - they separate the columns."
    if any(ord(c) < 32 for c in value):
        return "Control characters aren't allowed."
    return None


def ask_row(columns, current=None):
    return [ask(column, current[i] if current and i < len(current) else "", validate_cell)
            for i, column in enumerate(columns)]


def edit_impedance_table(plan):
    table = parse_table(plan.text_of(IMPEDANCE_TABLE))
    columns = table_columns(table)
    print("  One row per controlled-impedance structure. Get the values from the\n"
          "  impedance calculator / your fab's stackup, not from memory.")
    while True:
        count = len(table["rows"])

        def validate(v):
            m = re.match(r"^([ed])\s*(\d+)$", v.lower())
            if v.lower() in ("", "a", "o", "s"):
                return None
            if m:
                return None if 1 <= int(m.group(2)) <= count else f"There's no row {m.group(2)}."
            return "Enter a, e N, d N, o, s or just Enter."
        cmd = ask("a = add row, e N = edit row N, d N = delete row N, o = open in text editor, "
                  "s = show, Enter = done", validate=validate).lower()
        if not cmd:
            break
        if cmd == "a":
            table["rows"].append({"raw": None, "fields": ask_row(columns)})
        elif cmd == "o":
            edited = edit_in_text_editor(render_table(table), IMPEDANCE_TABLE.name)
            if edited is not None:
                table = parse_table(edited)
                columns = table_columns(table)
        elif cmd != "s":
            n = int(cmd[1:].strip())
            if cmd[0] == "d":
                del table["rows"][n - 1]
            else:
                row = table["rows"][n - 1]
                print("    (Enter keeps a value)")
                row["fields"] = ask_row(columns, row["fields"])
                row["raw"] = None
        print_table(table)
    plan.write(IMPEDANCE_TABLE, render_table(table), "impedance table")


def review_impedance_table(plan, ask_first):
    if not impedance_enabled(plan.text_of(KIBOT_MAIN)):
        if ask_first:
            print("\n  Impedance table: off for this board, skipped (turn it on in 'Edit board info').")
        return
    if not IMPEDANCE_TABLE.exists():
        return
    heading(f"Impedance table ({IMPEDANCE_TABLE.relative_to(PROJECT_DIR).as_posix()})")
    print_table(parse_table(plan.text_of(IMPEDANCE_TABLE)))
    if ask_first and ask_yes_no("Is the impedance table correct for this release?", default=True):
        return
    edit_impedance_table(plan)


# ----------------------------------------------------------------------------
# Stackup: KiBot's draw_fancy_stackup draws the board's own stackup (KiCad
# Board Setup) on the fabrication drawing, with STACKUP_TABLE_NOTE under it
# ----------------------------------------------------------------------------

def sexpr_block(text, start):
    """The balanced (...) starting at text[start], skipping quoted strings."""
    depth, i, in_str = 0, start, False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:]


def read_stackup(pcb_text):
    """([{layer, type, material, thickness, epsilon_r, color}], copper finish),
    or (None, None) if the board has no stackup defined."""
    m = re.search(r"\(stackup\b", pcb_text)
    if not m:
        return None, None
    block = sexpr_block(pcb_text, m.start())
    layers = []
    for lm in re.finditer(r'\(layer "([^"]*)"', block):
        body = sexpr_block(block, lm.start())

        def prop(name):
            p = re.search(rf'\({name} (?:"([^"]*)"|([^\s)]+))\)', body)
            return (p.group(1) if p.group(1) is not None else p.group(2)) if p else ""
        layers.append({"layer": lm.group(1), "type": prop("type"), "material": prop("material"),
                       "thickness": prop("thickness"), "epsilon_r": prop("epsilon_r"), "color": prop("color")})
    finish = re.search(r'\(copper_finish "([^"]*)"\)', block)
    return layers, finish.group(1) if finish else ""


def print_stackup(layers, finish):
    columns = [("Layer", "layer"), ("Type", "type"), ("Material", "material"),
               ("Thickness mm", "thickness"), ("Er", "epsilon_r"), ("Color", "color")]
    widths = [max([len(c)] + [len(layer[k]) for layer in layers]) for c, k in columns]
    print("    " + "  ".join(c.ljust(w) for (c, _), w in zip(columns, widths)).rstrip())
    for layer in layers:
        print("    " + "  ".join(layer[k].ljust(w) for (_, k), w in zip(columns, widths)).rstrip())
    total = 0.0
    for layer in layers:
        try:
            total += float(layer["thickness"] or 0)
        except ValueError:
            pass
    print(f"\n    Total thickness: {total:.3f} mm    Copper finish: {finish or '(not set)'}")


def validate_stackup_note(value):
    # Lands unquoted in kibot_main.yaml and inside '...' in
    # kibot_pre_draw_stackup.yaml, so ': ', ' #' and ' are out too.
    error = validate_free_text(value)
    if error:
        return error
    if "'" in value or ":" in value or "#" in value:
        return "Apostrophes, ':' and '#' aren't allowed here - they break KiBot's config."
    return None


def review_stackup(plan, releasing):
    """Show the stackup and its note. Returns False when the stackup itself
    is wrong during a release (it can only be fixed in KiCad), so the
    release is cancelled."""
    stem = find_project_stem()
    layers, finish = read_stackup(read(PROJECT_DIR / f"{stem}.kicad_pcb"))
    heading("Stackup (drawn on the fabrication drawing, from the .kicad_pcb)")
    if layers:
        print_stackup(layers, finish)
    else:
        print("    (no stackup defined - KiBot can't draw one)")
    note = read_definitions(plan.text_of(KIBOT_MAIN)).get("STACKUP_TABLE_NOTE", "")
    print(f"    Note under the table: {note or '(none)'}")
    if ask_yes_no("Is the stackup correct" + (" for this release?" if releasing else "?"), default=bool(layers)):
        return True
    if ask_yes_no("Is it only the note under the table that needs changing?", default=False):
        new_note = ask("Note under the stackup table", note, validate_stackup_note)
        plan.write(KIBOT_MAIN, set_definition(plan.text_of(KIBOT_MAIN), "STACKUP_TABLE_NOTE", new_note),
                   "stackup table note")
        return True
    print("\n  The stackup itself is set in KiCad: PCB Editor > File > Board Setup >\n"
          "  Board Stackup > Physical Stackup. Change it there, save, close KiCad,\n"
          "  commit, and " + ("run the release again." if releasing else "check it here again."))
    if releasing:
        print("Cancelled - nothing written.")
    return not releasing


def suggest_next_version(tags):
    if not tags:
        return "1.0.0"
    major, minor, _ = version_key(tags[0])
    return f"{major}.{minor + 1}.0"


def git_remote_url():
    try:
        url = subprocess.run(["git", "-C", str(PROJECT_DIR), "remote", "get-url", "origin"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ""
    url = re.sub(r"^git@github\.com:", "https://github.com/", url)
    return re.sub(r"\.git$", "", url)


def kicad_is_open(stem):
    return sorted(p.name for p in PROJECT_DIR.glob(f"~{stem}.*.lck"))


CONFLICT_MARKER_RE = re.compile(r"^(<<<<<<<|=======|>>>>>>>)(?: |$)", re.MULTILINE)


def project_file_problems():
    """Unresolved git merge conflicts in the KiCad files, and a .kicad_pro
    that isn't valid JSON. CI commits GIT_HASH_* into the .kicad_pro on every
    run, so pulling over local .kicad_pro edits can conflict; a conflicted
    file committed as-is breaks CI and, once opened, KiCad."""
    problems = []
    files = [p for pattern in ("*.kicad_pro", "*.kicad_sch", "*.kicad_pcb")
             for p in sorted(PROJECT_DIR.glob(pattern))]
    files += [PROJECT_DIR / "fp-lib-table", PROJECT_DIR / "sym-lib-table"]
    for path in files:
        if not path.is_file():
            continue
        text = read(path)
        m = CONFLICT_MARKER_RE.search(text)
        if m:
            line = text.count("\n", 0, m.start()) + 1
            problems.append(f"{path.name} line {line}: unresolved git merge conflict ({m.group(1)})")
        elif path.suffix == ".kicad_pro":
            try:
                json.loads(text)
            except ValueError as e:
                problems.append(f"{path.name}: not valid JSON ({e})")
    return problems


def load_project_json(path):
    """The .kicad_pro as a dict, or a ConfigError that says how to repair it
    (instead of a json traceback on a conflicted file)."""
    text = read(path)
    if CONFLICT_MARKER_RE.search(text):
        raise ConfigError(f"{path.name} has an unresolved git merge conflict. Choose 'Check config' from the "
                          "menu (or run configure.py --check --fix) to resolve it.")
    try:
        return json.loads(text)
    except ValueError as e:
        raise ConfigError(f"{path.name} is not valid JSON ({e}). Restore it from an earlier commit "
                          f"(git log -- \"{path.name}\", then git checkout <commit> -- \"{path.name}\").")


def project_json_text(data, like):
    """Serialize a .kicad_pro the way KiCad writes it (2-space indent, raw
    UTF-8 instead of \\u escapes), keeping `like`'s trailing newline or lack
    of one, so an edit doesn't reformat lines nobody changed."""
    return json.dumps(data, indent=2, ensure_ascii=False) + ("\n" if like.endswith("\n") else "")


# Text variables KiBot's set_text_variables preflight rewrites on every CI
# run (kibot_pre_set_text_variables.yaml). These are what make .kicad_pro
# pull conflicts common, and either side of a conflict on them is fine
# because the next CI run overwrites them anyway.
CI_TEXT_VARIABLE_RE = re.compile(
    r"^(REVISION|RELEASE_.*|GIT_HASH_.*|GIT_URL|BRANCH|PROJECT_NAME|BOARD_NAME|DESCRIPTION|"
    r"COMPANY|DESIGNER|BUILD_VARIANT|FABRICATION_NOTES|ASSEMBLY_NOTES|SHEET_NAME_.*)$")
_MISSING = object()


def merge_json(base, ours, theirs, where=""):
    """Three-way merge of parsed JSON. Returns (merged, conflicts) where
    conflicts are the /key/paths both sides changed differently (ours is
    kept there). Symmetric apart from that tie-break, so it doesn't matter
    whether the conflict came from a merge or a rebase."""
    if ours == theirs or theirs == base:
        return ours, []
    if ours == base:
        return theirs, []
    if isinstance(ours, dict) and isinstance(theirs, dict):
        base = base if isinstance(base, dict) else {}
        merged, conflicts = {}, []
        for key in list(ours) + [k for k in theirs if k not in ours]:
            value, c = merge_json(base.get(key, _MISSING), ours.get(key, _MISSING),
                                  theirs.get(key, _MISSING), f"{where}/{key}")
            if value is not _MISSING:
                merged[key] = value
            conflicts += c
        return merged, conflicts
    return ours, [where]


def git_unmerged_versions(path):
    """{1: base, 2: ours, 3: theirs} text of a file git has as unmerged
    (mid-merge or mid-rebase), else {}."""
    rel = path.relative_to(PROJECT_DIR).as_posix()
    try:
        out = subprocess.run(["git", "-C", str(PROJECT_DIR), "ls-files", "-u", "--", rel],
                             capture_output=True, text=True, check=True).stdout
        versions = {}
        for line in out.splitlines():
            _, sha, stage = line.split("\t", 1)[0].split()
            blob = subprocess.run(["git", "-C", str(PROJECT_DIR), "cat-file", "blob", sha],
                                  capture_output=True, check=True).stdout
            versions[int(stage)] = blob.decode("utf-8").replace("\r\n", "\n")
        return versions
    except Exception:
        return {}


def resolve_project_conflict(path):
    """Merged .kicad_pro text for a conflicted, still-unmerged file, or
    (None, reason) if it needs a human."""
    versions = git_unmerged_versions(path)
    if 2 not in versions or 3 not in versions:
        return None, ("git doesn't have both sides of the conflict any more (was the file committed "
                      "with the markers in it?). Restore it from an earlier commit: "
                      f"git log -- \"{path.name}\", then git checkout <commit> -- \"{path.name}\".")
    try:
        base, ours, theirs = (json.loads(versions[s]) if s in versions else {} for s in (1, 2, 3))
    except ValueError as e:
        return None, f"one side of the conflict isn't valid JSON ({e}); ask a lead."
    merged, conflicts = merge_json(base, ours, theirs)
    real = [c for c in conflicts
            if not (c.startswith("/text_variables/") and CI_TEXT_VARIABLE_RE.match(c[len("/text_variables/"):]))]
    if real:
        return None, ("both sides changed the same project settings, so this needs a human: "
                      + ", ".join(real) + ". Ask a lead.")
    return project_json_text(merged, versions[2]), None


def git_in_rebase():
    try:
        git_dir = subprocess.run(["git", "-C", str(PROJECT_DIR), "rev-parse", "--git-dir"],
                                 capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return False
    git_dir = PROJECT_DIR / git_dir
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


_REMOTE_PATH_RE = re.compile(r'"[^"]*[\\/]RemoteLibrary[\\/]([^"]*)"')


def fix_remote_library_paths(project_dir=PROJECT_DIR, dry_run=False):
    """Rewrite machine-specific RemoteLibrary paths to ${KIPRJMOD}/RemoteLibrary/...

    KiCad's Remote Symbols panel (used by Prism) writes the expanded absolute
    download path into fp-lib-table / sym-lib-table and the 3D model paths in
    downloaded footprints. Those break on any other machine and in CI.
    Safe to run repeatedly: already-relative paths are left unchanged.
    Returns the list of files that were (or, with dry_run, would be) modified.
    """
    project_dir = Path(project_dir)
    files = [project_dir / "fp-lib-table", project_dir / "sym-lib-table"]
    files += sorted((project_dir / "RemoteLibrary").rglob("*.kicad_mod"))

    def repl(m):
        rest = m.group(1).replace("\\", "/")
        return '"${KIPRJMOD}/RemoteLibrary/' + rest + '"'

    changed = []
    for f in files:
        if not f.is_file():
            continue
        # newline="" on read and write preserves CRLF/LF exactly
        with open(f, encoding="utf-8", newline="") as fh:
            text = fh.read()
        new = _REMOTE_PATH_RE.sub(repl, text)
        if new != text:
            if not dry_run:
                with open(f, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
            changed.append(f)
            print(f"  {'would fix' if dry_run else 'fixed'} RemoteLibrary paths in {f.relative_to(project_dir)}")
    return changed


# ----------------------------------------------------------------------------
# Change plan: collect every edit first, validate, then write all at once.
# ----------------------------------------------------------------------------

class Plan:
    def __init__(self):
        self.writes = {}    # Path -> (new_text, description)
        self.renames = []   # (old Path, new Path)

    def write(self, path, text, description):
        current = self.writes.get(path, (None,))[0]
        if current is None and path.exists():
            current = read(path)
        if text != current:
            prev = self.writes.get(path, (None, ""))[1]
            self.writes[path] = (text, f"{prev}; {description}" if prev else description)

    def text_of(self, path):
        return self.writes[path][0] if path in self.writes else read(path)

    def empty(self):
        return not self.writes and not self.renames

    def summary(self):
        lines = [f"  rename {o.name} -> {n.name}" for o, n in self.renames]
        lines += [f"  {p.relative_to(PROJECT_DIR)}: {d}" for p, (_, d) in self.writes.items()]
        return "\n".join(lines)

    def apply(self):
        for old, new in self.renames:
            if old.name.lower() == new.name.lower():  # case-only: go via a temp name
                tmp = old.with_name(old.name + ".renaming")
                old.rename(tmp)
                tmp.rename(new)
            else:
                old.rename(new)
        for path, (text, _) in self.writes.items():
            target = path
            for old, new in self.renames:
                if path == old:
                    target = new
            tmp = target.with_name(target.name + ".tmp")
            eol = _EOL.get(path, "\n")
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(text.replace("\n", eol) if eol != "\n" else text)
            os.replace(tmp, target)


def commit(plan, dry_run, confirm=True):
    """Validate the plan, show it, and write it."""
    if plan.empty():
        print("\nNothing to change - everything already matches.")
        return False
    if KIBOT_MAIN in plan.writes:
        problems = lint(plan.text_of(KIBOT_MAIN))
        if problems:
            print("\nRefusing to write - the result would break KiBot:")
            for p in problems:
                print(f"  - {p}")
            return False
    print("\nChanges:")
    print(plan.summary())
    if dry_run:
        print("\n(--dry-run: nothing written)")
        return False
    if confirm and sys.stdin.isatty() and not ask_yes_no("Apply these changes?", default=True):
        print("Cancelled - nothing written.")
        return False
    plan.apply()
    print("\nDone. Commit and push to run CI:\n"
          "  git add -A\n"
          '  git commit -m "chore: update board configuration"\n'
          "  git push")
    return True


# ----------------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------------

def action_stage(dry_run, requested=None, version=None):
    current = read_stage()
    current_version = read_release_version() if current == "RELEASED" else ""
    if requested is None:
        heading("Project stage")
        for i, (name, when, what) in enumerate(STAGES, start=1):
            mark = "  <- current" if name == current else ""
            print(f"  {i}. {name}{mark}\n     {when}\n     {what}")
        choice = ask("Choose 1-4 (Enter to cancel)", validate=lambda v: None if v in ("", "1", "2", "3", "4") else "Enter 1-4.")
        if not choice:
            return
        requested = STAGES[int(choice) - 1][0]

    requested = requested.upper()
    if requested not in STAGE_NAMES:
        raise ConfigError(f"Unknown stage '{requested}'. Choose one of: {', '.join(STAGE_NAMES)}.")

    plan = Plan()
    if requested == "RELEASED":
        tags = git_version_tags()
        print(f"\n  Last release: {tags[0] if tags else 'none yet'}")
        if version is None:
            if not sys.stdin.isatty():
                raise ConfigError("RELEASED needs a version: --stage RELEASED --version 1.0.0")
            version = ask("Version to release", suggest_next_version(tags), validate_release_version)
        error = validate_release_version(version)
        if error:
            raise ConfigError(error)
        if sys.stdin.isatty():
            # Stackup first: if it's wrong the fix is in KiCad, so cancel
            # before anyone has typed release notes that would be thrown away.
            if not review_stackup(plan, releasing=True):
                return
            if not edit_release_notes(plan):
                return
            review_manufacturing_notes(plan, ask_first=True)
            review_impedance_table(plan, ask_first=True)
        elif not any(read_release_notes(read(CHANGELOG) if CHANGELOG.exists() else "").values()):
            print("\n  Warning: CHANGELOG.md's [Unreleased] section is empty or placeholder text;"
                  "\n  that's what the release notes will say.")
        print(f"\n  On your next push, CI builds with ERC/DRC enforced, then tags {version},\n"
              "  updates main and creates the GitHub Release, using the notes above.\n"
              "  (Check with the Electrical Lead before pushing.)")
    else:
        if version is not None:
            raise ConfigError("--version only applies to --stage RELEASED.")
        version = ""
        if requested == "CHECKED":
            print("\n  Note: CHECKED enforces ERC/DRC. If the board still has errors, the next CI run fails until they're fixed.")

    if (requested, version) == (current, current_version) and plan.empty():
        print(f"\nAlready at {current}{' ' + version if version else ''}.")
        return

    def label(stage, v):
        return f"{stage} {v}" if v else stage
    plan.write(CI_YAML, set_stage_lines(read(CI_YAML), requested, version),
               f"stage {label(current, current_version)} -> {label(requested, version)}")
    commit(plan, dry_run)


def action_board_info(dry_run, first_time=False):
    stem = find_project_stem()
    kibot_text = read(KIBOT_MAIN)
    defs = read_definitions(kibot_text)
    pro_path = PROJECT_DIR / f"{stem}.kicad_pro"
    pro = load_project_json(pro_path)
    text_vars = pro.get("text_variables", {})

    heading("First-time setup" if first_time else "Board info")
    print("  Press Enter to keep the value in [brackets].\n")

    board_name = ask("Board name (repo name, e.g. bms_slave)",
                     "" if stem == PLACEHOLDER_STEM else stem.lower(), validate_board_name)
    title = ask("Board title", defs.get("PROJECT_NAME", ""),
                lambda v: validate_free_text(v, required=True) or validate_title_block("PROJECT_NAME", v))
    description = ask("One-sentence description (shown in README)", defs.get("DESCRIPTION", ""), validate_free_text)
    designer = ask(f"Designer (max ~{title_block_max_chars('DESIGNER')} characters)", defs.get("DESIGNER", ""),
                   lambda v: validate_free_text(v) or validate_title_block("DESIGNER", v))
    company = ask("Company", defs.get("COMPANY") or "Blue Devil Motor Sports", validate_free_text)
    # CI writes values like "+ (Unreleased)" here; don't offer those as a
    # default the validator would then reject.
    current_rev = text_vars.get("REVISION") or ""
    revision = ask("Revision (cosmetic; real revisions come from git tags)",
                   current_rev if not validate_revision(current_rev) else "0.1.0", validate_revision)

    impedance = ask_yes_no("Controlled-impedance board (enable impedance table)?", impedance_enabled(kibot_text))

    plan = Plan()

    # kibot_main.yaml
    new_kibot = quote_passthroughs(kibot_text)
    git_url = git_remote_url() or defs.get("GIT_URL") or f"https://github.com/BDMPowertrain/{board_name}"
    for key, value in (("PROJECT_NAME", title), ("BOARD_NAME", board_name.upper()), ("DESCRIPTION", description),
                       ("DESIGNER", designer), ("COMPANY", company), ("GIT_URL", git_url)):
        if defs.get(key) != value or key in FREE_TEXT_KEYS:
            new_kibot = set_definition(new_kibot, key, value)
    plan.write(KIBOT_MAIN, new_kibot, "board metadata")
    plan_impedance(plan, impedance)

    # .kicad_pro text variables
    if text_vars.get("COMPANY") != company or text_vars.get("REVISION") != revision:
        pro.setdefault("text_variables", {}).update({"COMPANY": company, "REVISION": revision})
        plan.write(pro_path, project_json_text(pro, read(pro_path)), "COMPANY/REVISION text variables")

    # Rename project files if the board name changed
    if board_name != stem:
        plan_rename(plan, stem, board_name)

    commit(plan, dry_run)


def toggle_impedance(text, enabled):
    head, defs = split_definitions(text)
    line_re = re.compile(r"^(\s*)(#\s*)?-\s*@CSV_IMPEDANCE_TABLE_OUTPUT@.*$", re.MULTILINE)
    m = line_re.search(head)
    if not m:
        return text  # template has no Tier 2 impedance line
    indent = m.group(1)
    new_line = (f"{indent}- @CSV_IMPEDANCE_TABLE_OUTPUT@   # Tier 2 (enabled by configure.py)" if enabled
                else f"{indent}# - @CSV_IMPEDANCE_TABLE_OUTPUT@   # Tier 2 - enable via configure.py")
    return head[:m.start()] + new_line + head[m.end():] + defs


def plan_rename(plan, old_stem, new_stem):
    """Rename the root project files and replace the old stem inside the
    root/sub-sheet .kicad_sch, .kicad_pro and .kicad_pcb (KiCad embeds the
    project name in sheet-instance data and export paths). Hierarchical
    sheet filenames are left alone - KiCad references them by relative
    path, and kibot_resources scripts expect the current names."""
    for ext in (".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_prl", ".kicad_dru"):
        old = PROJECT_DIR / f"{old_stem}{ext}"
        new = PROJECT_DIR / f"{new_stem}{ext}"
        if old.exists():
            # On Windows a case-only rename (BSPD -> bspd) makes `new.exists()`
            # true for the same file; that's fine, apply() handles it.
            if new.exists() and not os.path.samefile(old, new):
                raise ConfigError(f"Can't rename {old.name}: {new.name} already exists.")
            plan.renames.append((old, new))
    # Only replace the stem where it IS the project name: as a filename
    # (`BSPD.kicad_sch`) or a whole quoted value (`(project "BSPD"`). A plain
    # substring replace would also hit e.g. `BSPD_Compare.kicad_sch`, breaking
    # that sheet reference on case-sensitive filesystems (Linux CI).
    stem_re = re.compile(rf'(?<![\w.-]){re.escape(old_stem)}(?=\.kicad_\w+|")')
    for path in sorted(PROJECT_DIR.glob("*.kicad_sch")) + sorted(PROJECT_DIR.glob("*.kicad_pro")) + sorted(PROJECT_DIR.glob("*.kicad_pcb")):
        text = plan.text_of(path)
        new_text = stem_re.sub(new_stem, text)
        if new_text != text:
            plan.write(path, new_text, f"project name {old_stem} -> {new_stem}")


def action_manufacturing_docs(dry_run):
    plan = Plan()
    review_manufacturing_notes(plan, ask_first=False)
    review_impedance_table(plan, ask_first=False)
    review_stackup(plan, releasing=False)
    commit(plan, dry_run)


def action_show():
    stem = find_project_stem()
    defs = read_definitions(read(KIBOT_MAIN))
    pro = load_project_json(PROJECT_DIR / f"{stem}.kicad_pro")
    heading("Current settings")
    stage = read_stage()
    if stage == "RELEASED":
        stage += f" {read_release_version()}"
    rows = [("Project file", stem), ("Stage", stage),
            ("Title", defs.get("PROJECT_NAME", "")), ("Board name", defs.get("BOARD_NAME", "")),
            ("Description", defs.get("DESCRIPTION", "")), ("Designer", defs.get("DESIGNER", "")),
            ("Company", defs.get("COMPANY", "")), ("Revision", pro.get("text_variables", {}).get("REVISION", "")),
            ("GitHub URL", defs.get("GIT_URL", ""))]
    width = max(len(r[0]) for r in rows)
    for label, value in rows:
        print(f"  {label:<{width}}  {value}")


def action_check(fix=False, dry_run=False):
    text = read(KIBOT_MAIN)
    file_problems = project_file_problems()
    defs = read_definitions(text)
    fit_problems = [f"{key}: {err} Change it with 'Edit board info'." for key in TITLE_BLOCK_FIELDS
                    if (err := validate_title_block(key, defs.get(key, "")))]
    enabled = impedance_enabled(text)
    pdf_text = read(PDF_FAB_YAML) if PDF_FAB_YAML.exists() else ""
    include = impedance_include_state(pdf_text)
    impedance_problems = []
    if include is not None and include != enabled:
        impedance_problems.append(
            "The impedance table is " + ("off, but the fabrication drawing still fills it in"
                                         if not enabled else "on, but the fabrication drawing leaves it blank")
            + f" ({PDF_FAB_YAML.name}).")
    elif include is None and not enabled and "@NAME_IMPEDANCE_TABLE@" in pdf_text:
        impedance_problems.append(
            f"The impedance table is off, but {PDF_FAB_YAML.name} predates the on/off switch, so the "
            "fabrication drawing still fills it in. Copy that file from the current template.")
    problems = file_problems + lint(text) + fit_problems + impedance_problems
    if not problems:
        print("\nConfig OK - no problems found.")
        return True
    print("\nProblems found:")
    for p in problems:
        print(f"  - {p}")

    # Automatic fixes: quoting in kibot_main.yaml, and .kicad_pro merge
    # conflicts (almost always just CI's regenerated text variables).
    plan = Plan()
    fixed = quote_passthroughs(text)
    if fixed != text and not lint(fixed):
        plan.write(KIBOT_MAIN, fixed, "quoted free-text @VAR@ passthroughs")
    unresolved = [p for p in file_problems if ".kicad_pro" not in p] + fit_problems
    if include is not None and include != enabled:
        plan_impedance(plan, enabled)
    else:
        unresolved += impedance_problems
    for pro in sorted(PROJECT_DIR.glob("*.kicad_pro")):
        if not CONFLICT_MARKER_RE.search(read(pro)):
            if any(p.startswith(pro.name) for p in file_problems):
                unresolved.append(f"{pro.name}: not valid JSON - restore it from an earlier commit")
            continue
        merged, reason = resolve_project_conflict(pro)
        if merged is None:
            unresolved.append(f"{pro.name}: can't resolve the conflict automatically - {reason}")
        else:
            plan.write(pro, merged, "merge conflict resolved (both sides' changes kept)")

    applied = False
    if plan.empty():
        pass
    elif not fix:
        print("\n  Some of these can be fixed automatically - choose 'Check config' from the menu,\n"
              "  or run configure.py --check --fix.")
    else:
        applied = commit(plan, dry_run)
        if applied and any(p.suffix == ".kicad_pro" for p in plan.writes) and git_in_rebase():
            print("\n  (You're mid-rebase: instead of git commit, run git add -A then git rebase --continue.)")

    if unresolved:
        print("\nStill needs fixing by hand:" if fix else "\nNeeds fixing by hand:")
        for p in unresolved:
            print(f"  - {p}")
    if any(p in unresolved for p in file_problems) or any(".kicad_pro" in p for p in unresolved):
        print("\n  Do this BEFORE opening the project in KiCad: KiCad replaces an unreadable\n"
              "  .kicad_pro with default settings (text variables, net classes and design\n"
              "  rules all gone), and can't open a conflicted schematic or board at all.\n"
              "  For a .kicad_sch/.kicad_pcb conflict, keep one whole side - whoever owns\n"
              "  that sheet decides which (see README section 11) - or ask a lead.")
    return applied and not unresolved


# ----------------------------------------------------------------------------
# Menu / entry point
# ----------------------------------------------------------------------------

def is_fresh_template(stem):
    defs = read_definitions(read(KIBOT_MAIN))
    return stem == PLACEHOLDER_STEM or defs.get("BOARD_NAME") in ("", "BOARD_NAME")


def confirm_kicad_closed(stem):
    locks = kicad_is_open(stem)
    if locks:
        raise ConfigError("This project is open in KiCad (" + ", ".join(locks) + "). Close KiCad and run this again.")
    if sys.stdin.isatty() and not ask_yes_no("Is KiCad closed for this project?", default=True):
        raise ConfigError("Close KiCad, then run this again.")


def menu(dry_run):
    stem = find_project_stem()
    confirm_kicad_closed(stem)
    if project_file_problems():
        print("\n  ! The project files have unresolved merge conflicts or invalid JSON.\n"
              "    Choose 5. Check config to see them and resolve what can be resolved automatically.")
    if is_fresh_template(stem):
        print("\nThis looks like a fresh copy of the template - let's set it up.")
        action_board_info(dry_run, first_time=True)
    while True:
        stem = find_project_stem()
        defs = read_definitions(read(KIBOT_MAIN))
        heading(f"{defs.get('PROJECT_NAME') or stem}  -  stage: {read_stage()}")
        print("  1. Change project stage (DRAFT / PRELIMINARY / CHECKED / RELEASED)\n"
              "  2. Edit board info (title, description, designer, revision...)\n"
              "  3. Review fab / assembly notes, impedance table, stackup\n"
              "  4. Show current settings\n"
              "  5. Check config for problems\n"
              "  q. Quit")
        choice = ask("Choose", validate=lambda v: None if v.lower() in ("1", "2", "3", "4", "5", "q") else "Enter 1-5 or q.").lower()
        try:
            if choice == "1":
                action_stage(dry_run)
            elif choice == "2":
                action_board_info(dry_run)
            elif choice == "3":
                action_manufacturing_docs(dry_run)
            elif choice == "4":
                action_show()
            elif choice == "5":
                action_check(fix=True, dry_run=dry_run)
            else:
                return
        except ConfigError as e:
            print(f"\n  ! {e}")


def main():
    parser = argparse.ArgumentParser(description="BDM board configuration tool. Run with no arguments for the menu.")
    parser.add_argument("--stage", "--variant", dest="stage", metavar="NAME",
                        help="Set the project stage directly (DRAFT, PRELIMINARY, CHECKED, RELEASED).")
    parser.add_argument("--version", metavar="X.Y.Z", help="With --stage RELEASED, the version to release.")
    parser.add_argument("--init", action="store_true", help="Run first-time setup (board info) directly.")
    parser.add_argument("--check", action="store_true", help="Validate the config; exit 1 if there are problems.")
    parser.add_argument("--fix", action="store_true", help="With --check, auto-fix fixable problems.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing.")
    args = parser.parse_args()

    try:
        fix_remote_library_paths(dry_run=args.dry_run)
        if args.check:
            sys.exit(0 if action_check(fix=args.fix, dry_run=args.dry_run) else 1)
        if args.stage:
            confirm_kicad_closed(find_project_stem())
            action_stage(args.dry_run, requested=args.stage, version=args.version)
            return
        if not sys.stdin.isatty():
            raise ConfigError("The menu needs an interactive terminal. Use --stage or --check for scripts.")
        if args.init:
            stem = find_project_stem()
            confirm_kicad_closed(stem)
            action_board_info(args.dry_run, first_time=is_fresh_template(stem))
            return
        menu(args.dry_run)
    except ConfigError as e:
        sys.exit(f"Error: {e}")
    except KeyboardInterrupt:
        sys.exit("\nCancelled - nothing written.")


def launched_by_double_click():
    """True on Windows when this script owns its console window (Explorer
    double-click), which would otherwise close before you can read output."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleProcessList((ctypes.c_uint * 4)(), 4) <= 2
    except Exception:
        return False


if __name__ == "__main__":
    if sys.version_info < (3, 8):
        sys.exit("configure.py needs Python 3.8 or newer.")
    try:
        main()
    finally:
        if launched_by_double_click():
            input("\nPress Enter to close...")
