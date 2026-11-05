# Issue #389 — изоляция Verification и временные бюджеты CI

Проблема: [issue #389](https://github.com/ai-development-harness/ai-development-harness-template/issues/389).
Дата проверки: 2026-11-05. Статус: локальные Linux-проверки PASS; native Windows acceptance **не подтверждён**.

## Изменения

Общий scaffold `verification-self-test.py` использует `protocol_only=True`.
Все сценарии Verification, incremental, environment, manual-continuation,
high-risk и review-regressions сохраняют прежние assertions и выполняют
настоящие lifecycle/Git/evidence операции. Явный high-risk `--canary` сохраняет
полный clone переданного downstream и прежний порядок сценариев; этот путь
в данной проверке не запускался.

High-risk выводит ограниченные `[SCENARIO] high-risk/...` перед дорогими фазами.
Runner и механизм остановки дочерних процессов не изменены. Управляемый запуск
с лимитом 1 с вернул TIMEOUT и `lastScenario=high-risk/lifecycle/plan-and-baseline`;
это ожидаемая негативная проверка, а не успешный high-risk прогон.

Прежние 11 последовательных Windows execution-тестов разделены:

- `execution`: execution, reliable-orchestration-fault, operational-reports,
  operational-completion, operational-integration, local-cleanup;
- `verification`: verification, verification-environment;
- `incremental`: verification-incremental;
- `manual`: verification-manual-continuation;
- `high-risk`: verification-high-risk.

Вместе с прежними `update` и `resume` получаются семь независимых jobs.
Общий набор содержит те же 18 различных тестов. Финализатор требует success
всех семи jobs текущего запуска и отвергает failure/cancelled/skipped/missing.
Default per-test Windows timeout остаётся 900 с; внешний job timeout — 20 минут.
У одиночных дорогих suites остаются пять минут сверх per-test лимита для
checkout/setup/cleanup. Длительности составных групп требуют native проверки;
арифметика лимитов сама по себе не доказывает успешное завершение Windows.

## Воспроизведение и масштаб

Из checkout с исправлением, используя нужную версию Python:

```bash
python3.11 .harness/docs/evidence/issue-389/reproduce.py
python3.13 .harness/docs/evidence/issue-389/reproduce.py
```

Скрипт создаёт disposable initialized consumer с двумя STEP, project-owned
Verification policy и 1900 tracked product-файлами по 14000 байт. Проверяет
consumer через настоящий `validate.py --mode ci`, добавляет dirty installed
runtime и managed untracked файл, затем вызывает существующий bounded runner.
`python3` дочерних команд закреплён за тем же runtime. Коммиты создаются только
во временном consumer; исходный checkout не изменяется. JSON и полные логи
пишутся в системный временный каталог.

Фактический размер перед запуском тестов, включая установленный Harness:

- Python 3.11: 2370 файлов, 32091076 байт.
- Python 3.13: 2370 файлов, 31964913 байт.

Отдельная regression `verification_scale()` проверяет отсутствие product-файлов
в scaffold, сохранность installed dirty bytes, managed untracked и project skill,
удаление host Verification policy и неизменность исходного host вместе с Git index.
Проверка совместимости выявила необходимость собственного configured overview
у initialized test host; он теперь создаётся явно. Dynamic import fixture не
записывает `__pycache__` в host, чтобы проверка неизменности не ловила сам тест.

## Наблюдения Linux

Python 3.11.18: high-risk PASS за 50.097 с, запас до 120 с — 69.903 с.
Python 3.13.18: high-risk PASS за 63.095 с, запас до 120 с — 56.905 с.

Это по одному финальному наблюдению на версию, без retries, статистического
benchmark и утверждений о CI-оборудовании. Проверки разных версий выполнялись
одновременно. Captured machine results сохранены в `linux-3.11.json` и
`linux-3.13.json`; это реальные результаты runner, не реконструкция терминала.

Полный фактически выполненный целевой набор Linux/Python 3.13:

| Self-test | Результат | Секунды |
| --- | --- | ---: |
| execution-self-test.py | PASS | 6.785 |
| reliable-orchestration-fault-self-test.py | PASS | 9.004 |
| operational-reports-self-test.py | PASS | 2.382 |
| operational-completion-self-test.py | PASS | 1.634 |
| operational-integration-self-test.py | PASS | 6.480 |
| local-cleanup-self-test.py | PASS | 3.912 |
| verification-self-test.py | PASS | 10.930 |
| verification-environment-self-test.py | PASS | 4.574 |
| verification-incremental-self-test.py | PASS | 17.374 |
| verification-manual-continuation-self-test.py | PASS | 27.608 |
| verification-high-risk-self-test.py | PASS | 63.095 |
| self-test-fixture-self-test.py | PASS | 13.946 |
| windows-ci-self-test.py | PASS | 2.069 |
| run-self-tests-self-test.py | PASS | 2.176 |
| verification-review-regressions-self-test.py | PASS | 9.030 |

На Python 3.11 дополнительно прошла новая fixture regression. Локальный
`validate.py --mode ci` и `git diff --check` — PASS. `windows-ci-self-test`
проверяет CLI, состав групп, соответствие workflow, durations/exit codes,
отказы финализатора и сохранение TIMEOUT. `run-self-tests-self-test` подтверждает
очистку дочерних процессов. Полный discoverable suite не запускался.

## Оставшаяся проверка

Нужен запуск изменённого workflow на Windows 2025/Python 3.13: все 18 тестов,
включая прежние 11 execution-тестов, их native durations и финальный
`Validate Windows boundaries: PASS`. Нужны также Linux CI Python 3.11/3.13.
Локальные результаты не заменяют эти acceptance gates; issue не закрыт.

## Совместимость late-defect после первого CI

Первый [CI PR #390](https://github.com/ai-development-harness/ai-development-harness-template/actions/runs/42049931565)
обнаружил ещё одного потребителя scaffold: `late-defect-self-test.py` использовал
унаследованный `docs/architecture.md` как существующий evidence. Оба Linux jobs
завершили 84 из 85 тестов успешно; единственная ошибка — отсутствие этого файла.
High-risk прошёл за 27,974 с на Python 3.11 и 38,472 с на Python 3.13.

Теперь late-defect создаёт собственный evidence до исходного полного PASS.
Negative assertion изменения старого evidence после REVIEW и все остальные
проверки сохранены. Прямые запуски `late-defect-self-test.py` с согласованным PATH
на Python 3.11.18 и 3.13.18 завершились с exit code 0 / PASS; validator и
`git diff --check` — PASS. Эти факты записаны как summary локальных команд,
без реконструкции terminal output. Воспроизводимый набор дополнен late-defect.
Повторный CI проверяет исправленный consumer scaffold полным набором.
