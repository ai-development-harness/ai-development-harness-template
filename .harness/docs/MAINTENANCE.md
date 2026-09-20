# Поддержка Harness

## Что относится к control plane Harness

Основное правило: internal implementation и human-readable core documentation собраны под `.harness/**`, но сам namespace не является единой ownership class. `.harness/docs/**` и `.harness/tools/**` относятся к core, `.harness/manifest.yaml` и `.harness/git-policy.toml` являются shared, а `.harness/local/**` — local-only operational state.

Отдельно снаружи остаются integration surfaces, потому что их расположение определяется runtime/repository conventions:

- `AGENTS.md` (кроме generated project blocks);
- `CLAUDE.md`, `.codex/`, baseline `.claude/`;
- core `.agents/skills/`;
- baseline `.github/` integration.

Colocated `TEMPLATE.md` рядом с REQ/ADR/STEP и другими project artifacts являются project-owned scaffolds. Они обязательны для структуры Harness, но updater не захватывает их ownership: legacy projects могли адаптировать эти файлы до появления текущей update-policy.

## Что относится к конкретному проекту

- generated blocks README/AGENTS;
- `docs/PROJECT.md`;
- requirements;
- ADR;
- architecture/subsystem docs;
- roadmap/tasks/reviews/audits;
- Harness update reports;
- product code/tests/config;
- project-native/third-party skills;
- project-specific runtime additions, отсутствующие в upstream allowlist.

## Правило обновлений

Не копируй новый Harness поверх проекта вручную.

Используй:

```text
HARNESS UPDATE CHECK
HARNESS UPDATE APPLY
```

Формальная модель ownership, BASE/OURS/THEIRS, legacy adoption и release lifecycle описана в [`UPDATES.md`](UPDATES.md).

`HARNESS UPDATE APPLY` — maintenance mutation, а не STEP. После неё не выполняются commit/push/PR автоматически: сначала inspect diff, затем обычный `GIT CHECK` → `GIT COMMIT`.

## Version и release

`.harness/manifest.yaml` разделяет два понятия:

- `harness.version` — поколение protocol/schema layer;
- `harness.release` — конкретный semver release.

Пока protocol generation совместимо, `harness.version` остаётся `"1"`, а поставки получают immutable tags `vMAJOR.MINOR.PATCH`.

Known BASE проекта фиксируется в `.harness/harness.lock.json`. Moving `main` не используется как update baseline.

`v0.4.2` — одноразовая compatibility boundary для переноса control plane из `.project/**` в `.harness/**`. Relocation выполняет updater старого layout до reload; после перехода `.harness/**` является единственным bootstrap namespace, а legacy `.project/local/**` сохраняется только как ignored transitional state.

Новые updater’ы читают moving `source.default_branch` только через canonical `.harness/harness-update-graph.json`. Для updater’ов `v0.4.0`/`v0.4.1` сохраняется отдельный замороженный `.project/harness-update-graph.json` как compatibility discovery endpoint до corrective landing release `v0.5.1`; unsafe legacy landing `v0.5.0` обходится. Endpoint не является active control plane и после перехода не используется. Файлы protocol layer для каждого hop по-прежнему читаются только из immutable tags.

## Ownership

`.harness/harness-update.toml` делит обновляемые пути на:

- `harness_owned` — локальная модификация блокирует silent overwrite;
- `shared` — 3-way merge;
- `marker_merge` — 3-way merge с сохранением generated project blocks.

Runtime tuning относится к `shared`: пользователь может менять model/effort в `.codex/` и tracked Claude adapter, не теряя настройки при обычном Harness update. Colocated project `TEMPLATE.md` updater не меняет.

Всё неизвестное считается project-owned и updater не меняет. Например project-specific `.claude/skills/**` не становится Harness-owned только потому, что находится внутри `.claude/`.

То же относится к локальным ignored artifacts внутри managed directory: `__pycache__/`, bytecode и другие ignored cache/build files не входят в ownership scope только из-за совпадения с glob. Updater классифицирует OURS через Git tracked state; untracked ignored paths пропускаются, untracked non-ignored collisions блокируют update.

## Legacy projects

Если проект создан до появления lock, безопасный BASE неизвестен. Updater не должен угадывать его по похожести файлов.

Legacy adoption разрешён только для явно известного release через `update-harness`: укажи конкретный immutable tag `vX.Y.Z`. При неизвестном baseline нужен ручной reconciliation.

## Project-specific skills

Добавляй отдельно. Универсальный `implement-step` не должен знать конкретный framework. Если technology skill нужен большинству задач проекта — зарегистрируй его в `.agents/skills/` и упомяни в generated project context/architecture docs.

`.agents/skills/` является runtime-neutral canonical location. Не создавай вторую tracked копию core Harness skill в `.claude/skills/` только ради Claude Code.

## Third-party skills

Не смешивай upstream skill upgrades с обычным Harness update. У каждого внешнего skill должен быть `UPSTREAM.md` и запись в `docs/skills/REGISTRY.md`. Обновление upstream требует повторного inspection; не делай silent auto-update.

## Самодокументируемые конфиги

Tracked YAML/TOML в `.harness/`, `.codex/` и baseline GitHub Actions должны оставаться читаемыми без перехода в отдельную справку. Каждый параметр обязан иметь рядом комментарий с назначением и примером. Harness Integrity проверяет это правило для patterns из `.harness/harness-policy.toml`.

Claude Code settings являются strict JSON и не допускают комментариев. Поэтому их назначение и defaults документируются в [`CLAUDE_CODE.md`](CLAUDE_CODE.md), а validator проверяет JSON structure и обязательные значения отдельно.

При добавлении нового YAML/TOML policy/config key одновременно:

1. объясни назначение;
2. перечисли допустимое поведение, если оно неочевидно;
3. приведи `Пример:` или `Example:`;
4. только после этого добавляй значение.
