# Архитектурное решение: Verification после высокорискового FIX (#382)

Дата: 2026-11-05. Статус: принято для реализации upstream-контракта #382.
Это решение Harness Core, а не ADR неинициализированного product-проекта.
Дополняет [INCREMENTAL_VERIFICATION.md](INCREMENTAL_VERIFICATION.md): запрет
high-risk reuse сохраняется за пределами описанного исключения.

## Контекст и проблема

Полный первый PASS и риск STEP не определяют влияние следующего исправления.
Нужен проверяемый opt-in для незавершённого STEP, без удаления risk flags,
подмены старого PASS или обхода Completion Gate и независимых reviewers.

## Решение

Project-owned запись STEP в impact map может содержать `highRiskFix`:
`riskChecks` сопоставляет каждый исключающий risk flag непустому списку
родительских check ID; `externalState` явно классифицирует каждую проверку
как `none` или `always-run`; `maxAgeSeconds` ограничивает возраст полного
baseline. В первой версии внешний mutable state всегда проверяется заново.
Critical checks исполняются exact командами, включая монолит, если он указан.

Весь файл policy входит в planning context opt-in STEP. Изменение карты
требует нового независимого planning PASS и нового полного Verification.
До первого использования нужны квалифицированный полный producer-bound PASS,
активная canonical `STEP FIX`, schema-valid REVIEW FAIL с findings и точный
pre-FIX Git tree. Core закрепляет bytes FIX baseline в producer proof.
Результат и baseline сохраняют эту связь после incremental PASS.

Каждый finding инвалидирует все checks, inputs которых покрывают его location;
неизвестный location означает full fallback. Зависимости распространяются
транзитивно, включая группы. Проверки findings, riskChecks и внешнего state
не могут заменяться targeted cache. Полноту карты и finding-to-check связи
проверяют planning reviewer и независимый FIX reviewer; Core не выводит её
из размера patch или расширения файла.

Checkpoint сохраняет исходные полный proof и Evidence, накопленный tree и
последний PASS checks. Последующие FIX не сдвигают полный baseline; новая
canonical full Verification начинает новый baseline. Неизменность контракта,
environment/toolchain, map и инфраструктуры проверяется прежним механизмом.
Повреждение/потеря любого необходимого proof, устаревание или изменение
subject во время исполнения закрываются full fallback либо stale blocker.

## Альтернативы

- Снять ранний risk guard: недостаточно, теряется связь с FIX и findings.
- Оставить только полный режим: безопасно, но не различает UI-тест и shared input.
- Разрешить cross-STEP reuse или external-state attestations: расширяет
  trust boundary, отложено. High-risk source cache по-прежнему запрещён.

## Последствия, безопасность и совместимость

Без opt-in поведение прежнее. IMPLEMENT, post-PASS observations, completed STEP,
первый прогон и неподтверждённый FIX не получают исключения. `--full` сохраняется.
Manual/product observations, Semantic Blast Radius, exact execution consumers,
security/tests reviewers, producer CAS и Completion Gate не ослабляются.
Local state остаётся optional clone-local cache, не защищённым от процесса,
который одновременно переписывает все локальные proofs и project artifacts.
Старые checkpoints без нового full provenance требуют переквалификации;
миграция исторических reports и новых persistent каталогов не нужна.


## Уточнение recovery после FAIL, 2026-11-05

[Независимый комментарий к PR #383](https://github.com/ai-development-harness/ai-development-harness-template/pull/383#issuecomment-6653920670)
подтвердил потерю capture pin при замене/удалении result proof после FAIL.
Fresh full PASS восстанавливал результаты, но completion повторял full из-за
утраченного provenance. Receipt capture отделён от расходуемого result proof:
`verification-proofs/STEP-NNN.fix.json`, schemaVersion=1. Только capture owner
после успешного CAS canonical PASS выдаёт STEP/execution/exact-bytes binding.
Writer читает его для текущего unchanged capture и переносит pin в новый full
PASS; не создаёт receipt после правок. FAIL по-прежнему инвалидирует результаты,
receipt не разрешает reuse сам по себе. Invalid present receipt не маскируется
legacy fallback; отсутствие допускает лишь действующий прежний PASS pin.
Это recovery текущей границы доверия, без нового namespace и без ослабления
полноты Verification. Lifecycle и migration: [MAINTENANCE.md](MAINTENANCE.md).
