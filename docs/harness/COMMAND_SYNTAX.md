# Синтаксис команд Harness

Этот документ определяет каноническую форму пользовательских команд и сокращённый синтаксис последовательного выполнения.

## 1. Каноническая форма

Команда начинается с явной области:

```text
<DOMAIN> <OPERATION...> [TARGET] [: free-form input]
```

`OPERATION` может состоять из нескольких слов, например в `HARNESS UPDATE CHECK` или `PROJECT QUICK FIX`.

Канонические области:

- `PROJECT` — lifecycle и maintenance конкретного проекта;
- `STEP` — работа с STEP;
- `SKILL` — поиск, установка и создание repository skills;
- `GITHUB` — GitHub collaboration artifacts;
- `RELEASE` — release gates;
- `HARNESS` — lifecycle самого Harness;
- `GIT` — локальная история и публикация Git.

Примеры:

```text
PROJECT INIT
PROJECT STATUS
PROJECT RECONCILE
PROJECT QUICK FIX: исправить опечатку в README

STEP ADD: добавить экспорт отчётов
STEP NEXT
STEP PLAN STEP-024
STEP IMPLEMENT STEP-024
STEP REVIEW STEP-024
STEP FIX STEP-024
STEP RUN STEP-024
STEP AUDIT STEP-024

SKILL FIND: accessibility review
SKILL INSTALL: #2
SKILL CREATE: проверка миграций

GITHUB GENERATE TEMPLATES

RELEASE CHECK

HARNESS UPDATE CHECK
HARNESS UPDATE CHECK TO v0.4.0
HARNESS UPDATE APPLY
HARNESS UPDATE APPLY TO v0.4.0

GIT CHECK
GIT COMMIT
GIT COMMIT: обновить документацию Harness
GIT PUSH
GIT PR
GIT SYNC
```

Старые ненеймспейсные формы не являются каноническими alias. Если пользователь хочет локальный alias, он задаётся явно в `AGENTS.local.md`.

## 2. Цепочки

Оператор `>` как отдельный token, окружённый пробелами, означает последовательное выполнение нескольких команд одной области:

```text
<FULL COMMAND> > <ACTION> > <ACTION>
```

Первый сегмент всегда содержит явный DOMAIN. Последующие сегменты могут не повторять тот же DOMAIN.

Примеры:

```text
GIT CHECK > COMMIT > PUSH > PR

STEP PLAN STEP-024 > IMPLEMENT > REVIEW

HARNESS UPDATE CHECK TO v0.4.0 > APPLY
```

Полные повторные формы той же области также допустимы, но сокращённая запись предпочтительнее:

```text
GIT CHECK > GIT COMMIT > GIT PUSH
```

эквивалентна:

```text
GIT CHECK > COMMIT > PUSH
```

## 3. Валидация до выполнения

Вся цепочка должна быть разобрана и проверена **до выполнения первого сегмента**.

Если цепочка синтаксически или семантически невалидна:

- ни один сегмент не выполняется;
- working tree / Git / Harness artifacts не меняются;
- пользователь получает конкретную причину.

Это предотвращает ситуацию, когда первая mutation уже произошла, а ошибка в последнем сегменте обнаружилась только после неё.

## 4. Наследование области

Внутри цепочки DOMAIN наследуется от первого сегмента. Для семейства `HARNESS UPDATE` также наследуется префикс `UPDATE`, поэтому `> APPLY` означает `HARNESS UPDATE APPLY`.

Например:

```text
GIT CHECK > COMMIT > PUSH > PR
```

означает:

```text
GIT CHECK
GIT COMMIT
GIT PUSH
GIT PR
```

Указание другого DOMAIN после `>` запрещено.

Невалидно:

```text
STEP RUN STEP-024 > GIT COMMIT
```

Для перехода между областями пользователь запускает отдельную команду/цепочку.

## 5. Наследование target

### STEP

После первого explicit STEP target он фиксируется для всей STEP-цепочки.

```text
STEP PLAN STEP-024 > IMPLEMENT > REVIEW
```

означает работу только с `STEP-024`.

Эквивалент:

```text
STEP PLAN STEP-024
STEP IMPLEMENT STEP-024
STEP REVIEW STEP-024
```

Если последующий сегмент указывает другой STEP, вся цепочка невалидна и ничего не выполняется.

### HARNESS UPDATE

Explicit target `TO <tag>` наследуется внутри update chain:

```text
HARNESS UPDATE CHECK TO v0.4.0 > APPLY
```

означает:

```text
HARNESS UPDATE CHECK TO v0.4.0
HARNESS UPDATE APPLY TO v0.4.0
```

Указание другого target в `APPLY` делает цепочку невалидной.

### GIT

Git-цепочка не имеет отдельного target; каждый сегмент работает с текущим repository/branch context согласно `.project/git-policy.toml`.

## 6. Разрешённые цепочки

Цепочки поддерживаются только там, где сокращение не скрывает обязательное пользовательское решение.

### GIT

В chain участвуют только фазы publication pipeline:

```text
GIT CHECK
GIT COMMIT
GIT PUSH
GIT PR
```

`GIT SYNC` остаётся самостоятельной командой.

Пример обычной публикации:

```text
GIT CHECK > COMMIT > PUSH > PR
```

### STEP

Для ручного управления стадиями допустимы:

```text
STEP PLAN STEP-NNN
STEP IMPLEMENT STEP-NNN
STEP REVIEW STEP-NNN
STEP FIX STEP-NNN
```

Пример:

```text
STEP PLAN STEP-024 > IMPLEMENT > REVIEW
```

`STEP RUN STEP-NNN` уже является orchestration-командой и не используется как сегмент цепочки.

`STEP AUDIT STEP-NNN` является самостоятельной audit-командой и не объединяется с mutation flow.

### HARNESS UPDATE

Поддерживается только безопасная пара:

```text
HARNESS UPDATE CHECK [TO <tag>] > APPLY
```

`APPLY` выполняется только после успешного matching CHECK для того же target и route.

### Не поддерживаются

Цепочки не используются для:

- `PROJECT` — lifecycle-команды должны оставаться явными;
- `SKILL` — после поиска выбор кандидата должен оставаться отдельным пользовательским решением;
- `GITHUB` — генерация templates является самостоятельной mutation;
- `RELEASE` — release check является самостоятельным gate.

## 7. Допустимый порядок операций

Same-domain chain не считается валидной только потому, что все её сегменты по отдельности являются существующими командами.

До первого выполнения Harness обязан проверить **структурный порядок операций**.

### GIT

Git-chain описывает только pipeline публикации:

```text
CHECK → COMMIT → PUSH → PR
```

Допустима последовательность, которая движется только вперёд по этому pipeline и не нарушает обязательные промежуточные зависимости.

Примеры:

```text
GIT CHECK > COMMIT
GIT CHECK > COMMIT > PUSH
GIT CHECK > COMMIT > PUSH > PR
GIT CHECK > PUSH
GIT CHECK > PUSH > PR
GIT CHECK > PR
GIT COMMIT > PUSH
GIT COMMIT > PUSH > PR
GIT PUSH > PR
```

`GIT CHECK > PUSH` допустима, если commit уже существует и текущий repository state позволяет push.
`GIT CHECK > PR` допустима, если ветка уже опубликована и удовлетворяет preconditions `GIT PR`.

После `GIT COMMIT` переход напрямую к `GIT PR` запрещён: новый локальный commit должен быть опубликован через `GIT PUSH`.

Нельзя двигаться назад, повторять уже пройденную фазу или выполнять публикацию после `PR`:

```text
GIT PR > COMMIT              # INVALID_CHAIN
GIT PUSH > COMMIT            # INVALID_CHAIN
GIT COMMIT > CHECK           # INVALID_CHAIN
GIT CHECK > COMMIT > CHECK   # INVALID_CHAIN
GIT COMMIT > PR              # INVALID_CHAIN
GIT PR > PUSH                # INVALID_CHAIN
```

Такая ошибка определяется **до первого сегмента**. Например `GIT PR > COMMIT` не создаёт и не ищет PR — вся цепочка отклоняется целиком.

`GIT SYNC` не является фазой publication pipeline и выполняется только как самостоятельная команда. Оно не используется внутри chain.

### STEP

Для ручного implementation flow допустимы переходы:

```text
PLAN → IMPLEMENT → REVIEW
REVIEW(FAIL) → FIX → REVIEW
```

Вход в цепочку разрешён с любой стадии, если preconditions этой стадии уже удовлетворены repository state.

Структурно допустимы, например:

```text
STEP PLAN STEP-024 > IMPLEMENT > REVIEW
STEP IMPLEMENT STEP-024 > REVIEW
STEP REVIEW STEP-024 > FIX > REVIEW
STEP FIX STEP-024 > REVIEW
```

`REVIEW > FIX` является **условным** переходом: `FIX` выполняется только если фактический verdict review = `FAIL`. При `PASS` или `BLOCKED` оставшиеся сегменты получают `NOT_EXECUTED`.

Обратные или пропускающие обязательную mutation стадии цепочки запрещены:

```text
STEP REVIEW STEP-024 > IMPLEMENT      # INVALID_CHAIN
STEP IMPLEMENT STEP-024 > PLAN       # INVALID_CHAIN
STEP PLAN STEP-024 > REVIEW          # INVALID_CHAIN
STEP FIX STEP-024 > IMPLEMENT        # INVALID_CHAIN
```

### HARNESS UPDATE

Единственная допустимая update-chain:

```text
HARNESS UPDATE CHECK [TO <tag>] > APPLY
```

`APPLY > CHECK`, повторный `CHECK`, повторный `APPLY` и любые другие порядки невалидны.

### Общий принцип

Chain validator должен различать:

- `INVALID_CHAIN` — структура/порядок невозможны; ничего не выполняется;
- `BLOCKED` — структура допустима, но runtime/repository precondition не выполнена;
- `NOT_EXECUTED` — сегмент структурно допустим, но до него не дошли из-за результата предыдущего сегмента.

## 8. Условие перехода к следующему сегменту

Следующий сегмент выполняется только если предыдущий:

1. завершился успешно;
2. не вернул `FAIL` / `BLOCKED`;
3. не требует отдельного пользовательского решения;
4. допускает следующий шаг своим protocol handoff.

При остановке оставшиеся сегменты получают состояние `NOT_EXECUTED`.

Пример:

```text
GIT CHECK > COMMIT > PUSH > PR
```

может завершиться так:

```text
✓ GIT CHECK
✓ GIT COMMIT
✗ GIT PUSH — BLOCKED: remote ahead
○ GIT PR — NOT_EXECUTED
```

## 9. Цепочка не является транзакцией

Успешно выполненные mutation не откатываются автоматически при ошибке следующего сегмента.

Например, если:

```text
GIT COMMIT
```

успешно создал commit, а `GIT PUSH` затем оказался BLOCKED, Harness сохраняет локальный commit и сообщает partial result.

Automatic rollback, reset, amend, merge/rebase или force push из chain semantics запрещены.

## 10. Safety boundary STEP → GIT

Harness намеренно не поддерживает:

```text
STEP RUN STEP-024 > GIT COMMIT > GIT PUSH
```

После работы над STEP пользователь получает возможность отдельно посмотреть diff/evidence/review и только затем запускает Git-команду или Git-цепочку:

```text
STEP RUN STEP-024
```

затем:

```text
GIT CHECK > COMMIT > PUSH > PR
```

Эта граница является частью protocol safety, а не ограничением parser implementation.
