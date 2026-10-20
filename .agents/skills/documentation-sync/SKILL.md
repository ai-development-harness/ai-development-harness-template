---
name: documentation-sync
description: Synchronize documentation and traceability from verified implementation while preserving accepted product and architecture contracts as authoritative.
---
# documentation-sync

Обновляй только затронутые docs после подтверждённой реализации.

## Source hierarchy

- Фактические code/tests/evidence подтверждают **что реализовано**.
- Canonical REQ определяют **какое product/system behavior требуется**.
- Accepted ADR/architecture определяют **какие durable решения обязательны**.
- STEP/review/evidence определяют traceability и состояние конкретной работы.

Не «синхронизируй документацию под код», если реализация расходится с Accepted REQ/ADR. Такое расхождение — finding/corrective work либо отдельное решение об изменении contract, а не основание молча переписать requirement/ADR.

## Workflow

1. Все project paths бери из manifest.
2. Для owning STEP используй точный documentation delta из Ready plan: проверяй только configured architecture, project overview и непосредственно связанные subsystem docs. Не обходи весь репозиторий и не открывай отдельный documentation STEP ради обычного сопровождения собственной поставки. Независимый исторический drift вне scope оформляй как отдельную corrective работу.
3. Изменяй описательные current-state claims о **доказанной** готовности/отсутствии возможностей и текущих ограничениях. Не называй planned feature готовой до реализации; сохрани claims о соседних ещё не поставленных возможностях. Если delta отсутствует, не создавай фиктивных изменений.
4. Проверяй, что каждый изменяемый output разрешён Scope/Mutation policy и заявлен в Deliverables/Files; для изменяемых `architecture_refs` нужны `architecture_outputs`. Missing declaration → BLOCKED/fresh PLAN, не скрытая мутация frozen input.
5. Не придумывай API/behavior, которых нельзя доказать code/tests/evidence или accepted contract.
6. Обновляй relevant subsystem docs и разрешённую canonical traceability. Accepted ADR immutable; изменение durable decision оформляется через новый ADR.
7. Не редактируй PLAN/STATUS/requirements SPEC+STATUS/Open Questions index вручную.
8. Пересобери projections:
   ```bash
   python3 .harness/tools/sync-projections.py
   ```
9. Для механической части используй `docs` agent; semantic conflict между implementation и contract не поручай ему «исправить текстом».
