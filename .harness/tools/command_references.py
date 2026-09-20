#!/usr/bin/env python3
"""Детерминированный поиск устаревших ссылок на Harness commands в тексте.

Модуль намеренно не решает, является ли найденное упоминание фактическим drift:
он только находит command-looking legacy forms и предлагает каноническую замену.
Решение о том, является ли упоминание исторически намеренным, принимает caller.

Один и тот же набор patterns используют Harness Integrity и PROJECT RECONCILE,
чтобы правила legacy syntax не расходились между двумя проверками.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable


@dataclass(frozen=True)
class DeprecatedCommandPattern:
    pattern: re.Pattern[str]
    legacy: str
    canonical: str


@dataclass(frozen=True)
class DeprecatedCommandFinding:
    path: str
    line: int
    legacy: str
    canonical: str
    excerpt: str


DEPRECATED_COMMAND_PATTERNS: tuple[DeprecatedCommandPattern, ...] = (
    DeprecatedCommandPattern(re.compile(r"\bINIT PROJECT\b"), "INIT PROJECT", "PROJECT INIT"),
    DeprecatedCommandPattern(re.compile(r"\bADD STEP(?=[:\s])"), "ADD STEP", "STEP ADD:"),
    DeprecatedCommandPattern(re.compile(r"\bFIND SKILL(?=[:\s])"), "FIND SKILL", "SKILL FIND:"),
    DeprecatedCommandPattern(re.compile(r"\bINSTALL SKILL(?=[:\s])"), "INSTALL SKILL", "SKILL INSTALL:"),
    DeprecatedCommandPattern(re.compile(r"\bCREATE SKILL(?=[:\s])"), "CREATE SKILL", "SKILL CREATE:"),
    DeprecatedCommandPattern(re.compile(r"\bGENERATE GITHUB TEMPLATES\b"), "GENERATE GITHUB TEMPLATES", "GITHUB GENERATE TEMPLATES"),
    DeprecatedCommandPattern(re.compile(r"\bSTATUS PROJECT\b"), "STATUS PROJECT", "PROJECT STATUS"),
    DeprecatedCommandPattern(re.compile(r"\bNEXT STEP\b"), "NEXT STEP", "STEP NEXT"),
    DeprecatedCommandPattern(re.compile(r"\bRECONCILE PROJECT\b"), "RECONCILE PROJECT", "PROJECT RECONCILE"),
    DeprecatedCommandPattern(re.compile(r"\bCHECK HARNESS UPDATE\b"), "CHECK HARNESS UPDATE", "HARNESS UPDATE CHECK"),
    DeprecatedCommandPattern(re.compile(r"\bUPDATE HARNESS(?:\s+TO\b|\b)"), "UPDATE HARNESS", "HARNESS UPDATE APPLY"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*QUICK FIX(?=[:\x60\s]|$)"), "QUICK FIX", "PROJECT QUICK FIX:"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bPLAN STEP-"), "PLAN STEP-NNN", "STEP PLAN STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bIMPLEMENT STEP-"), "IMPLEMENT STEP-NNN", "STEP IMPLEMENT STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bREVIEW STEP-"), "REVIEW STEP-NNN", "STEP REVIEW STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bFIX STEP-"), "FIX STEP-NNN", "STEP FIX STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bRUN STEP-"), "RUN STEP-NNN", "STEP RUN STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bAUDIT STEP-"), "AUDIT STEP-NNN", "STEP AUDIT STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*COMMIT(?=[:\x60\s]|$)"), "COMMIT", "GIT COMMIT"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*PUSH(?=[\x60\s]|$)"), "PUSH", "GIT PUSH"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*PR(?=[\x60\s]|$)"), "PR", "GIT PR"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*SYNC(?=[\x60\s]|$)"), "SYNC", "GIT SYNC"),
)


def find_deprecated_commands(text: str) -> list[tuple[DeprecatedCommandPattern, re.Match[str]]]:
    """Вернуть все legacy command matches в порядке появления."""
    matches: list[tuple[DeprecatedCommandPattern, re.Match[str]]] = []
    for spec in DEPRECATED_COMMAND_PATTERNS:
        matches.extend((spec, match) for match in spec.pattern.finditer(text))
    matches.sort(key=lambda item: item[1].start())
    return matches


def scan_files(root: Path, paths: Iterable[Path]) -> list[DeprecatedCommandFinding]:
    """Просканировать UTF-8 text files и вернуть findings с точными line numbers."""
    findings: list[DeprecatedCommandFinding] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"cannot read live project document {path}: {exc}") from exc
        lines = text.splitlines()
        for spec, match in find_deprecated_commands(text):
            line = text.count("\n", 0, match.start()) + 1
            source_line = lines[line - 1] if lines else ""
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = str(path)
            findings.append(
                DeprecatedCommandFinding(
                    path=rel,
                    line=line,
                    legacy=spec.legacy,
                    canonical=spec.canonical,
                    excerpt=source_line.strip(),
                )
            )
    return findings


def _manifest_project_paths(root: Path) -> tuple[list[Path], Path]:
    """Прочитать live project paths из простого scalar subset manifest.yaml.

    Полный YAML parser намеренно не нужен: Harness manifest использует top-level
    sections и scalar path values. Неизвестные/сложные значения fail-closed.
    """
    manifest = root / ".harness" / "manifest.yaml"
    try:
        text = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"cannot read Harness manifest {manifest}: {exc}") from exc

    wanted = {
        "sources": {"projectOverview", "requirements", "architecture", "roadmap", "status"},
        "protocol": {"taskDirectory"},
    }
    values: dict[tuple[str, str], str] = {}
    section: str | None = None

    for raw_line in text.splitlines():
        if not raw_line or raw_line.lstrip().startswith("#"):
            continue
        top = re.fullmatch(r"([A-Za-z0-9_.-]+):\s*(?:#.*)?", raw_line)
        if top:
            section = top.group(1)
            continue
        if section not in wanted:
            continue
        item = re.match(r"^  ([A-Za-z0-9_.-]+):\s*([^#\s][^#]*?)\s*(?:#.*)?$", raw_line)
        if not item or item.group(1) not in wanted[section]:
            continue
        value = item.group(2).strip().strip('"').strip("'")
        if value:
            values[(section, item.group(1))] = value

    missing = [
        f"{section}.{key}"
        for section, keys in wanted.items()
        for key in sorted(keys)
        if (section, key) not in values
    ]
    if missing:
        raise RuntimeError(
            "Harness manifest missing command-reference scan paths: " + ", ".join(missing)
        )

    def resolve_repo_path(value: str) -> Path:
        rel = Path(value)
        if rel.is_absolute() or ".." in rel.parts:
            raise RuntimeError(f"Harness manifest path escapes repository: {value}")
        return root / rel

    project_paths = [
        resolve_repo_path(values[("sources", key)])
        for key in ("projectOverview", "requirements", "architecture", "roadmap", "status")
    ]
    task_directory = resolve_repo_path(values[("protocol", "taskDirectory")])
    return project_paths, task_directory


def project_live_document_paths(root: Path) -> list[Path]:
    """Вернуть active project-owned docs, где command syntax должен быть текущим.

    Primary project paths и taskDirectory берутся из .harness/manifest.yaml.
    Source path может быть файлом или каталогом; каталоги рекурсивно раскрываются
    в Markdown-файлы. Дополнительно сканируются README и live project docs под docs/**.
    Harness docs находятся вне project-owned `docs/**` под `.harness/docs/**`
    и поэтому сюда не попадают. Из `docs/**` исключается только `docs/adr/**`
    как immutable decision history; также не сканируются history-oriented planning
    records: reviews/audits/releases/updates/searches.
    """
    manifest_paths, task_directory = _manifest_project_paths(root)
    paths = [root / "README.md"]
    for path in manifest_paths:
        if path.is_dir():
            paths.extend(sorted(path.rglob("*.md")))
        else:
            paths.append(path)

    docs_root = root / "docs"
    if docs_root.exists():
        for path in sorted(docs_root.rglob("*.md")):
            rel = path.relative_to(docs_root)
            # docs/adr — исторические decision records; старый command syntax там может
            # намеренно отражать состояние проекта на момент принятия решения.
            if rel.parts and rel.parts[0] == "adr":
                continue
            paths.append(path)

    paths.extend(sorted(task_directory.glob("STEP-*.md")))
    return paths
