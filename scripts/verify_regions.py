#!/usr/bin/env python3
"""
Verify semantic regions: find all [START SPEC:...] markers in bot code,
check that SPEC_ID is referenced in docs/specs, and print a report.
Usage: python scripts/verify_regions.py   (run from python-runner root)
"""

import re
import sys
from pathlib import Path


def find_regions_in_file(file_path: Path) -> list[tuple[str, str]]:
    """Find all [START SPEC:SPEC_ID:REGION_NAME] in file. Returns list of (spec_id, region_name)."""
    pattern = re.compile(r"#\s*\[START SPEC:([A-Z0-9\-]+):([^\]]+)\]")
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return pattern.findall(text)


def find_all_regions(bot_root: Path) -> list[tuple[Path, str, str]]:
    """Scan bot_root for .py files and collect (file, spec_id, region_name)."""
    results: list[tuple[Path, str, str]] = []
    for py_path in bot_root.rglob("*.py"):
        for spec_id, region_name in find_regions_in_file(py_path):
            results.append((py_path, spec_id, region_name))
    return results


def spec_id_referenced_in_docs(spec_id: str, docs_specs_root: Path, repo_root: Path) -> bool:
    """True if SPEC_ID is mentioned in any spec file or in SEMANTIC_REGIONS_GUIDE.md."""
    guide = repo_root / "docs" / "SEMANTIC_REGIONS_GUIDE.md"
    if guide.is_file() and spec_id in guide.read_text(encoding="utf-8"):
        return True
    if spec_id.startswith("TASK-"):
        num = spec_id.split("-")[-1]
        for md in docs_specs_root.rglob("*.md"):
            if f"TASK-{num}" in md.name or spec_id in md.name:
                return True
        return False
    for md in docs_specs_root.rglob("*.md"):
        try:
            if spec_id in md.read_text(encoding="utf-8"):
                return True
        except OSError:
            continue
    return False


def main() -> int:
    # Assume run from python-runner
    repo_root = Path(__file__).resolve().parent.parent
    bot_root = repo_root / "telegram-casino-bot" / "bot"
    docs_specs = repo_root / "docs" / "specs"

    if not bot_root.is_dir():
        print("Expected bot dir at:", bot_root, file=sys.stderr)
        return 1

    regions = find_all_regions(bot_root)
    if not regions:
        print("No semantic regions found under", bot_root)
        return 0

    # Build report
    by_spec: dict[str, list[tuple[Path, str]]] = {}
    for file_path, spec_id, region_name in regions:
        by_spec.setdefault(spec_id, []).append((file_path, region_name))

    missing: list[str] = []
    for spec_id in by_spec:
        if not spec_id_referenced_in_docs(spec_id, docs_specs, repo_root):
            missing.append(spec_id)

    print(f"Found {len(regions)} semantic region(s)")
    print()
    print("| SPEC_ID | Region | File |")
    print("|---------|-------|------|")
    for spec_id in sorted(by_spec.keys()):
        for file_path, region_name in by_spec[spec_id]:
            short = (
                file_path.relative_to(repo_root) if repo_root in file_path.parents else file_path
            )
            ref = "✓" if spec_id not in missing else "⚠"
            print(f"| {spec_id} {ref} | {region_name} | {short} |")

    if missing:
        print()
        print("⚠ SPEC_ID(s) not referenced in docs/specs:", ", ".join(missing))
        return 1
    print()
    print("✓ All SPEC_IDs have corresponding specs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
