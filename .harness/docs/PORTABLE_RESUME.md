# Portable Resume: Git-backed Handoff и безопасное восстановление (#300–#301)

> `--write` и `--check` публикуют и проверяют Git-backed handoff. `HARNESS RESUME` теперь допускает строго ограниченный переносимый вход: **новый локальный STEP PLAN**, но не replay IMPLEMENT/REVIEW/FIX.
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

## Project-owned storage

Расположение определяется без новой manifest key:

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
символические ссылки — BLOCKED. Точное расположение определяет `.harness/tools/portable_handoff.py` через
`harness_config.task_directory()`, а не независимый registry.

## Strict allowlisted schema v1

Сокращённый пример поддерживаемого JSON (хеши здесь условные):

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

1. Все product/STEP изменения должны быть в Git, `git status` чистый; STEP должен иметь статус `in_progress`.
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
5. `HARNESS RESUME` сначала выбирает штатное локальное продолжение. Лишь в новом clone без локальной истории и с единственным полностью проверенным кандидатом начинается **новый локальный STEP PLAN** (новый executionId). Старый executionId, native session и Verified PASS не импортируются.

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

## Команды подготовки и проверки

В уже инициализированном Harness-проекте с опубликованными изменениями STEP:

```bash
python3 .harness/tools/portable-handoff.py --write --step STEP-017 --json
# Изучить дифф; затем штатно GIT CHECK → COMMIT → PUSH.
```

На ноутбуке после `git pull`:

```bash
python3 .harness/tools/portable-handoff.py --check --step STEP-017 --json
```

`PASS/HANDOFF_WRITTEN_NOT_PUBLISHED` означает лишь, что JSON создан в
рабочем дереве. Пока файл не закоммичен, переносимого checkpoint нет.
`PASS/HANDOFF_PROVEN_NOT_EXECUTION` означает только успешную проверку
provenance и сохранённых смысловых отпечатков, а **не успешный REVIEW,
Verification или выполнение команды**. В обоих случаях возвращаются
`safeToResume=false`, `nextCommand=null`; запись локального состояния
Harness отсутствует.

### Результаты и ограничения

| Результат | Значение |
| --- | --- |
| `REPOSITORY_NOT_PUBLISHABLE` | Проект не инициализирован, Git dirty или нет подходящего STEP |
| `HANDOFF_COLLISION` | Файл уже существует, но его схема недоказуема |
| `HANDOFF_NOT_PUBLISHED` | Handoff ещё не закоммичен |
| `HANDOFF_BRANCH_CHANGED` | Ветка текущего клона не соответствует исходной |
| `HANDOFF_SOURCE_UNREACHABLE` | Исходный commit не входит в текущую историю |
| `HANDOFF_STEP_CHANGED` | Git index object STEP отличается от опубликованного |
| `HANDOFF_CONTRACT_STALE` | Изменился смысловой контракт STEP/REQ/ADR/плана |
| `HANDOFF_SCHEMA_INVALID` | Некорректная версия или дополнительное поле, включая provider secret/session metadata |

Конфликтующий проектный файл не перезаписывается без schema проверки и
compare-before-replace. Механический инструмент не выполняет
`git add/commit/push`, не требует конкретного runtime и не читает
`.harness/local/**`. На другом клоне производные локальные подтверждения
Verification отсутствуют и не могут быть подменены handoff.

## Граница текущего этапа

**#301: ограниченное переносимое продолжение.** При наличии local resumable execution она всегда имеет приоритет. Повреждённый/утраченный local checkpoint и имеющаяся local history не могут быть обойдены portable fallback. Если в чистом клоне есть ровно один Git-published handoff с актуальным Ready plan и matching independent planning review, `HARNESS RESUME` создаёт **новую локальную STEP PLAN invocation** через штатный dispatcher/CTS. Это повторная смысловая проверка контракта, а не утверждение о выполненном IMPLEMENT.

Если есть несколько in_progress STEP, изменённый Git/контракт, неподтверждённый план, конфликтующий handoff или любое сомнение — BLOCKED. Нельзя автоматически повторять Git COMMIT/PUSH/PR, UPDATE и другие side effects. Модель и её session handle в checkpoint не входят. Для работы после PLAN агент должен проверить опубликованный код, фактические доказательства и заново выполнить необходимые локальные Verification gates.

**Ограничение:** Git-handoff v1 не фиксирует завершённую фазу или exclusive lease между двумя активными компьютерами. Он не даёт права автоматически продолжать IMPLEMENT/FIX/REVIEW и не обеспечивает распределённую блокировку. Полная проверка двух клонов, races и negative matrix — отдельный обязательный этап #302.

### Граница локальной истории (ревью #301)

Для переносимого запуска недостаточно пустого списка `executions`: даже
полностью компактированный `execution-status.json` остаётся доказательством
предыдущей работы в этом clone. `HARNESS RESUME` сохраняет привычный
`NO_RESUMABLE_EXECUTION` для local-only состояния без доступного продолжения.
Второй gate внутри `start_execution` под межпроцессной блокировкой ещё раз
проверяет отсутствие checkpoint перед созданием нового локального STEP PLAN.
Если за время диагностики Git-handoff устарел либо другой процесс уже начал
локальное выполнение, переносимый запуск блокируется; существующее состояние
не сбрасывается. Эти гарантии проверяются отдельным двухклоновым тестом
`portable-resume-self-test.py` с настоящим Git и публичным dispatcher.

### Откуда берётся SUCCESS после portable re-plan

Git уже содержит `Ready` и прежний `PLAN-REVIEW`. Они подтверждают только
состояние **до** новой локальной invocation. Когда portable `HARNESS RESUME`
запускает `STEP PLAN`, Execution Status сохраняет `plan.revision` и путь
`plan.reviewed_report` до semantic работы. Старый review не может закрыть новую
execution ни через crash recovery, ни по сообщению модели `SUCCESS`.

Для успешного завершения нужны **новая revision** плана и **новый
независимый immutable planning-review**, подтверждённые штатным
`latest_matching_planning_review`. Нет нового proof —
`PORTABLE_PLAN_RECHECK_REQUIRED`, локальное выполнение остаётся незавершённым.
Это не новый источник истины: используются canonical STEP + PLAN review.

## Команды UI и dispatcher

`harness-ux.py resume --json` возвращает выбранное продолжение без записи новой execution. Реальное выполнение через `harness-dispatch.py start --command "HARNESS RESUME"` запускает новую локальную STEP PLAN только после проверки переносимого handoff. Публикацию в Git команды восстановления не выполняют.
