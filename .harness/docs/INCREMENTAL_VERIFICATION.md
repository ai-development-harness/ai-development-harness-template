# Инкрементальная STEP Verification (#367)

## Назначение и граница доверия

Canonical Verification остаётся обязательным перед завершением `STEP IMPLEMENT` /
`STEP FIX` и перед независимым `STEP REVIEW`. Опциональный режим
`incremental` формирует **новый** producer-bound Evidence PASS для текущего
subject: часть команд запускается сейчас, а сохранённые PASS используются
только при доказанно неизменных входах. Старому aggregate PASS новый subject
hash **никогда** не присваивается задним числом.

**Без явной project-owned карты влияния режим всегда `full`.** Карта является
утверждением проекта о полноте зависимостей, которое должен проверить
независимый planning reviewer. Core умеет проверять её форму, точное
соответствие Verification/Acceptance, изменённые Git paths и их fingerprints,
но не способен доказать полноту произвольных зависимостей по glob-шаблонам.
Если проект не может обосновать карту, он не должен её подключать.

## Подключение

В configured `.harness/manifest.yaml` проекта укажи необязательную секцию:

```yaml
verification:
  impactMap: docs/verification/impact-map.json
```

Путь project-owned, обязан быть внутри репозитория. Имя файла не зашито в Core.
Пример для STEP, у которого две отдельные `- command:` проверки:

```json
{
  "schemaVersion": 1,
  "steps": {
    "STEP-017": {
      "checks": [
        {
          "id": "ui",
          "command": "npm run test:ui",
          "inputs": ["src/ui/**", "tests/ui/**", "src/shared/**"],
          "dependsOn": [],
          "acceptance": ["Кнопка доступна с клавиатуры и имеет доступное имя."],
          "reusable": true
        },
        {
          "id": "backend",
          "command": "npm run test:backend",
          "inputs": ["src/backend/**", "tests/backend/**"],
          "dependsOn": [],
          "acceptance": ["Контракт API не регрессировал."],
          "reusable": true
        }
      ],
      "infrastructure": [
        "package.json",
        "package-lock.json",
        "nx.json",
        "tsconfig.json",
        "tools/test/**",
        "docs/verification/**"
      ]
    }
  }
}
```

Все `command` должны в точности совпадать с командами `## Verification`
данного STEP, без пропусков и дубликатов. `acceptance` указывает буквальный
текст соответствующих пунктов `## Acceptance criteria`; объединение всех
`acceptance` обязано покрывать каждый пункт. `dependsOn` содержит ID других
проверок: при изменении входов предшествующей проверки повторяются все её
зависимые проверки. Циклы и неизвестные ID недопустимы.

`inputs` включают **все** существенные исходники, тесты, конфигурацию,
генерируемые входы и общие зависимости этой проверки. Если изменение может
затронуть несколько проверок, путь должен присутствовать во всех
соответствующих inputs или эффект должен быть передан через `dependsOn`.
Пути без соответствия карте не считаются «безопасными»: выбирается полный
прогон. `infrastructure` содержит общие настройки тестирования, lockfile,
инструментарий и адаптер; их изменение заставляет повторить весь контракт.
`reusable: false` принудительно выполняет проверку при каждом запуске.

Если STEP содержит только одну непрозрачную команду `npm test`, это одна
проверяемая обязанность. Её нельзя заменить произвольным одним тестовым
файлом. Для гранулярности проект должен **заранее** разделить собственный
STEP Verification на доказанно эквивалентные отдельные команды/группы либо
использовать проектный тестовый адаптер с проверенной полнотой покрытия.
Harness v1 не утверждает автоматически, что произвольный набор подкоманд
эквивалентен монолитному `npm test`.

## Жизненный цикл

1. Первый полный PASS запускает все команды и создаёт обычный generated
   Evidence и producer-bound proof. После его записи Core сохраняет отдельный
   Git tree snapshot фактического tracked/staged/unstaged/non-ignored untracked
   состояния, hash карты, context/contract, runtime tool identity и результаты
   каждого check. Изменение `HEAD` при неизменных файлах само по себе не
   отменяет content proof.
2. В следующем прогоне Core сравнивает **накопленный** diff с исходным полным
   tree, проверяет покрытие каждого изменённого пути и для каждой группы
   сравнивает текущее содержимое её inputs с состоянием последнего PASS.
   Неизменённые группы переиспользуются, затронутые и их dependents
   выполняются. После нескольких исправлений исходный baseline не сдвигается.
3. `verify-selected.py` по-прежнему возвращает
   `completionProof=false`. Однако его PASS может быть включён в новый
   aggregate proof **без повторного запуска** при той же exact subject
   content identity, context, карте, окружении и одобренной выборке.
4. Manual/product observations должны быть представлены и проверены заново
   на актуальном subject; Core не считает неизменность Git файлов
   доказательством актуальности внешнего или ручного наблюдения.
5. Dispatcher сохраняет новый Evidence через canonical writer. Его CAS,
   проверка refs/subject/context, локальный Verification proof и
   `completion-gate.py` работают как раньше. В Evidence фиксируются
   `Verification mode`, provenance каждой команды, число выполненных /
   переиспользованных проверок и причина возврата к полному запуску.

Выполнить **всё** независимо от карты можно явно:

```bash
python3 .harness/tools/verify-step.py STEP-017 --full
```

При dispatcher completion допустим явный `details.fullVerification=true`.
Это не отменяет manual/product подтверждения.

## Безопасные возвраты к полному прогону

- Нет карты, исходного полного PASS, локального checkpoint или пригодного
  Git tree; policy/map повреждены, нет точного покрытия изменённых путей.
- Изменились Acceptance/REQ/ADR/plan, команда/timeout, map, общий
  инфраструктурный вход, environment или идентичность инструментов.
- Любой risk flag: `security-sensitive`, `data-migration`,
  `external-integration`, `destructive`, `release-critical`.
- Предыдущий Evidence не подтверждается canonical producer proof.
  FAIL конкретной проверки никогда не переиспользуется как PASS.
- Изменение subject во время исполнения, попытка теста изменить Git refs
  или repository, сбой Evidence CAS: прежнее fail-closed поведение.
- `manual`/`product` не подтверждены для текущего запуска: итог
  `MANUAL_REQUIRED` или `FAIL`, не `PASS`.

Измерения `executedCount`/`reusedCount` сообщают **число команд**, а
`durationMs` каждого результата показывает время фактического исполнения
либо исходного PASS; `targetedReusedCount` выделяется отдельно. Это не
доказательство сокращения времени без сравнительного полного прогона.

## Исправление дефекта после REVIEW PASS

Нельзя подделывать прошлый FAIL, переписывать immutable REVIEW или снова
переводить completed STEP в `in_progress`. После зафиксированного
завершения нужно создать **новый связанный corrective STEP** через обычные
`STEP ADD / PLAN / IMPLEMENT / REVIEW` с фактическим наблюдением,
воспроизведением и необходимыми проверками. Объём нового STEP определяется
его собственным Acceptance; проверка исходной большой подсистемы не
наследуется автоматически. Пока STEP ещё выполняется, локальные исправления
внутри его scope могут пользоваться механизмом, описанным выше.

Отдельный автоматизированный перенос baseline/coverage **между completed
STEP и новым corrective STEP**, а также автоматическое разложение произвольного
монолитного test command требуют самостоятельного строгого контракта; текущая
реализация не выдаёт такие возможности за завершённые.

## Local state и безопасность

- `.harness/local/verification-incremental/STEP-NNN.json` — versioned
  `schemaVersion=1`, owner: canonical Evidence writer, запись под
  `execution_state_lock`, сохранение только после producer-bound PASS.
  Содержит исходный полный Git tree и последний PASS каждой группы.
- `.harness/local/verification-incremental/STEP-NNN.targeted.json` —
  необязательный PASS `verify-selected`, сохраняется под тем же lock,
  допускается к reuse только после повторной проверки exact subject/inputs.
- Данные clone-local, в Git не входят. Утрата, несовместимость версии,
  истечение жизни Git tree после GC или удаление файла → обычный полный
  Verification. Snapshot нельзя принимать вместо исходников или
  пользовательских secret files. Очистка безопасна в любой момент за счёт
  полного fallback; повторная запись PASS заменяет прежнее состояние.
- Два параллельных producer-а не могут опубликовать разные состояния без
  проверки canonical subject CAS. Это оптимизация, а не trusted remote cache.

## Проверки

```bash
python3 .harness/tools/verification-incremental-self-test.py
python3 .harness/tools/verification-self-test.py
python3 .harness/tools/verification-selective-self-test.py
python3 .harness/tools/run-self-tests.py
python3 .harness/tools/validate.py --mode ci
```
