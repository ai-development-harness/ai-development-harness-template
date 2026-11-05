# Проверка исправления #387

Дата: 2026-11-05. Задача: [issue #387](https://github.com/ai-development-harness/ai-development-harness-template/issues/387).
Scope: lifecycle synthetic fixtures и настройка их собственной Verification
policy. Production parsing, project-owned impact map и completion gates не изменены.

## Исправление

`isolate_project_artifacts()` сбрасывает унаследованную секцию `verification`
вместе с host STEP и PROJECT INIT lifecycle. Project-owned файлы карты могут
оставаться в полной копии как инертные данные: runtime больше не получает
ссылку на чужую policy. Minimal/protocol-only копия также не требует исходный
map file, которого в ней может не быть.

`set_fixture_verification()` заменяет один top-level YAML узел через общий
parser/serializer, сохраняет остальные значения и обнаруживает duplicate keys
до записи. Существующие tests с собственной картой и новый manual continuation
regression используют эту идемпотентную boundary вместо append второй секции.
Копируется effective candidate checkout, включая текущие изменения runtime;
pristine upstream для обхода дефекта не используется.

## Воспроизведение до исправления

В изолированной копии прежнего runtime подготовлен initialized host с двумя
STEP, canonical REQ и валидной картой `policies/custom/host-map.json`.
`python3 .harness/tools/validate.py --mode ci` завершился exit code 0 / PASS.
`python3 .harness/tools/verification-environment-self-test.py` затем завершился
exit code 1: `VERIFICATION_CONTRACT_INVALID`, duplicate YAML key `verification`.
Это summary наблюдённых фактов, а не восстановленная terminal quote.

## Проверки после исправления

- `python3 .harness/tools/self-test-fixture-self-test.py` — exit code 0 / PASS.
  Regression создаёт initialized host с двумя STEP и project-owned policy;
  проверяет обычный и нестандартный пути карты, full/protocol-only копии,
  отсутствие inherited config и STEP, идемпотентную замену секции в середине
  manifest и безопасный отказ при duplicate keys. Исходная и собственная
  fixture карты проходят реальные full/incremental Verification gates.
  Host contents, file modes и Git index сохраняются побайтово.
- Полный discoverable `python3 -u .harness/tools/run-self-tests.py` из initialized
  host с включённой `verification.impactMap` и `manualContinuation`:
  **Python 3.11.18 — 85/85 PASS, exit code 0**;
  **Python 3.13.18 — 85/85 PASS, exit code 0**.
  Каждый host использовал нестандартный путь `policies/custom/host-map.json`.
  После каждого полного прогона все исходные tracked files, modes и Git index
  сравнены с pre-run snapshot: изменений нет.
- Все семь tests из issue остались включены и прошли на обеих версиях:
  command-dispatch, late-defect, repository-hardening, verification-environment,
  verification-high-risk, verification-incremental, verification-review-regressions.
  Manual continuation regression #385 также прошёл на обеих версиях.
- `python3 .harness/tools/validate.py --mode manual`, AST syntax check восьми
  изменённых Python modules и `git diff --check` — PASS.

Полные наборы выполнялись на Linux в disposable host roots; отдельные Python
интерпретаторы установлены в temporary directory, системный runtime не заменён.
Product integration suites и нативный Windows для этой fixture-регрессии не
запускались. Workflow gates и discoverable tests не отключались.
