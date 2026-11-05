# Продолжение Verification после MANUAL_REQUIRED (#385)

## Границы

`MANUAL_REQUIRED → PASS` завершает ручную часть **того же свежего автоматического
этапа**, с тем же subject и той же IMPLEMENT/FIX execution. Это доступно и при
`external-integration`, `security-sensitive`, `data-migration`, `destructive`,
`release-critical`, если проект явно описал обязательства ниже.

Это отдельный механизм от [high-risk FIX reuse](HIGH_RISK_FIX_VERIFICATION.md)
после настоящего REVIEW FAIL и от [cross-STEP reuse](INCREMENTAL_VERIFICATION.md)
в корректирующем STEP. Для manual continuation не нужны FAIL review, finding
invalidation или impact map. Он не переносит PASS на изменённый subject.

## Policy для high-risk STEP

В configured manifest проекта объяви exact команды данного STEP:

```yaml
verification:
  manualContinuation:
    STEP-017:
      readOnly: true
      localCommands:
        - "npm run test:unit"
        - "npm run build"
      repeatCommands:
        - "npm run test:external-api"
```

`localCommands` — проверки, чей результат определяется зафиксированным local
subject, окружением и инструментами. `repeatCommands` — проверки mutable
external state или любые проверки, которые нужно повторить после observations.
Оба списка вместе обязаны покрывать exact `- command:` entries без дубликатов.
Пустой список записывается `[]`. Общий risk flag сам не выбирает дорогой полный
повтор; repeat list определяет конкретные команды и возвращает причину
`MANUAL_CONTINUATION_EXTERNAL_STATE`.

`readOnly: true` — project-owned обязательство, что все manual/product
observations только наблюдают состояние и не меняют входы локальных проверок.
Если процедура меняет БД, удалённый сервис, ignored runtime state или другие
существенные входы, установи `readOnly: false`: прежний этап использовать нельзя,
будет полный прогон. Альтернатива для наблюдений, затрагивающих только внешние
проверки, — вынести **все** затронутые команды в `repeatCommands`, оставив
`readOnly: true` только относительно сохранённых локальных результатов.
Неполную декларацию нельзя считать доказанной лишь потому, что её принял parser.
Семантику декларации и полноту external-state obligations проверяет planning reviewer.

Отсутствующая/невалидная policy у high-risk STEP оставляет полный прогон с явной
причиной. Обычный low-risk STEP без policy сохраняет прежний режим: bounded
read-only manual continuation всех команд. Policy можно задать и ему.
Квалифицированные composite groups пока требуют полного повтора; manual
continuation не обходит их отдельные producer/coverage obligations.

## До дорогого completion

Первый `VERIFICATION_MANUAL_REQUIRED` возвращает `verification.continuationPlan`:
`executedChecks`, `reusedChecks`, `reasonCode`, producer и execution binding.
Это snapshot, который может устареть. Перед повторным completion можно получить
свежий read-only план без команд, записи Evidence или изменения execution:

```bash
python3 .harness/tools/verify-step.py STEP-017 --continuation-plan
```

Выполни только listed manual checks после получения реальных observations,
затем передай exact `check/status/observed` через dispatcher `details.manualVerification`.
Не прогнозируй manual PASS заранее. Если состояние изменилось, preflight назовёт
полный повтор и причину. `fullVerification: true` явно требует полный прогон
независимо от checkpoint. Сам preflight не является разрешением пропустить
повторную проверку актуальности в completion.

## Proof и безопасный fallback

Checkpoint создаётся после публикации producer-bound `MANUAL_REQUIRED` Evidence.
Его bytes отдельно закреплены в producer proof. Проверяются exact STEP,
единственная активная IMPLEMENT/FIX execution, subject revision, Verification
и semantic contract, policy, список команд, timeout, полное inherited environment,
identity executable (путь, metadata и содержимое), возраст не больше 30 минут
и исходные per-command PASS/exit code. Env values не сохраняются.
Повторные partial observations не продлевают исходный TTL локальных PASS.

Новый aggregate содержит ссылку на producer этапа и исходные command results;
старый aggregate не получает новый subject задним числом. Перед публикацией
повторно проверяются continuation proof и обычные subject/context/CAS gates.
После FAIL/PASS pending checkpoint удаляется. Missing/corrupt/symlink checkpoint,
потеря producer proof, смена execution/входов или истечение TTL требуют реального
повтора. Resume/restart читают тот же checkpoint с диска; chat memory не участвует.
Локальный proof защищает от ошибочного редактирования, а не от процесса, который
произвольно переписывает одновременно Evidence и всё operational state.

## Регрессии

`python3 .harness/tools/verification-manual-continuation-self-test.py` проверяет
все пять flags через canonical IMPLEMENT dispatcher с реальными счётчиками,
Ready plan, штатными writers, restart/preflight, producer/freshness gates,
адресным external повтором и отрицательными сценариями. Fixture не запускает
реальные downstream build/install/browser/database suites.
