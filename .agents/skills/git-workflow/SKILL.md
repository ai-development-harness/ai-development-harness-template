---
name: git-workflow
description: Safe repository Git workflow for GIT CHECK, GIT COMMIT, GIT PUSH, GIT PR and GIT SYNC using project policy and deterministic integrity checks.
---
# git-workflow

Используй для `GIT CHECK`, `GIT COMMIT`, `GIT PUSH`, `GIT PR`, `GIT SYNC` и сегментов валидной Git-цепочки вроде `GIT CHECK > COMMIT > PUSH > PR`.

## Общие правила

1. Прочитай `.harness/git-policy.toml`.
2. До mutation изучи `git status --short --branch`, staged/unstaged diff и untracked files.
3. Запусти `python3 .harness/tools/validate.py --mode commit` (для read-only check тоже допустимо).
4. Никогда не выполняй `git reset --hard`, `git clean -fd`, force-push, automatic merge/rebase или amend без явного запроса пользователя.
5. Не включай unrelated changes. При нескольких независимых логических изменениях останови GIT COMMIT и предложи разбиение.
6. Секреты/local brief/generated мусор не должны попадать в index/commit.
7. Язык commit message бери из `.harness/manifest.yaml` → `language.commitMessages`; не используй отдельный скрытый default.
8. STEP/REQ/ADR traceability не обязательна для подтверждённого micro-change/PROJECT QUICK FIX. Если diff без STEP меняет behavior/API/data/security/architecture/dependencies — GIT COMMIT должен остановиться и предложить `STEP ADD:`.

## GIT CHECK

Read-only. Покажи branch, upstream/ahead-behind, staged/unstaged/untracked, policy, suspicious files, Harness validation, вероятный commit type/scope и blockers. Ничего не stage/commit/push.

## GIT COMMIT

1. Определи фактический logical change по diff; optional `GIT COMMIT: <hint>` — только подсказка, diff является источником истины.
2. Определи Conventional Commit type/scope.
3. Если текущая ветка protected и policy=`auto-create`, до commit создай `<prefix>/<slug>`. Для первого commit пустого repo допускается protected branch, если policy разрешает.
4. Stage согласно `stage_mode`:
   - `staged-only` — не добавлять ничего;
   - `tracked-only` — только изменённые tracked files;
   - `all-safe` — только проверенный набор относящихся к change tracked/untracked files; не использовать бездумный `git add .`.
5. Повторно проверь staged diff и safety.
6. Сформируй подробное сообщение по `.gitmessage` и `.harness/git-policy.toml`.
7. Выполни commit. GIT COMMIT никогда не делает push.
8. Верни hash, branch, subject, files, verification и следующую рекомендуемую команду.

## GIT PUSH

1. Выполни Harness validation, затем `git fetch <remote>` если policy требует.
2. Проверь upstream/divergence. При remote-ahead и policy=`block` остановись.
3. Protected branch push разрешён только policy; initial push может иметь отдельное исключение.
4. Push без force; при первом push установить upstream, если разрешено.
5. После успешного push применить `pull_request.after_push`:
   - `never` — завершить;
   - `ask` — предложить `GIT PR`;
   - `create-if-missing` — проверить существующий PR и создать при отсутствии.
6. Для GitHub предпочитать `gh`; если он недоступен/не авторизован, не выдумывать успех.

## PR

1. Требует опубликованную non-protected branch (если provider policy не говорит иначе).
2. Не создавать дубликат, если `reuse_existing=true`.
3. Заголовок должен отражать основное изменение; body — `.github/pull_request_template.md`, заполненный фактическими STEP/REQ/ADR, verification, risks и review.
4. Создать draft/non-draft согласно config.
5. Вернуть URL или конкретный blocker.

## GIT SYNC

1. Выполнить fetch.
2. Показать ahead/behind/diverged.
3. В `mode=report` ничего больше не менять.
4. В `mode=ff-only` разрешён только safe fast-forward чистой рабочей копии.
5. Никогда автоматически не merge/rebase конфликтующую историю.
