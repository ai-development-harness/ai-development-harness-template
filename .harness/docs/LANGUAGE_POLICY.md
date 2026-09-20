# Языковая политика

Единый источник языковых настроек — `.harness/manifest.yaml` → `language`.

Настройки разделены, потому что проект может, например, вести документацию на русском, а test names или commit messages — на английском. Используются BCP 47 tags (`ru`, `en`, `pt-BR` и т.д.).

Поля:

- `default` — fallback;
- `agentResponses` — ответы агентов;
- `documentation` — PROJECT/REQ/ADR/STEP/reports;
- `commitMessages` — Git commits;
- `codeComments` — комментарии/doc-comments;
- `testNames` — человекочитаемые названия test cases;
- `fixtures` — sample/fixture content;
- `githubTemplates` — Issue/PR templates;
- `releaseNotes` — changelog/release notes.

## Что не переводится автоматически

Language policy не требует переводить:

- identifiers, class/function/variable names;
- API paths/JSON keys;
- package/framework/tool names;
- protocol keywords (`REQ`, `ADR`, `STEP`, `PASS`);
- данные, которые тестируют конкретную локаль.

При конфликте с доменной задачей фактический contract имеет приоритет: multilingual fixture для i18n-теста остаётся multilingual независимо от `language.fixtures`.
