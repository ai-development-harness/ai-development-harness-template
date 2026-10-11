# Portable Resume: Git-backed Handoff Contract (проектирование #300)

> Статус: **проектируемый контракт**, а не уже доступная возможность.
> Реализация `HARNESS RESUME` в текущем Harness остаётся local-only до #301.
> Parent: #298. Depends on #299.

## Почему нельзя синхронизировать execution-status.json

Текущий `.harness/local/execution/execution-status.json` — clone-local operational
state. Он содержит действующую invocation, counters, executionId, progress,
native runtime context и ограниченные side-effect checkpoints. Этот файл,
verification proofs, .harness/.execution-checkpoint-known, locks и update journal
не следует помещать в Git.

В новом Git clone нельзя доказать, что чужой процесс завершился, только по
строке `current.status=running` или по перенесённому executionId.

## Источники истины

- `task_directory()` из `manifest.protocol.taskDirectory` определяет STEP.
- `planning_context_basis()`, `plan_content_hash()` и matching planning
  review определяют актуальность Ready-плана.
- `step_completion_proof()`, immutable REVIEW и Verification определяют,
  что действительно завершено.
- CTS + Execution Status + Intent Resume и Side-effect Recovery определяют,
  какие действия можно запускать и продолжать.

**Handoff не добавляет новый PASS/DONE validator и не заменяет ни один из
этих механизмов.** Он даёт только переносимый набор проверяемых фактов
и подсказку, какой canonical workflow исследовать в другом clone.

## Proposed project-owned storage

Первоначальный вариант без новой manifest key:

```text
<parent of configured protocol.taskDirectory>/
  handoffs/
    STEP-NNN.json
```

Например при `protocol.taskDirectory: work/tasks` проектный файл находится
в `work/handoffs/STEP-017.json`. Default `planning/tasks` даёт
`planning/handoffs/STEP-017.json`.

Область должна быть project-owned и Git-tracked; не размещать эти файлы
в `.harness/local/`, Harness update-owned `.harness/docs/**` или
runtime adapter configuration. Коллизии с пользовательскими файлами и
символические ссылки — BLOCKED. Точное расположение/схему закрепит код
и его негативные regressions, а не это описание само по себе.

## Proposed allowlisted schema v1

Пример **формата проектирования**, не готовый совместимый JSON:

```json
{
  "schemaVersion": 1,
  "kind": "portable-step-handoff",
  "stepId": "STEP-017",
  "source": {
    "gitHeadBeforeHandoff": "<40-or-64-hex>",
    "branch": "feat/search",
    "taskIndexObject": "<40-or-64-hex>"
  },
  "facts": {
    "stepStatus": "in_progress",
    "planningContextBasis": "sha256:...",
    "planContentHash": "sha256:...",
    "planStatus": "ready"
  }
}
```

Запрещены неизвестные/пользовательские поля, absolute paths, raw model output,
account data, tokens, secrets, provider session handles, full transcripts,
and synthetic `verified=true` or `reviewPassed=true`.

Документ не хранит current executionId или состояние side-effect attempts.
Поле `source.gitHeadBeforeHandoff` **намеренно** ссылается на коммит до
добавления самого handoff-файла: иначе получится самоссылочная hash-зависимость.

## Publication boundary

1. Все product/STEP изменения должны быть в Git, `git status` чистый.
2. Writer проверяет canonical links и fingerprints по текущему рабочему
   дереву и Git index; записывает только handoff-файл.
3. Пользователь публикует файл через обычный `GIT CHECK → COMMIT → PUSH`.
   Writer **не** stage-ит, не создаёт commit и не обращается к сети.
4. В другом clone после `pull` validator доказывает:
   - handoff взят из отслеживаемого файла, а не из ignored/untracked path;
   - source commit является проверяемым предком текущего HEAD;
   - branch identity согласована и repository не находится в неоднозначном
     dirty/detached/diverged состоянии;
   - canonical STEP и его Git index object/semantic fingerprints совпадают;
   - schema/canonical path/version доказаны.
5. Только после этих проверок #301 решает, как восстановить **новую локальную**
   invocation. Старый executionId, native session и Verified PASS не импортируются.

Переименование ветки, rebase, force-push, changed task, modified contract,
lost marker в уже существующем clone и несовпадающие handoff files не
разрешают silent recovery.

## Current vs portable verification

Producer-bound Verification proof в `.harness/local/verification-proofs/`
остаётся локальным. Его отсутствие в ноутбуке не может трактоваться
как PASS только потому, что STEP Evidence был закоммичен. Потребуется
обычная Verification либо отдельный будущий доказуемый provenance contract,
не поддельный импорт текущего local proof.

## Two-clone safety

Базовая synthetic матрица использует local bare remote: desktop подготовил
handoff, commit+push; laptop fetch/pull; оба видят одинаковые project facts,
но разные local Execution Status. Также нужны stale REQ/ADR/PLAN, invalid
schema, changed Git HEAD, concurrent publisher, missing reviewed report,
dirty or ignored handoff, symlink/path traversal.

## Граница текущего этапа

До реализации writer и validator этот документ не меняет поведение Harness.
`HARNESS RESUME` остаётся существующей командой для local executions;
read-only `repository-recovery.py` из #299 даёт только кандидатов. Ни
экспорт, ни импорт, ни реплей опасных операций не выполняются автоматически.
