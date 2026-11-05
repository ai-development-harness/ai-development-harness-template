# Проверка реализации #382

Дата: 2026-11-05. Источник задачи: [issue #382](https://github.com/ai-development-harness/ai-development-harness-template/issues/382).
Это сводка выполненных проверок рабочего дерева, не canonical STEP REVIEW
и не подтверждение опубликованного релиза.

## Что реализовано

Project-owned `highRiskFix` opt-in разрешает incremental canonical Verification
только в активном FIX незавершённого высокорискового STEP после REVIEW FAIL.
Policy включена в independent planning basis и Context Contract; полный первый
PASS, exact critical/external execution, producer-bound checkpoint, накопленный
Git baseline и независимые completion/review gates сохраняются.

Решение и контракт: [HIGH_RISK_FIX_VERIFICATION.md](HIGH_RISK_FIX_VERIFICATION.md),
[INCREMENTAL_VERIFICATION.md](INCREMENTAL_VERIFICATION.md).
REQ/ADR/STEP неинициализированного product-проекта не создавались.

## Исполненные проверки

Все перечисленные команды завершились с кодом 0:

| Проверка | Результат |
| --- | --- |
| `python3 .harness/tools/validate.py --mode ci`, Python 3.12.3 | PASS |
| `python3 .harness/tools/run-self-tests.py`, Python 3.12.3 | PASS, 84 self-tests |
| Те же validator и полный self-test runner, Python 3.11.18 | PASS, 84 self-tests |
| `python3 .harness/tools/verification-high-risk-self-test.py --canary ../release-canary` | PASS, lifecycle completed |
| `git diff --check` | PASS |

Дополнительный Python 3.11 установлен только для проверки в disposable `/tmp`.
Полные terminal logs не являются versioned artifact; таблица фиксирует
команды, exit code и наблюдённые результаты, без реконструкции terminal quotes.

## Проверка canary

Runner клонировал чистый локальный `release-canary/main` и исполнял candidate
Python modules Core с config и историей копии. Исходный canary после проверки
остаётся чистым. Установленный Harness canary не заменялся; updater/promotion
не выполнялись.

В копии создан отдельный тестовый STEP и обычными writers выполнен lifecycle:
полный PASS → schema-valid REVIEW FAIL → FIX → incremental PASS → повторный
FAIL/FIX → независимый по роли delta REVIEW → completion. Тестовые semantic
payloads синтетические и явно маркированы; они проверяют executable protocol,
а не выдают реальное product acceptance от имени независимого человека.

Наблюдённые результаты финального сценария:

- Test-only FIX: реально исполнены 6 команд — UI, lint, types, auth,
  migration-safety и отдельный external-state provisioning; backend и
  независимый migration suite переиспользованы — 2 команды.
- Shared validator: исполнены все 8 команд, reuse отсутствует.
- Исходные `security-sensitive` и `data-migration` сохранены.
- Dispatcher завершил финальный FIX в incremental режиме; скрытого full перед
  REVIEW/completion не появилось.
- Квалифицированные группы проверены отдельным regression fixture: UI group
  fresh, независимая backend group reused, dependent parent fresh; critical
  parent и все его группы исполнены exact. Повтор без изменения файлов
  по-прежнему инвалидирует finding и dependent obligations.

В suite также проверены dirty/staged/untracked additions, deletion/rename,
interruption/resume, конкурентная запись, cache/FIX pin tampering, новый
targeted FAIL, смена env/policy, неизвестный input и истечение baseline.
Существующие регрессии high-risk cross-STEP source, targeted producer binding
и exact-command consumers остались зелёными.

## Независимое ревью

Отдельные read-only architecture, implementation, security и tests roles
завершились PASS. Architecture review выявил два integration gap — fallback
обычной повреждённой карты и новый planning component namespace; исправления
включены в итоговую реализацию.

Tests review выявил отсутствие standalone external-state regression и нового
теста в Windows groups. Оба исправлены. Повторный mutation experiment удалял
обработку external-state obligations в памяти: новый тест обнаружил пропуск
реального provisioning execution и упал на ожидаемом assertion.
Security review отдельно проверил 7 одиночных повреждений producer/cache/FIX
state: каждый случай приводил к full fallback. Потеря capture/proof/cache
также независимо проверена implementation reviewer.

## Пределы подтверждения

При первоначальной локальной проверке нативный Windows runner и GitHub CI
ещё не запускались.
Новый self-test добавлен в Windows `execution`, состав набора увеличен до 17,
`windows-ci-self-test.py` прошёл на Linux. Это подтверждает регистрацию и
границы runner, но не заменяет нативное выполнение Windows.

Не заявляются измеренная экономия времени, release qualification или принятие
новой версии в canary. Commit/push/PR не выполнялись. Следующий разрешённый
read-only Git gate: `GIT CHECK`.


## Исправление первого Windows CI в PR #383

Первый [Windows execution job](https://github.com/ai-development-harness/ai-development-harness-template/actions/runs/41996883805/job/127142134776)
обнаружил отказ до high-risk FIX: resolver возвращал полный путь `runneradmin`,
а parser REVIEW строил относительный путь от короткого alias `RUNNER~1`.
Получался `FIX_BASELINE_BLOCKED`; остальные независимые jobs прошли,
итоговый Windows check отражал отказ группы execution.

Parser теперь использует существующий `planning_contract._repo_relative`,
нормализующий обе стороны. В high-risk self-test добавлен lexical alias root:
он воспроизвёл тот же `ValueError` на Linux до исправления, после исправления
полный lifecycle прошёл. Отдельные `review-findings-self-test.py`,
`incremental-review-self-test.py` и validator также прошли. Полномочия reuse,
producer proofs и требования к выполнению проверок не менялись.
Нативное подтверждение исправления относится к следующему GitHub CI PR.


## Recovery после Verification FAIL: замечание P2

[Комментарий пользователя](https://github.com/ai-development-harness/ai-development-harness-template/pull/383#issuecomment-6653920670)
выявил скрытый полный прогон: FAIL расходовал result proof вместе с capture pin;
после нового full PASS completion не мог доказать прежний capture и повторял
все команды. Регрессия, проверяющая режим completion и сохранение нового full
baseline, воспроизвела это до исправления.

В существующем proof namespace добавлен отдельный producer-bound capture
receipt. Только pre-FIX owner выдаёт его после CAS canonical PASS; writer
не создаёт receipt после правок. FAIL по-прежнему инвалидирует результаты,
а восстановить pin можно при новом full PASS на прежнем unchanged capture.
Regression покрывает canonical и targeted FAIL, восстановление и отсутствие
повторного full, invalid/foreign receipt, legacy absence и сохранность capture.
