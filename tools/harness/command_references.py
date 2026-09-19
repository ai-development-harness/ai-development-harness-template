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
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*PLAN STEP-"), "PLAN STEP-NNN", "STEP PLAN STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*IMPLEMENT STEP-"), "IMPLEMENT STEP-NNN", "STEP IMPLEMENT STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*REVIEW STEP-"), "REVIEW STEP-NNN", "STEP REVIEW STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*FIX STEP-"), "FIX STEP-NNN", "STEP FIX STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*RUN STEP-"), "RUN STEP-NNN", "STEP RUN STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*AUDIT STEP-"), "AUDIT STEP-NNN", "STEP AUDIT STEP-NNN"),
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
        except UnicodeDecodeError:
            continue
        for spec, match in find_deprecated_commands(text):
            line = text.count("\n", 0, match.start()) + 1
            source_line = text.splitlines()[line - 1] if text.splitlines() else ""
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


def project_live_document_paths(root: Path) -> list[Path]:
    """Вернуть active project-owned docs, где command syntax должен быть текущим.

    Immutable/history-oriented records намеренно не входят в scope:
    planning/reviews, planning/audits, planning/releases,
    planning/harness-updates, planning/skill-searches и docs/adr.
    """
    paths = [
        root / "README.md",
        root / "docs/PROJECT.md",
        root / "docs/architecture.md",
        root / "docs/OPEN_QUESTIONS.md",
        root / "planning/PLAN.md",
        root / "planning/STATUS.md",
    ]
    paths.extend(sorted((root / "docs/requirements").glob("*.md")))
    paths.extend(sorted((root / "planning/tasks").glob("STEP-*.md")))
    return paths
