#!/usr/bin/env python3
"""Release gate: managed workflows не содержат временных CI-артефактов (#379).

Workflow из `.github/workflows/` поставляются downstream-проектам как managed
paths. Временный workflow отдельного PR, push-триггер на рабочую ветку или
pinned fetch/restore upstream commit в downstream мёртв либо опасен, поэтому
release candidate с такими артефактами не квалифицируется.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


WORKFLOW_DIRECTORY = ".github/workflows"
# Долгоживущие integration targets Harness. Пример: main, feature/**.
ALLOWED_BRANCH_FILTERS = frozenset({"main", "feature/**"})
TEMPORARY_WORKFLOW_RE = re.compile(r"^pr[-_]?\d+", re.IGNORECASE)
BRANCH_KEY_RE = re.compile(r"^(?P<indent>\s*)(?:branches|branches-ignore)\s*:\s*(?P<inline>.*)$")
LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)-\s*(?P<value>.+?)\s*$")
PINNED_GIT_RE = re.compile(
    r"\bgit\s+(?:fetch|restore|checkout|switch|reset|cherry-pick|merge|rebase)\b.*\b[0-9a-f]{40}\b",
    re.IGNORECASE,
)


def _strip_comment(line: str) -> str:
    # В workflow YAML `#` внутри значения встречается только в кавычках/expressions;
    # для triggers и git-команд достаточно отбросить хвост после ` #`.
    if line.lstrip().startswith("#"):
        return ""
    return re.split(r"\s#", line, maxsplit=1)[0].rstrip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _workflow_files(root: Path) -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", WORKFLOW_DIRECTORY],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    )
    if proc.returncode == 0:
        names = [name for name in proc.stdout.split("\0") if name]
    else:
        folder = root / WORKFLOW_DIRECTORY
        names = [path.relative_to(root).as_posix() for path in folder.glob("*")] if folder.is_dir() else []
    return sorted(root / name for name in names if name.endswith((".yml", ".yaml")))


def _branch_filters(lines: list[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        match = BRANCH_KEY_RE.match(lines[index])
        index += 1
        if match is None:
            continue
        inline = match.group("inline").strip()
        if inline:
            items = inline[1:-1].split(",") if inline.startswith("[") and inline.endswith("]") else [inline]
            found.extend((index, _unquote(item)) for item in items if item.strip())
            continue
        key_indent = len(match.group("indent"))
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            item = LIST_ITEM_RE.match(line)
            if item is None or len(item.group("indent")) < key_indent:
                break
            index += 1
            found.append((index, _unquote(item.group("value"))))
    return found


def inspect(root: Path) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    for path in _workflow_files(root):
        rel = path.relative_to(root).as_posix()
        if TEMPORARY_WORKFLOW_RE.match(path.name):
            violations.append({"code": "TEMPORARY_WORKFLOW_FILE", "path": rel, "line": None, "value": path.name})
        try:
            raw = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            violations.append({"code": "WORKFLOW_UNREADABLE", "path": rel, "line": None, "value": None})
            continue
        lines = [_strip_comment(line) for line in raw]
        for line_no, branch in _branch_filters(lines):
            if branch not in ALLOWED_BRANCH_FILTERS:
                violations.append({"code": "TEMPORARY_BRANCH_TRIGGER", "path": rel, "line": line_no, "value": branch})
        for line_no, line in enumerate(lines, start=1):
            if PINNED_GIT_RE.search(line):
                violations.append({"code": "PINNED_UPSTREAM_COMMIT", "path": rel, "line": line_no,
                                   "value": line.strip()})
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    violations = inspect(root)
    status = "FAIL" if violations else "PASS"
    if args.json:
        print(json.dumps({"kind": "release_artifact_hygiene", "status": status, "violations": violations},
                         ensure_ascii=False))
    else:
        for item in violations:
            location = item["path"] if item["line"] is None else f"{item['path']}:{item['line']}"
            print(f"{item['code']}: {location}: {item['value']}")
        print("RELEASE ARTIFACT HYGIENE: " + status)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
