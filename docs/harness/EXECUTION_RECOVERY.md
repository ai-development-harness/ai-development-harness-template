# Execution Recovery

Execution Recovery делает длительные Harness-команды устойчивыми к обрыву session/runtime, исчерпанию account limit, закрытию клиента и другим аварийным остановкам.

Он не заменяет Command Transition System (CTS):

~~~text
CTS
→ какой переход структурно разрешён?

Execution Recovery
→ на каком разрешённом переходе фактически остановилась работа?

Resolver
→ какую canonical command выполнить сейчас?
~~~

## Источники истины

Machine-readable recovery policy:

`.project/execution-recovery.json`

Local operational cursor:

`.project/local/execution/STEP-NNN.json`

Deterministic tools:

- `tools/harness/execution_recovery.py`
- `tools/harness/execution-state.py`
- `tools/harness/resolve-next-command.py`

Authority:

~~~text
canonical repository artifacts
        >
local execution cursor
~~~

Cursor не является product evidence и не коммитится. Удаление `.project/local/execution/` не делает проект некорректным: Harness восстанавливает максимум из durable artifacts, а недоказанную phase консервативно повторяет.

## Почему cursor нужен

PLAN и REVIEW имеют durable completion proof:

- PLAN — Ready plan с актуальным Plan basis;
- REVIEW — новый immutable review report;
- весь STEP — canonical status `Выполнено`.

IMPLEMENT/FIX нельзя надёжно признать завершёнными только по существующему diff или `Статус: В работе`. Поэтому они завершаются только explicit local completion-checkpoint после scope, verification и Evidence.

## Crash-safe запись

Cursor обновляется atomic replace:

~~~text
temporary file
→ flush
→ fsync
→ os.replace
~~~

После process crash должен остаться либо предыдущий валидный JSON, либо новый валидный JSON.

## Cursor lifecycle

Перед phase:

~~~bash
python3 tools/harness/execution-state.py begin STEP-001 \
  --command 'STEP IMPLEMENT STEP-001'
~~~

После доказанного handoff:

~~~bash
python3 tools/harness/execution-state.py complete STEP-001 \
  --command 'STEP IMPLEMENT STEP-001' \
  --result SUCCESS
~~~

Если session оборвалась между ними, cursor остаётся `IMPLEMENT / running` и resolver возвращает ту же command с `RESUME`.

## Deterministic resolver

~~~bash
python3 tools/harness/resolve-next-command.py --json STEP-001
~~~

Пример:

~~~json
{
  "status": "RESUME",
  "stepId": "STEP-001",
  "command": "STEP IMPLEMENT STEP-001",
  "reasonCode": "INTERRUPTED_IMPLEMENT"
}
~~~

Без STEP id resolver возвращает active/interrupted execution candidates. `STEP NEXT` обязан рассматривать их раньше старта нового STEP.

## PLAN и Plan basis

Task хранит:

~~~text
Plan status
Plan revision
Plan basis
Planned at
~~~

После сохранения plan:

~~~bash
python3 tools/harness/execution-state.py stamp-plan STEP-001
~~~

Plan basis — SHA-256 от нормализованного task contract:

- Type;
- Depends on;
- Requirements;
- ADR;
- Risk flags;
- Goal;
- Context;
- Scope;
- Mutation policy;
- Out of scope;
- Acceptance criteria;
- Verification;
- Deliverables.

Evidence, Review status, Blocker и сам Implementation plan в basis не входят.

Если current hash отличается от stored basis:

~~~text
PLAN_STALE
→ STEP PLAN STEP-NNN
~~~

Это определяется без LLM reasoning.

### Crash после PLAN

~~~text
STEP RUN STEP-001
  PLAN
    plan saved
    stamp-plan done
    ↯ session lost before local completion checkpoint
~~~

Valid Plan basis доказывает завершение PLAN, поэтому новая session начинает с `STEP IMPLEMENT STEP-001`.

## IMPLEMENT recovery

Если IMPLEMENT имеет running cursor без completion-checkpoint:

~~~text
RESUME
→ STEP IMPLEMENT STEP-NNN
~~~

Resume semantics:

1. проверить актуальный plan/basis;
2. изучить существующий diff/Evidence;
3. определить уже выполненную работу;
4. продолжить недостающее;
5. повторить необходимые verification;
6. записать Evidence;
7. только затем записать SUCCESS checkpoint.

Partial diff сам по себе не является completion proof.

## REVIEW recovery

При begin REVIEW cursor сохраняет `reviewReportBefore`.

Если session оборвалась, но после begin появился новый immutable review report, resolver восстанавливает verdict без повторного REVIEW.

- FAIL → `STEP FIX STEP-NNN`;
- BLOCKED → `BLOCKED`;
- PASS при незавершённом close/sync → `STEP RUN STEP-NNN` с `FINALIZE_AFTER_PASS`.

При FINALIZE_AFTER_PASS RUN не запускает PLAN/IMPLEMENT/REVIEW повторно.

## FIX recovery

При begin FIX cursor сохраняет latest FAIL report как `sourceReview`.

Если FIX оборвался без completion-checkpoint:

~~~text
RESUME
→ STEP FIX STEP-NNN
~~~

После FIX SUCCESS resolver переводит flow на свежий REVIEW только если completed FIX относится к latest FAIL report.

## FIX/REVIEW limit

Лимит берётся из `.project/manifest.yaml → execution.maxFixReviewCycles`.

Для восстановления после потери local cursor resolver использует immutable FAIL review history консервативно. При max=3:

~~~text
Review #0 FAIL → FIX #1 → Review #1
Review #1 FAIL → FIX #2 → Review #2
Review #2 FAIL → FIX #3 → Review #3
Review #3 FAIL → BLOCKED
~~~

То есть новый FIX не начинается, если он потребовал бы цикл N+1.

## STEP RUN как restart-safe macro

Deterministic coding recovery применяется к:

- IMPLEMENTATION;
- BUGFIX;
- REFACTOR;
- HARDENING.

Алгоритм:

~~~text
register root command
→ resolve-next-command
→ exact phase
→ begin checkpoint
→ execute phase
→ completion proof/checkpoint
→ resolve-next-command
→ ...
~~~

Повторный `STEP RUN STEP-NNN` после interruption является штатным resume entry point и не повторяет доказанно завершённые PLAN/REVIEW.

ADR/RESEARCH/AUDIT/REVIEW/DOCUMENTATION/RELEASE пока используют type-specific RUN semantics и не прогоняются через coding resolver.

## STEP NEXT

Перед обычным roadmap selection:

~~~bash
python3 tools/harness/resolve-next-command.py --json
~~~

Active/interrupted executions рассматриваются раньше нового STEP. Это не даёт новой session случайно начать STEP-002, если STEP-001 оборвался на IMPLEMENT.

## Result codes

- `NEXT` — предыдущая phase доказанно завершена;
- `RESUME` — нужно продолжить interrupted phase или завершить orchestration tail;
- `REPLAN` — task contract изменился и Plan basis устарел;
- `BLOCKED` — durable/runtime blocker или исчерпан FIX/REVIEW limit;
- `DONE` — STEP canonical completed;
- `NOT_APPLICABLE` — STEP Type использует type-specific RUN semantics.

## Failure philosophy

~~~text
completion proven
→ move forward

completion not proven
→ resume/retry same phase
~~~

Recovery может повторить часть анализа/verification, но не должен пропускать незавершённую mutation только ради экономии токенов.
