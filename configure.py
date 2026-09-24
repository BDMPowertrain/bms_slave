#!/usr/bin/env python3
"""
BDM board configuration tool.

This is the ONLY supported way to change board metadata, rename a freshly
templated project, or change a board's variant. Never hand-edit kibot_main.yaml,
ci.yaml, or the text variables inside a .kicad_pro file — this script owns those.

Python 3 standard library only. No pip install, ever. Fully self-contained:
everything this script needs lives in this repo, no network access required.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Lowercase letters, digits, and underscores only — no hyphens, no spaces, and
# deliberately no car/year prefix (e.g. "ev27-"), since the same template and
# naming convention carries forward to future cars without renaming anything.
BOARD_NAME_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
PLACEHOLDER_STEM = "BOARD_TEMPLATE"

VARIANTS = [
    ("DRAFT", "Schematic still being drawn. Only the netlist, schematic PDF, and a "
              "draft BoM are generated. No ERC/DRC. Matches Plane's Design phase, early cycle."),
    ("PRELIMINARY", "Schematic is close to final. Full schematic AND PCB documents generate, "
                    "but ERC/DRC are still not enforced. Matches Design phase, late cycle."),
    ("CHECKED", "Board is believed correct. Full documents generate WITH ERC/DRC enforced — "
               "CI fails the run if either has errors. Matches Procurement/Fabrication phase."),
]


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------

class Change:
    """One (file, description) edit, tracked so we can print a summary and
    respect --dry-run without every function needing its own if-statement."""
    def __init__(self, path: Path, description: str):
        self.path = path
        self.description = description


def prompt(label: str, default: str, validator=None, error_msg: str = "") -> str:
    """Ask a question, showing `default` as what pressing Enter keeps.
    Re-prompts forever until `validator` (if given) returns True."""
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        value = raw if raw else default
        if validator is None or validator(value):
            return value
        print(f"  {error_msg or 'Invalid value, try again.'}")


def atomic_write(path: Path, content: str, changes: list, description: str, dry_run: bool):
    """Write `content` to `path` without ever leaving a half-written file if the
    process crashes mid-write: write to a sibling temp file, then os.replace()
    it into place (atomic on both Windows and Linux for same-volume renames).
    Also keeps a .bak copy of whatever was there before (safe to keep around —
    .gitignore already excludes *.bak)."""
    changes.append(Change(path, description))
    if dry_run:
        return
    if path.exists():
        path.with_suffix(path.suffix + ".bak").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)  # atomic rename


def find_lock_files(project_dir: Path, stem: str) -> list:
    # KiCad's LOCKFILE class writes "~<filename>.lck" next to each open file.
    # Best-effort detection (confirmed via KiCad's own LOCKFILE source and
    # several GitLab issue reports, but not independently verified by hand
    # against KiCad 10) — always paired with the explicit confirmation below.
    return sorted(project_dir.glob(f"~{stem}.*.lck"))


def refuse_if_open(project_dir: Path, stem: str):
    locks = find_lock_files(project_dir, stem)
    if locks:
        print("This project looks like it's currently open in KiCad:")
        for lock in locks:
            print(f"  {lock.name}")
        print("\nClose KiCad completely, then run this script again.")
        sys.exit(1)

    # Lock-file detection is best-effort, not guaranteed — always double check.
    if sys.stdin.isatty():
        answer = input(
            "Confirm KiCad is completely closed for this project right now [y/N]: "
        ).strip().lower()
        if answer != "y":
            print("Aborting — close KiCad and run this script again.")
            sys.exit(1)


def find_project_stem(project_dir: Path) -> str:
    pro_files = list(project_dir.glob("*.kicad_pro"))
    if len(pro_files) != 1:
        sys.exit(
            f"Expected exactly one .kicad_pro file in {project_dir}, found {len(pro_files)}. "
            "Something is wrong with this repo's layout — ask a lead for help."
        )
    return pro_files[0].stem


def is_fresh_template(stem: str, kibot_main_text: str) -> bool:
    return stem == PLACEHOLDER_STEM or "BOARD_NAME: BOARD_NAME" in kibot_main_text


def git_remote_url(project_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        )
        url = result.stdout.strip()
        # normalize git@github.com:org/repo.git -> https://github.com/org/repo
        url = re.sub(r"^git@github\.com:", "https://github.com/", url)
        url = re.sub(r"\.git$", "", url)
        return url
    except Exception:
        return ""


# ----------------------------------------------------------------------------
# File patchers — each one is idempotent: safe to run every time, only
# actually changes the file (and gets logged in `changes`) if the value differs.
# ----------------------------------------------------------------------------

DEFINITIONS_MARKER = re.compile(r"^\.\.\.\s*$", re.MULTILINE)


def split_at_definitions(text: str):
    """kibot_main.yaml uses KEY: @KEY@ passthrough lines inside several
    `import:` blocks (e.g. PROJECT_NAME, BOARD_NAME, DESIGNER all appear this
    way in the kibot_pre_set_text_variables.yaml import) to forward the real
    values into sub-configs under the same name. The REAL values live in the
    global `definitions:` block after the YAML '...' document separator at
    the bottom of the file. Reading or patching by key name alone would match
    whichever occurrence comes first in the file — the passthrough, not the
    real one — so every lookup/patch is scoped to the text after this marker."""
    match = DEFINITIONS_MARKER.search(text)
    if not match:
        sys.exit("Could not find the '...' document separator in kibot_main.yaml — has its structure changed?")
    return text[:match.end()], text[match.end():]


def patch_yaml_scalar(text: str, key: str, value: str) -> str:
    """Replace a `KEY: value` line in kibot_main.yaml's global definitions
    block (only). Regex-based on purpose — the stdlib has no YAML parser, and
    a real YAML round-trip would strip the comments these files rely on for
    readability."""
    head, tail = split_at_definitions(text)
    pattern = re.compile(rf"^(\s*{re.escape(key)}:\s*).*$", re.MULTILINE)
    quoted = f"'{value}'" if re.search(r"[:#]", value) else value
    if not pattern.search(tail):
        sys.exit(f"Could not find '{key}:' in kibot_main.yaml's definitions block — has its structure changed?")
    return head + pattern.sub(rf"\g<1>{quoted}", tail, count=1)


def rename_project_files(project_dir: Path, old_stem: str, new_stem: str, changes: list, dry_run: bool):
    if old_stem == new_stem:
        return
    for ext in (".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_prl", ".kicad_dru"):
        old_path = project_dir / f"{old_stem}{ext}"
        if not old_path.exists():
            continue
        new_path = project_dir / f"{new_stem}{ext}"
        changes.append(Change(new_path, f"renamed from {old_path.name}"))
        if not dry_run:
            old_path.rename(new_path)
    # Hierarchical sheet files (Block Diagram.kicad_sch, Section A - Title A.kicad_sch,
    # etc.) are NOT renamed. Only the root project stem needs to match .kicad_pro for
    # KiCad to recognize the project; the sub-sheets are referenced by KiCad internally
    # via UUID + relative path, neither of which depends on the root's name. Renaming
    # them would be pure churn for zero benefit, and would break the kibot_resources
    # helper scripts that expect these filenames. Change a sheet's TITLE inside KiCad
    # (double-click the sheet -> Sheet Properties), not its filename.

    # BUT: KiCad also embeds the project's own name as a literal string INSIDE
    # every .kicad_sch (root AND hierarchical sub-sheets both — it's in each
    # sheet's symbol/sheet-instance-tracking data) and inside .kicad_pro (its
    # own filename, plus default export paths for netlist/step/BOM). Renaming
    # the files alone leaves all of that stale, so every .kicad_sch/.kicad_pro/
    # .kicad_pcb in the project gets a plain text substitution of the old
    # project name for the new one. This runs after the file rename above, so
    # the glob below picks up the root file under its NEW name.
    content_files = (
        sorted(project_dir.glob("*.kicad_sch"))
        + sorted(project_dir.glob("*.kicad_pro"))
        + sorted(project_dir.glob("*.kicad_pcb"))
    )
    for path in content_files:
        text = path.read_text(encoding="utf-8")
        if old_stem not in text:
            continue
        new_text = text.replace(old_stem, new_stem)
        atomic_write(
            path, new_text, changes,
            f"internal project-name references updated ({old_stem} -> {new_stem})",
            dry_run,
        )


def patch_kicad_pro_text_variables(path: Path, updates: dict, changes: list, dry_run: bool, read_path: Path = None):
    """Writes into the "text_variables" object of a .kicad_pro file without
    touching anything else in that JSON (board settings, net classes, etc.).
    `read_path` lets a caller read from a different (currently-existing) file
    than the one being written to — needed for --dry-run when a rename hasn't
    actually happened yet, so the target filename doesn't exist on disk."""
    data = json.loads((read_path or path).read_text(encoding="utf-8"))
    current = data.get("text_variables", {})
    if all(current.get(k) == v for k, v in updates.items()):
        return  # nothing changed, don't touch the file
    current.update(updates)
    data["text_variables"] = current
    new_text = json.dumps(data, indent=2) + "\n"
    atomic_write(path, new_text, changes, "text_variables (COMPANY/REVISION) updated", dry_run)


def patch_kibot_main(path: Path, values: dict, tier2_impedance: bool, changes: list, dry_run: bool):
    text = path.read_text(encoding="utf-8")
    original = text
    for key, value in values.items():
        text = patch_yaml_scalar(text, key, value)

    impedance_line = "      - @CSV_IMPEDANCE_TABLE_OUTPUT@"
    commented = "      # - @CSV_IMPEDANCE_TABLE_OUTPUT@   # Tier 2 — configure.py uncomments this line when enabled"
    if tier2_impedance and commented.strip("# ").strip() not in text:
        text = text.replace(commented, impedance_line + "   # Tier 2 (enabled)")
    elif not tier2_impedance and impedance_line in text:
        text = text.replace(impedance_line + "   # Tier 2 (enabled)", commented)

    if text != original:
        atomic_write(path, text, changes, "board metadata / Tier 2 settings updated", dry_run)


def patch_ci_variant(path: Path, variant: str, changes: list, dry_run: bool):
    """The ONLY thing this script ever writes into ci.yaml: the top-level
    `kibot_variant:` env value. Everything else in that file is maintainer-only."""
    text = path.read_text(encoding="utf-8")
    original = text
    text = re.sub(r"(kibot_variant:\s*).*", rf"\g<1>{variant}", text, count=1)
    if text != original:
        atomic_write(path, text, changes, f"kibot_variant={variant}", dry_run)


def seed_changelog(path: Path, changes: list, dry_run: bool):
    if path.exists() and "[Unreleased]" in path.read_text(encoding="utf-8"):
        return
    content = (
        "# Changelog\n\n"
        "All notable changes to this board are documented here, following\n"
        "[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and\n"
        "[semantic versioning for hardware](https://www.maskset.net/blog/2023/02/26/"
        "semantic-versioning-for-hardware/).\n\n"
        "## [Unreleased]\n\n"
        "### Added\n\n"
    )
    atomic_write(path, content, changes, "seeded with [Unreleased] section", dry_run)


def seed_readme(path: Path, board_title: str, changes: list, dry_run: bool):
    # A new board repo inherits the template's own real README.md, so this
    # normally never fires — it's just a fallback in case README.md is ever
    # missing. README.md is regenerated by KiBot from
    # kibot_resources/templates/readme.txt on every CI run; never overwrites
    # a real one that already exists.
    if path.exists():
        return
    content = (
        f"# {board_title}\n\n"
        "This README is placeholder text. It is fully overwritten by KiBot on "
        "the first CI run — do not edit it by hand. See "
        "https://github.com/BDMPowertrain/board_template in the meantime.\n"
    )
    atomic_write(path, content, changes, "seeded placeholder (KiBot overwrites on first CI run)", dry_run)


# ----------------------------------------------------------------------------
# Modes
# ----------------------------------------------------------------------------

def run_setup(project_dir: Path, dry_run: bool):
    """Modes 1 and 2 share this: same prompts, current values as defaults.
    Whether files get renamed is just whether the board name actually changed —
    that's what makes this safely re-runnable. This mode never touches
    ci.yaml's variant — that's Mode 3's job only."""
    old_stem = find_project_stem(project_dir)
    kibot_main_path = project_dir / "kibot_yaml" / "kibot_main.yaml"
    kibot_main_text = kibot_main_path.read_text(encoding="utf-8")
    fresh = is_fresh_template(old_stem, kibot_main_text)

    refuse_if_open(project_dir, old_stem)

    _, kibot_definitions_tail = split_at_definitions(kibot_main_text)

    def current(key: str, fallback: str) -> str:
        m = re.search(rf"^\s*{key}:\s*'?([^'\n]*)'?\s*$", kibot_definitions_tail, re.MULTILINE)
        return m.group(1).strip() if m and m.group(1).strip() else fallback

    print(f"\n{'First-time setup' if fresh else 'Update board settings'}\n")

    board_name = prompt(
        "Board name (repo name, e.g. tim or bse_apps)",
        old_stem.lower() if old_stem != PLACEHOLDER_STEM else "",
        validator=lambda v: bool(BOARD_NAME_RE.match(v)),
        error_msg="Lowercase letters, digits, and underscores only (e.g. tim, bse_apps) "
                  "— no spaces, no hyphens, no year/car prefix.",
    )
    # These four land inside a double-quoted YAML string when KiBot builds the
    # schematic's text variables (kibot_pre_set_text_variables.yaml) — a
    # plain apostrophe is fine there, but a literal " or \ isn't and would
    # break every KiBot run with a cryptic YAML parse error, the same class
    # of bug that motivated switching those fields to double quotes in the
    # first place. Reject them here instead of letting that surface in CI.
    def no_quotes_or_backslash(v: str) -> bool:
        return '"' not in v and "\\" not in v

    quote_error = 'Straight quotes (") and backslashes (\\) break KiBot\'s YAML config — rephrase without them.'

    board_title = prompt(
        "Human-readable board title", current("PROJECT_NAME", "Board Name"),
        validator=no_quotes_or_backslash, error_msg=quote_error,
    )
    description = prompt(
        "Short description of this board (one sentence, shown in the README)",
        current("DESCRIPTION", ""),
        validator=no_quotes_or_backslash, error_msg=quote_error,
    )
    designer = prompt(
        "Designer name", current("DESIGNER", ""),
        validator=no_quotes_or_backslash, error_msg=quote_error,
    )
    company = prompt(
        "Company", current("COMPANY", "Blue Devil Motor Sports"),
        validator=no_quotes_or_backslash, error_msg=quote_error,
    )
    revision = prompt("Initial revision (cosmetic only — real revision comes from git tags at release)",
                       "0.1.0")
    tier2_answer = prompt(
        "Enable Tier 2 impedance table output? (only relevant if this board has "
        "controlled-impedance traces) [y/n]",
        "n", validator=lambda v: v.lower() in ("y", "n"), error_msg="Answer y or n.",
    )
    tier2_impedance = tier2_answer.lower() == "y"

    changes = []
    rename_project_files(project_dir, old_stem, board_name, changes, dry_run)

    new_pro_path = project_dir / f"{board_name}.kicad_pro"
    old_pro_path = project_dir / f"{old_stem}.kicad_pro"
    read_pro_path = old_pro_path if (dry_run and old_stem != board_name) else new_pro_path
    patch_kicad_pro_text_variables(
        new_pro_path, {"COMPANY": company, "REVISION": revision}, changes, dry_run, read_path=read_pro_path
    )

    git_url = git_remote_url(project_dir) or f"https://github.com/BDMPowertrain/{board_name}"
    patch_kibot_main(
        kibot_main_path,
        {
            "PROJECT_NAME": board_title,
            "BOARD_NAME": board_name.upper(),
            "DESCRIPTION": description,
            "DESIGNER": designer,
            "COMPANY": company,
            "GIT_URL": git_url,
        },
        tier2_impedance, changes, dry_run,
    )

    seed_changelog(project_dir / "CHANGELOG.md", changes, dry_run)
    seed_readme(project_dir / "README.md", board_title, changes, dry_run)

    print_summary(changes, dry_run)


def run_variant(project_dir: Path, requested: str, dry_run: bool):
    stem = find_project_stem(project_dir)
    ci_yaml_path = project_dir / ".github" / "workflows" / "ci.yaml"
    text = ci_yaml_path.read_text(encoding="utf-8")
    variant_match = re.search(r"kibot_variant:\s*(\S+)", text)
    current_variant = variant_match.group(1) if variant_match else "DRAFT"

    if requested is None:
        print(f"\nCurrent variant: {current_variant}\n")
        for i, (name, desc) in enumerate(VARIANTS, start=1):
            marker = " (current)" if name == current_variant else ""
            print(f"  {i}. {name}{marker}\n     {desc}\n")
        choice = prompt(
            "Choose a variant (1-3)", "",
            validator=lambda v: v in ("1", "2", "3"),
            error_msg="Enter 1, 2, or 3.",
        )
        requested = VARIANTS[int(choice) - 1][0]

    requested = requested.upper()
    if requested == "RELEASED":
        print(
            "\nRELEASED is not something this script sets. It is produced automatically "
            "by pushing a version tag, per the CI model — that's what guarantees a RELEASED "
            "build always corresponds to a real, tagged, immutable release.\n\n"
            "To release this board:\n\n"
            "  git checkout main\n"
            "  git pull\n"
            "  git tag 1.0.0\n"
            "  git push origin 1.0.0\n\n"
            "(Only the Electrical Lead pushes tags — check with them first.)\n"
        )
        sys.exit(1)

    if requested not in [v[0] for v in VARIANTS]:
        sys.exit(f"Unknown variant '{requested}'. Choose from: DRAFT, PRELIMINARY, CHECKED.")

    if requested == "CHECKED" and current_variant != "CHECKED":
        print(
            "\nMoving to CHECKED: CI will now enforce ERC and DRC. If this board has "
            "existing errors, the NEXT CI run is expected to fail until they're fixed — "
            "that's the point of this variant, not a bug.\n"
        )

    refuse_if_open(project_dir, stem)
    changes = []
    patch_ci_variant(ci_yaml_path, requested, changes, dry_run)
    print_summary(changes, dry_run)


def print_summary(changes: list, dry_run: bool):
    print()
    if not changes:
        print("No changes needed — everything already matches what you entered.")
        return
    heading = "Would change (--dry-run, nothing written):" if dry_run else "Changed:"
    print(heading)
    for c in changes:
        print(f"  {c.path.relative_to(c.path.anchor) if c.path.is_absolute() else c.path} — {c.description}")
    if dry_run:
        return
    print(
        "\nNext steps:\n"
        "  git status\n"
        "  git add -A\n"
        '  git commit -m "chore: run configure.py"\n'
        "  git push\n"
    )


# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="BDM board configuration tool.")
    parser.add_argument("--init", action="store_true", help="First-time setup (also runs automatically on a fresh template).")
    parser.add_argument("--variant", nargs="?", const="", help="Change variant. Bare flag opens a menu; --variant CHECKED sets it directly.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing anything.")
    args = parser.parse_args()

    project_dir = Path(__file__).resolve().parent

    if args.variant is not None:
        run_variant(project_dir, args.variant or None, args.dry_run)
    else:
        run_setup(project_dir, args.dry_run)


if __name__ == "__main__":
    main()
