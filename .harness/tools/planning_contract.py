#!/usr/bin/env python3
"""Детерминированные проверки planning contract и fingerprint контекста STEP.

Модуль намеренно не пытается заменить semantic review модели. Его задача —
дешёво и fail-closed ловить те противоречия и stale-state, которые можно
доказать статически: отсутствующие REQ/ADR/dependencies, циклы зависимостей,
OPEN questions у Ready-плана и изменение upstream contracts после planning.

Используется и локальным validator, и Execution Status. Только stdlib.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

STEP_ID_RE = re.compile(r"STEP-\d{3,}")
REQ_ID_RE = re.compile(r"REQ-\d{3}")
ADR_ID_RE = re.compile(r"ADR-\d{3}")
STEP_STATUSES = {
    "Запланировано",
    "В работе",
    "Выполнено",
    "Заблокировано",
    "Отменено",
    "Заменено",
}
STEP_TYPES = {
    "IMPLEMENTATION",
    "BUGFIX",
    "REFACTOR",
    "RESEARCH",
    "ADR",
    "AUDIT",
    "REVIEW",
    "HARDENING",
    "DOCUMENTATION",
    "RELEASE",
}
UNRESOLVED_LINE_RE = re.compile(
    r"(?mi)^\s*(?:[-*]\s*)?(?:TBD|TODO|\?\?\?)\s*$"
)

CONTRACT_METADATA = ("Type", "Depends on")
CONTRACT_SECTIONS = (
    "Requirements",
    "ADR",
    "Risk flags",
    "Goal",
    "Context",
    "Scope",
    "Mutation policy",
    "Out of scope",
    "Acceptance criteria",
    "Verification",
    "Deliverables",
)
REQUIRED_TASK_METADATA = ("Статус", "Type", "Приоритет", "Фаза", "Depends on")
REQUIRED_TASK_SECTIONS = CONTRACT_SECTIONS + (
    "Implementation plan",
    "Evidence",
    "Review status",
    "Blocker / Failure reason",
)


# Нормализовать Markdown/текст перед hashing: CRLF и trailing whitespace не должны
# без причины инвалидировать plan, содержательные изменения — должны.
def normalize_text(value: str) -> str:
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


# Разобрать используемый Harness subset Markdown: metadata **Key:** value и ## sections.
def parse_markdown(text: str) -> tuple[dict[str, str], dict[str, str]]:
    metadata: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.replace("\r\n", "\n").split("\n"):
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip()
            sections.setdefault(current, [])
            continue
        meta = re.match(r"^\*\*([^*]+?):\*\*\s*(.*)$", line)
        if meta:
            metadata[meta.group(1).strip()] = meta.group(2).strip()
        if current is not None:
            sections[current].append(line)
    return metadata, {
        name: normalize_text("\n".join(lines))
        for name, lines in sections.items()
    }


# Прочитать простой scalar из двухуровневой секции manifest без YAML dependency.
# Manifest Harness использует стабильный mapping subset; сложный YAML здесь не нужен.
def manifest_scalar(
    root: Path,
    section: str,
    key: str,
    default: str | None = None,
) -> str | None:
    path = root / ".harness" / "manifest.yaml"
    if not path.is_file():
        return default
    text = path.read_text(encoding="utf-8")
    in_section = False
    for raw in text.splitlines():
        if re.fullmatch(rf"{re.escape(section)}:\s*(?:#.*)?", raw):
            in_section = True
            continue
        if in_section and raw and not raw.startswith((" ", "\t", "#")):
            break
        if in_section:
            match = re.match(rf"^  {re.escape(key)}:\s*([^#]+?)\s*(?:#.*)?$", raw)
            if match:
                return match.group(1).strip().strip("\"'")
    return default


# Вернуть manifest-driven path. Default оставлен только для bootstrap/legacy state,
# но canonical template всегда содержит соответствующий параметр.
def configured_path(
    root: Path,
    section: str,
    key: str,
    default: str,
) -> Path:
    value = manifest_scalar(root, section, key, default) or default
    return root / value


def task_directory(root: Path) -> Path:
    return configured_path(root, "protocol", "taskDirectory", "planning/tasks")


def review_directory(root: Path) -> Path:
    return configured_path(root, "protocol", "reviewDirectory", "planning/reviews")


def requirements_directory(root: Path) -> Path:
    return configured_path(root, "sources", "requirements", "docs/requirements")


def architecture_path(root: Path) -> Path:
    return configured_path(root, "sources", "architecture", "docs/architecture.md")


# Прочитать execution.maxFixReviewCycles без reasoning. Невалидное значение —
# protocol error, который должен остановить orchestration.
def max_fix_review_cycles(root: Path) -> int:
    raw = manifest_scalar(root, "execution", "maxFixReviewCycles")
    if raw is None or not re.fullmatch(r"[0-9]+", raw):
        raise ValueError("manifest execution.maxFixReviewCycles must be an integer from 1 to 5")
    value = int(raw)
    if not 1 <= value <= 5:
        raise ValueError("manifest execution.maxFixReviewCycles must be between 1 and 5")
    return value


# Разрешить STEP path через manifest, а не через hard-coded planning/tasks.
def task_path(root: Path, step_id: str) -> Path:
    if not STEP_ID_RE.fullmatch(step_id):
        raise ValueError(f"invalid STEP id: {step_id}")
    path = task_directory(root) / f"{step_id}.md"
    if not path.is_file():
        raise FileNotFoundError(f"task file not found: {path.relative_to(root)}")
    return path


def read_task(root: Path, step_id: str) -> dict[str, Any]:
    path = task_path(root, step_id)
    text = path.read_text(encoding="utf-8")
    metadata, sections = parse_markdown(text)
    return {
        "path": path,
        "text": text,
        "metadata": metadata,
        "sections": sections,
    }


# Только собственный contract STEP. Plan/Evidence/Review не входят, чтобы execution
# facts не инвалидировали plan сами по себе.
def task_contract_snapshot(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    return {
        "metadata": {key: task["metadata"].get(key, "") for key in CONTRACT_METADATA},
        "sections": {key: task["sections"].get(key, "") for key in CONTRACT_SECTIONS},
    }


def _ids(value: str, pattern: re.Pattern[str]) -> list[str]:
    return sorted(set(pattern.findall(value)))


# Найти ровно один canonical REQ-NNN-*.md. Дубликаты считаются ошибкой, а не
# случайным выбором первого файла.
def canonical_requirement_path(root: Path, req_id: str) -> Path:
    matches = sorted(requirements_directory(root).glob(f"{req_id}-*.md"))
    if len(matches) != 1:
        raise ValueError(
            f"{req_id}: expected exactly one canonical requirement file, found {len(matches)}"
        )
    return matches[0]


# ADR filename в проектах может содержать slug; canonical identity — prefix ADR-NNN.
def canonical_adr_path(root: Path, adr_id: str) -> Path:
    directory = root / "docs" / "adr"
    matches = sorted(directory.glob(f"{adr_id}*.md"))
    matches = [path for path in matches if path.name != "TEMPLATE.md"]
    if len(matches) != 1:
        raise ValueError(f"{adr_id}: expected exactly one ADR file, found {len(matches)}")
    return matches[0]


def dependency_ids(task: dict[str, Any]) -> list[str]:
    return _ids(task["metadata"].get("Depends on", ""), STEP_ID_RE)


def requirement_ids(task: dict[str, Any]) -> list[str]:
    return _ids(task["sections"].get("Requirements", ""), REQ_ID_RE)


def adr_ids(task: dict[str, Any]) -> list[str]:
    return _ids(task["sections"].get("ADR", ""), ADR_ID_RE)


# Сформировать transitive planning snapshot только из upstream contracts, которые
# действительно способны сделать сохранённый plan устаревшим.
def planning_context_snapshot(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)

    requirements: dict[str, str] = {}
    for req_id in requirement_ids(task):
        path = canonical_requirement_path(root, req_id)
        requirements[req_id] = normalize_text(path.read_text(encoding="utf-8"))

    adrs: dict[str, str] = {}
    for adr_id in adr_ids(task):
        path = canonical_adr_path(root, adr_id)
        adrs[adr_id] = normalize_text(path.read_text(encoding="utf-8"))

    dependencies: dict[str, Any] = {}
    for dependency_id in dependency_ids(task):
        dependencies[dependency_id] = task_contract_snapshot(root, dependency_id)

    architecture = architecture_path(root)
    architecture_text = (
        normalize_text(architecture.read_text(encoding="utf-8"))
        if architecture.is_file()
        else ""
    )

    return {
        "schema": 2,
        "step": task_contract_snapshot(root, step_id),
        "requirements": requirements,
        "adrs": adrs,
        "dependencies": dependencies,
        "architecture": {
            "path": architecture.relative_to(root).as_posix(),
            "content": architecture_text,
        },
    }


# Plan basis v2: изменение linked REQ/ADR/dependency contract/architecture делает
# Ready-план stale автоматически, без reasoning-модели.
def planning_context_basis(root: Path, step_id: str) -> str:
    encoded = json.dumps(
        planning_context_snapshot(root, step_id),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _plan_fields(task: dict[str, Any]) -> dict[str, str]:
    section = task["sections"].get("Implementation plan", "")
    fields, _ = parse_markdown(section)
    return fields


# Извлечь OPEN questions и их Affects из документированного line-oriented формата.
def open_question_affects(root: Path) -> list[dict[str, Any]]:
    path = root / "docs" / "OPEN_QUESTIONS.md"
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(
            r"^(?:#{1,6}\s+)?(OQ-\d{3})\s+—\s+(.+)$",
            raw.strip(),
        )
        if heading:
            if current:
                entries.append(current)
            current = {"id": heading.group(1), "status": None, "affects": set()}
            continue
        if current is None:
            continue
        status = re.match(
            r"^(?:\*\*)?Status:(?:\*\*)?\s*(OPEN|RESOLVED|DEFERRED)\s*$",
            raw.strip(),
        )
        if status:
            current["status"] = status.group(1)
            continue
        affects = re.match(
            r"^(?:\*\*)?Affects:(?:\*\*)?\s*(.+)$",
            raw.strip(),
        )
        if affects:
            current["affects"].update(STEP_ID_RE.findall(affects.group(1)))
            current["affects"].update(REQ_ID_RE.findall(affects.group(1)))
            current["affects"].update(ADR_ID_RE.findall(affects.group(1)))
    if current:
        entries.append(current)
    return entries


# Собрать дешёвые planning errors. Это structural/static слой; смысл требований
# и конфликт целей всё равно проверяет mandatory semantic gate модели.
def validate_planning_contracts(
    root: Path,
    *,
    warnings: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    directory = task_directory(root)
    if not directory.is_dir():
        return errors

    tasks: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("STEP-*.md")):
        match = re.fullmatch(r"(STEP-\d{3,})\.md", path.name)
        if not match:
            errors.append(f"planning: invalid STEP filename: {path.relative_to(root)}")
            continue
        step_id = match.group(1)
        task = read_task(root, step_id)
        tasks[step_id] = task

        first_nonempty = next(
            (line.strip() for line in task["text"].splitlines() if line.strip()),
            "",
        )
        h1 = re.fullmatch(r"# (STEP-\d{3,}) — .+", first_nonempty)
        if h1 is None:
            errors.append(
                f"planning: {step_id} must start with '# {step_id} — <title>'"
            )
        elif h1.group(1) != step_id:
            errors.append(
                f"planning: filename/H1 ID mismatch for {step_id}: {h1.group(1)}"
            )

        for field in REQUIRED_TASK_METADATA:
            if not task["metadata"].get(field, "").strip():
                errors.append(f"planning: {step_id} missing metadata '{field}'")

        step_status = task["metadata"].get("Статус", "")
        if step_status and step_status not in STEP_STATUSES:
            errors.append(f"planning: {step_id} invalid Статус: {step_status}")
        step_type = task["metadata"].get("Type", "")
        if step_type and step_type not in STEP_TYPES:
            errors.append(f"planning: {step_id} invalid Type: {step_type}")

        for section in REQUIRED_TASK_SECTIONS:
            if section not in task["sections"]:
                errors.append(f"planning: {step_id} missing section '## {section}'")

        for dep_id in dependency_ids(task):
            if dep_id == step_id:
                errors.append(f"planning: {step_id} depends on itself")
            elif not (directory / f"{dep_id}.md").is_file():
                errors.append(f"planning: {step_id} dependency not found: {dep_id}")

        for req_id in requirement_ids(task):
            try:
                canonical_requirement_path(root, req_id)
            except ValueError as exc:
                errors.append(f"planning: {step_id}: {exc}")

        for adr_id in adr_ids(task):
            try:
                canonical_adr_path(root, adr_id)
            except ValueError as exc:
                errors.append(f"planning: {step_id}: {exc}")

        fields = _plan_fields(task)
        required_plan_fields = ("Plan status", "Plan revision", "Plan basis", "Planned at")
        for field in required_plan_fields:
            if field not in fields:
                errors.append(f"planning: {step_id} missing Implementation plan field '{field}'")

        plan_status = fields.get("Plan status", "")
        if plan_status not in {"Not planned", "Ready"}:
            errors.append(
                f"planning: {step_id} invalid Plan status: {plan_status or '<empty>'}"
            )

        if plan_status == "Ready":
            if task["metadata"].get("Фаза") == "TBD":
                errors.append(f"planning: {step_id} Ready plan has unresolved Phase=TBD")
            for section_name in (
                "Goal",
                "Scope",
                "Mutation policy",
                "Acceptance criteria",
                "Verification",
                "Deliverables",
            ):
                if UNRESOLVED_LINE_RE.search(task["sections"].get(section_name, "")):
                    errors.append(
                        f"planning: {step_id} Ready plan contains unresolved placeholder "
                        f"in '{section_name}'"
                    )

            # Ready означает executable contract. Hard dependencies уже должны
            # быть закрыты, а linked ADR — действительно Accepted.
            for dep_id in dependency_ids(task):
                dependency = tasks.get(dep_id)
                if dependency is None:
                    try:
                        dependency = read_task(root, dep_id)
                    except (OSError, ValueError, FileNotFoundError):
                        dependency = None
                if dependency is not None and dependency["metadata"].get("Статус") != "Выполнено":
                    errors.append(
                        f"planning: {step_id} Ready plan has incomplete dependency {dep_id}"
                    )

            for adr_id in adr_ids(task):
                try:
                    adr_path = canonical_adr_path(root, adr_id)
                    adr_metadata, _ = parse_markdown(
                        adr_path.read_text(encoding="utf-8")
                    )
                    if adr_metadata.get("Status") != "Accepted":
                        errors.append(
                            f"planning: {step_id} Ready plan references non-Accepted {adr_id}"
                        )
                except (OSError, ValueError, FileNotFoundError):
                    # Missing/ambiguous ADR уже добавлен отдельной structural check.
                    pass

            stored = fields.get("Plan basis", "")
            revision = fields.get("Plan revision", "")
            planned_at = fields.get("Planned at", "")
            if not re.fullmatch(r"[1-9][0-9]*", revision):
                errors.append(f"planning: {step_id} Ready plan must have positive Plan revision")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", stored):
                errors.append(f"planning: {step_id} Ready plan has invalid Plan basis format")
            if not planned_at or planned_at == "—":
                errors.append(f"planning: {step_id} Ready plan must have Planned at timestamp")
            try:
                current = planning_context_basis(root, step_id)
            except (OSError, ValueError, FileNotFoundError) as exc:
                errors.append(f"planning: {step_id} cannot compute Ready Plan basis: {exc}")
            else:
                if stored != current:
                    message = (
                        f"planning: {step_id} Ready plan is stale: "
                        "Plan basis does not match upstream context"
                    )
                    # Stale plan — execution precondition, а не повреждение repo.
                    # Resolver всё равно не разрешит IMPLEMENT без fresh PLAN.
                    # Глобальный validator сообщает drift warning, чтобы Harness
                    # update/другие независимые операции не требовали массового
                    # перепланирования всех будущих STEP.
                    if warnings is None:
                        errors.append(message)
                    else:
                        warnings.append(message)

    # Dependency graph cycle check.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str, chain: list[str]) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            start = chain.index(step_id) if step_id in chain else 0
            cycle = chain[start:] + [step_id]
            errors.append("planning: dependency cycle: " + " -> ".join(cycle))
            return
        visiting.add(step_id)
        chain.append(step_id)
        for dep_id in dependency_ids(tasks[step_id]):
            if dep_id in tasks:
                visit(dep_id, chain)
        chain.pop()
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in sorted(tasks):
        visit(step_id, [])

    # OPEN_QUESTIONS — часть blocking contract. Malformed entry нельзя
    # молча проигнорировать, иначе static gate можно обойти случайным форматированием.
    all_questions = open_question_affects(root)
    seen_questions: set[str] = set()
    for question in all_questions:
        question_id = question["id"]
        if question_id in seen_questions:
            errors.append(f"planning: duplicate Open Question ID: {question_id}")
        seen_questions.add(question_id)
        if question.get("status") not in {"OPEN", "RESOLVED", "DEFERRED"}:
            errors.append(f"planning: {question_id} missing or invalid Status")
        if not question.get("affects"):
            errors.append(f"planning: {question_id} missing Affects references")

    # Ready plan не может обходить явно OPEN вопрос, который влияет на сам STEP
    # или на linked REQ/ADR этого STEP.
    open_questions = [item for item in all_questions if item.get("status") == "OPEN"]
    for step_id, task in tasks.items():
        fields = _plan_fields(task)
        if fields.get("Plan status") != "Ready":
            continue
        relevant = {step_id, *requirement_ids(task), *adr_ids(task)}
        for question in open_questions:
            if relevant.intersection(question["affects"]):
                errors.append(
                    f"planning: {step_id} Ready plan is blocked by {question['id']} (OPEN)"
                )

    return errors
