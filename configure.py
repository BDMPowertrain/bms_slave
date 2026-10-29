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
the .kicad_pro text variables. Don't hand-edit those.

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
import subprocess
import sys
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
            if not edit_release_notes(plan):
                return
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
    pro = json.loads(read(pro_path))
    text_vars = pro.get("text_variables", {})

    heading("First-time setup" if first_time else "Board info")
    print("  Press Enter to keep the value in [brackets].\n")

    board_name = ask("Board name (repo name, e.g. bms_slave)",
                     "" if stem == PLACEHOLDER_STEM else stem.lower(), validate_board_name)
    title = ask("Board title", defs.get("PROJECT_NAME", ""), lambda v: validate_free_text(v, required=True))
    description = ask("One-sentence description (shown in README)", defs.get("DESCRIPTION", ""), validate_free_text)
    designer = ask("Designer", defs.get("DESIGNER", ""), validate_free_text)
    company = ask("Company", defs.get("COMPANY") or "Blue Devil Motor Sports", validate_free_text)
    # CI writes values like "+ (Unreleased)" here; don't offer those as a
    # default the validator would then reject.
    current_rev = text_vars.get("REVISION") or ""
    revision = ask("Revision (cosmetic; real revisions come from git tags)",
                   current_rev if not validate_revision(current_rev) else "0.1.0", validate_revision)

    impedance_enabled = bool(re.search(r"^\s*-\s*@CSV_IMPEDANCE_TABLE_OUTPUT@", split_definitions(kibot_text)[0], re.MULTILINE))
    impedance = ask_yes_no("Controlled-impedance board (enable impedance table)?", impedance_enabled)

    plan = Plan()

    # kibot_main.yaml
    new_kibot = quote_passthroughs(kibot_text)
    git_url = git_remote_url() or defs.get("GIT_URL") or f"https://github.com/BDMPowertrain/{board_name}"
    for key, value in (("PROJECT_NAME", title), ("BOARD_NAME", board_name.upper()), ("DESCRIPTION", description),
                       ("DESIGNER", designer), ("COMPANY", company), ("GIT_URL", git_url)):
        if defs.get(key) != value or key in FREE_TEXT_KEYS:
            new_kibot = set_definition(new_kibot, key, value)
    new_kibot = toggle_impedance(new_kibot, impedance)
    plan.write(KIBOT_MAIN, new_kibot, "board metadata")

    # .kicad_pro text variables
    if text_vars.get("COMPANY") != company or text_vars.get("REVISION") != revision:
        pro.setdefault("text_variables", {}).update({"COMPANY": company, "REVISION": revision})
        plan.write(pro_path, json.dumps(pro, indent=2) + "\n", "COMPANY/REVISION text variables")

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


def action_show():
    stem = find_project_stem()
    defs = read_definitions(read(KIBOT_MAIN))
    pro = json.loads(read(PROJECT_DIR / f"{stem}.kicad_pro"))
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
    problems = lint(text)
    if not problems:
        print("\nConfig OK - no problems found.")
        return True
    print("\nProblems found:")
    for p in problems:
        print(f"  - {p}")
    fixed = quote_passthroughs(text)
    if fix and fixed != text and not lint(fixed):
        plan = Plan()
        plan.write(KIBOT_MAIN, fixed, "quoted free-text @VAR@ passthroughs")
        return commit(plan, dry_run)
    if fixed != text and not lint(fixed):
        print("\n  These can be fixed automatically - choose 'Check config' from the menu, or run configure.py --check --fix.")
    return False


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
    if is_fresh_template(stem):
        print("\nThis looks like a fresh copy of the template - let's set it up.")
        action_board_info(dry_run, first_time=True)
    while True:
        stem = find_project_stem()
        defs = read_definitions(read(KIBOT_MAIN))
        heading(f"{defs.get('PROJECT_NAME') or stem}  -  stage: {read_stage()}")
        print("  1. Change project stage (DRAFT / PRELIMINARY / CHECKED / RELEASED)\n"
              "  2. Edit board info (title, description, designer, revision...)\n"
              "  3. Show current settings\n"
              "  4. Check config for problems\n"
              "  q. Quit")
        choice = ask("Choose", validate=lambda v: None if v.lower() in ("1", "2", "3", "4", "q") else "Enter 1-4 or q.").lower()
        try:
            if choice == "1":
                action_stage(dry_run)
            elif choice == "2":
                action_board_info(dry_run)
            elif choice == "3":
                action_show()
            elif choice == "4":
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
