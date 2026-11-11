"""Print one released CHANGELOG.md section, formatted for a schematic text box.

Used by kibot_pre_set_text_variables.yaml to fill the Revision History sheet:
    get_changelog.py -f CHANGELOG.md --index 1 --title-only   newest release's title
    get_changelog.py -f CHANGELOG.md --index 2                the release before it
    get_changelog.py -f CHANGELOG.md --version 1.0.0          a specific release

Only released sections (`## [x.y.z] - YYYY-MM-DD`) count; [Unreleased] is
skipped. Prints nothing when there's no such release (yet), so an unused
Revision History column stays blank instead of showing an error.
"""
import argparse
import re
import sys

RELEASE_RE = re.compile(
    r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})[^\n]*\n(.*?)(?=^## |^\[[^\]\n]+\]:|\Z)",
    re.MULTILINE | re.DOTALL)


def releases(changelog):
    """[(version, date, body)], newest first (CHANGELOG.md order)."""
    return [m.groups() for m in RELEASE_RE.finditer(changelog)]


def format_body(content, extra_spaces, separators):
    if separators is not None:
        content = re.sub(r'^(###.*?)$', '_' * separators + r'\n\1', content, flags=re.MULTILINE)
    content = re.sub(r'### ', '', content)
    if extra_spaces:
        content = re.sub(r'(?<!\n)\n(?!\n)', '\n\n', content)
    return content


def main():
    parser = argparse.ArgumentParser(description="Extract and format a released version from CHANGELOG.md")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("-i", "--index", type=int, help="Nth newest release (1 = latest)")
    which.add_argument("-v", "--version", help="Version to extract (e.g., 1.0.1)")
    parser.add_argument("-f", "--file", required=True, help="Path to CHANGELOG.md file")
    parser.add_argument("-t", "--title-only", action="store_true", help="Print the title only")
    parser.add_argument("-s", "--extra-spaces", action="store_true", help="Add extra spaces between lines")
    parser.add_argument("-a", "--separators", type=int, required=False, help="Number of underscores for separators")
    args = parser.parse_args()

    try:
        with open(args.file, encoding="utf-8") as f:
            changelog = f.read().replace("\r\n", "\n")
    except FileNotFoundError:
        print(f"Error: File '{args.file}' not found.")
        sys.exit(1)

    found = releases(changelog)
    if args.index is not None:
        found = found[args.index - 1:args.index] if args.index >= 1 else []
    else:
        found = [r for r in found if r[0] == args.version]
    if not found:
        return  # no such release yet: leave the text box empty

    version, date, body = found[0]
    if args.title_only:
        print(f"Version {version} - {date}")
    else:
        print(format_body(body, args.extra_spaces, args.separators))


if __name__ == "__main__":
    main()
