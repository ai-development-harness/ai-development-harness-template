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
# Ключ фильтра веток в начале строки или внутри flow mapping, в том числе в кавычках.
# Пример: `branches:`, `'branches-ignore':`, `push: {branches: [main, fix/x]}`.
BRANCH_KEY_RE = re.compile(r"(?P<lead>^\s*|[{,]\s*)(?P<quote>['\"]?)(?:branches-ignore|branches)(?P=quote)\s*:")
LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)-\s*(?P<value>.+?)\s*$")
# Любой полный commit SHA считается overlay: git fetch/restore, checkout `ref:`,
# значение в `env:` или продолжение команды на следующей строке.
# Пример: `UPSTREAM: <sha>` + `git fetch origin "$UPSTREAM"`.
FULL_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b", re.IGNORECASE)
# Supply-chain pinning action разрешён. Пример: `- uses: actions/checkout@<sha>`.
ACTION_PIN_RE = re.compile(r"^\s*(?:-\s+)?uses\s*:\s*['\"]?[^\s'\"@]+@[0-9a-f]{40}['\"]?$", re.IGNORECASE)


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


def _flow_items(text: str) -> list[str]:
    body = text.strip().removeprefix("[").removesuffix("]")
    return [_unquote(item) for item in body.split(",") if item.strip()]


def _flow_sequence(lines: list[str], index: int, text: str) -> str:
    # Flow sequence заканчивается парной `]`, после неё может идти `}` flow mapping.
    # Пример: `push: {branches: [main, fix/x]}` либо `[` … `]` на нескольких строках.
    while True:
        depth = 0
        for pos, char in enumerate(text):
            if char in "[]":
                depth += 1 if char == "[" else -1
                if depth == 0:
                    return text[: pos + 1]
        if index >= len(lines):
            return text
        text += " " + lines[index].strip()
        index += 1


def _branch_values(lines: list[str], number: int, match: re.Match[str]) -> list[tuple[int, str]]:
    line = lines[number - 1]
    value = line[match.end():].strip()
    index = start = number
    # Flow sequence может начинаться строкой ниже и занимать несколько строк.
    # Пример: `branches:` + `  [main, fix/x]` либо `branches: [` … `]`.
    if not value:
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index < len(lines) and lines[index].lstrip().startswith("["):
            value = lines[index].strip()
            index += 1
            start = index
    if value.startswith("["):
        return [(start, item) for item in _flow_items(_flow_sequence(lines, index, value))]
    if value:
        # Scalar внутри flow mapping заканчивается на `,` или `}`. Пример: `{branches: main}`.
        if match.group("lead").strip():
            value = re.split(r"[,}]", value, maxsplit=1)[0]
        return [(start, _unquote(value))]
    found: list[tuple[int, str]] = []
    key_indent = len(line) - len(line.lstrip())
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        item = LIST_ITEM_RE.match(lines[index])
        if item is None or len(item.group("indent")) < key_indent:
            break
        index += 1
        found.append((index, _unquote(item.group("value"))))
    return found


def _branch_filters(lines: list[str]) -> list[tuple[int, str]]:
    # Каждая строка сканируется целиком: flow mapping может нести несколько ключей,
    # а значения уже разобранного ключа с BRANCH_KEY_RE не совпадают.
    # Пример: `push: {branches: [main], branches-ignore: [fix/x]}`.
    found: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        for match in BRANCH_KEY_RE.finditer(line):
            found.extend(_branch_values(lines, number, match))
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
            if FULL_SHA_RE.search(line) and not ACTION_PIN_RE.match(line):
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
