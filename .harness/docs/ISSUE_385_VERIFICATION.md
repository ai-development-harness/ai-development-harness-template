# Проверка исправления #385

Дата: 2026-11-05. Scope: свежий `MANUAL_REQUIRED → PASS` той же execution;
изменение subject, high-risk FIX reuse и cross-STEP cache остаются отдельными
границами. Исходная задача: [issue #385](https://github.com/ai-development-harness/ai-development-harness-template/issues/385).

## Результат

Добавлен producer-bound checkpoint опубликованного автоматического этапа.
High-risk continuation требует project-owned `verification.manualContinuation`:
локальные результаты сохраняются, mutable external checks повторяются адресно.
Без достаточного proof действует полный fallback. Перед completion доступны
`verification.continuationPlan` и read-only CLI `--continuation-plan`.
Policy и ограничения описаны в [MANUAL_VERIFICATION_CONTINUATION.md](MANUAL_VERIFICATION_CONTINUATION.md).

## Выполненные проверки

Ниже summary команд, exit code 0 и наблюдаемых фактов; это не literal terminal log.

- `python3 .harness/tools/verification-manual-continuation-self-test.py` — PASS.
  Для каждого из пяти исключавших risk flags initialized synthetic fixture
  проходит Ready plan → canonical IMPLEMENT → MANUAL_REQUIRED → restart/preflight
  → manual payload → PASS. Обе локальные команды реально выполняются один раз.
  Сохраняются исходные duration/output observations; новый producer proof свежий.
  Отдельный сценарий проходит существующие REVIEW и STEP completion gates.
  External policy даёт счётчики `1/2`: повторяется только external команда.
  Corrupt checkpoint, state-changing observation и предыдущий factual FAIL
  через dispatcher требуют новых запусков. Preflight отдельно отвергает
  source/contract/policy/commands/timeout/environment/tool identity/execution
  drift, TTL expiry, отсутствующие/битые producer/checkpoint и доступный на ОС
  symlink. Подмена proof между selection и Evidence publication блокируется.
- `python3 .harness/tools/verification-self-test.py` — PASS: low-risk manual
  continuation, force-full, invalid commands, repository/ref mutations и CAS.
- `python3 .harness/tools/verification-incremental-self-test.py` — PASS:
  существующие incremental/composite/corrective reuse сценарии.
- `python3 .harness/tools/verification-high-risk-self-test.py` — PASS:
  прежний high-risk FIX lifecycle завершается; независимый backend PASS
  сохраняется, shared dependencies запускают обязательные проверки.
- `python3 .harness/tools/verification-environment-self-test.py` — PASS:
  изменение inherited environment не наследует прежний PASS.
- `python3 .harness/tools/verification-review-regressions-self-test.py` — PASS.
- `python3 .harness/tools/windows-ci-self-test.py` — PASS: новый regression
  зарегистрирован в существующей Windows execution группе.
- `python3 .harness/tools/validate.py --mode manual` — PASS.
- `git diff --check` и `python3 -m py_compile` изменённых Verification modules — PASS.

## Границы доказательства

Это локальные synthetic проверки orchestration на Linux. Нативный Windows
execution lane и реальные downstream build/install/database/browser suites
здесь не запускались. Synthetic REVIEW проверяет применение существующих
schema/proof gates; он не является независимым semantic review этого patch.
Release, установленный canary и опубликованный tag не обновлялись.

## Native Windows follow-up

Первый native CI выявил расхождение только `environmentBasis` при restart:
[диагностический check](https://github.com/ai-development-harness/ai-development-harness-template/actions/runs/42026756939/job/127242777683).
Причина в negative test: `patch.dict(os.environ)` выполнял bulk clear/update.
Windows CRT `_wputenv` удаляет empty-valued переменные из native environment,
тогда как Python mapping может ещё хранить их; дочерний процесс видел уже иной
набор входов. Guard корректно требовал повтор.

Negative test теперь меняет только новый временный ключ. Весь regression
запускается в отдельном процессе с явно заданной пустой переменной, поэтому
restart проверяет сохранность именно native environment. Основной runner,
TTL, producer/CAS и проверка полного окружения не ослаблены. Перед публикацией
этого исправления targeted manual/basic/environment suites прошли на Linux;
окончательный native результат хранится в checks обновлённого PR #386.

Семантика CRT: [Microsoft `_putenv` / `_wputenv`](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/putenv-wputenv).
