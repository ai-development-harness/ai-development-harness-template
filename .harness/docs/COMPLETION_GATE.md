# Completion / Convergence Gate

`STEP REVIEW` и completion отвечают на разные вопросы:

- **REVIEW**: есть ли material defect в inspected implementation/revision;
- **COMPLETION**: покрыты ли все in-scope Acceptance obligations свежим evidence и можно ли закрыть STEP;
- **RECONCILE**: не разошёлся ли repository-wide фактический state с canonical contracts.

REVIEW PASS сам по себе не переводит STEP в `completed`.

## Pipeline

```text
REVIEW PASS
→ deterministic completion precheck
→ semantic Acceptance coverage
→ PASS: existing completion proof + status=completed
→ FAIL: existing FIX loop
→ BLOCKED: stop current RUN
```

Нового lifecycle/CTS state нет.

## Deterministic precheck

```bash
python3 .harness/tools/completion-gate.py STEP-024 --json
```

Precheck выполняется до semantic convergence judgement и проверяет:

- наличие machine-discoverable Acceptance criteria;
- generated Verification freshness/status;
- current Ready planning/contract prerequisites.

Contract/freshness gap => BLOCKED.

## Semantic coverage payload

Для REVIEW PASS reviewer передаёт дополнительное поле `completion`:

```json
{
  "disposition": "pass",
  "coverage": [
    {
      "criterion": "User can save the record.",
      "status": "covered",
      "evidence": ["test_save PASS"]
    }
  ],
  "findings": [],
  "rationale": "All in-scope acceptance obligations are proven."
}
```

`disposition`:

- `pass`: каждый exact Acceptance criterion покрыт evidence;
- `fix`: отсутствующая работа находится внутри утверждённого scope — existing FIX loop;
- `blocked`: проблема в contract/prerequisite — текущий RUN останавливается.

Gate запрещает придумывать out-of-scope obligations: coverage criterion обязан буквально принадлежать `## Acceptance criteria`.

Immutable REVIEW report не переписывается после completion verdict. PROJECT STATE показывает `review_pass_completion_pending`, когда REVIEW уже PASS, но STEP ещё не закрыт.
