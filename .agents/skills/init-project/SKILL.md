---
name: init-project
description: Bootstrap a new repository from PROJECT_BRIEF.local.md into a durable project knowledge base and initial roadmap.
---
# init-project

Используй для `INIT PROJECT`.

1. Прочитай `.project/manifest.yaml`, включая `language`; если initialized=true, остановись и предложи `RECONCILE PROJECT`. После общих repository instructions также прочитай `AGENTS.local.md`, если он существует.
2. Прочитай `PROJECT_BRIEF.local.md`; если файла нет, сообщи точную команду копирования example.
3. Изучи предоставленные референсы настолько, насколько они доступны. Не подменяй недоступный источник общими знаниями без явной пометки.
4. Создавай project documentation на языке `language.documentation`. Создай `docs/PROJECT.md`, REQ, минимальный architecture baseline, OPEN_QUESTIONS и продуктовый `docs/GLOSSARY.md` по необходимости. Термины Harness не дублируй: они определены в `docs/harness/GLOSSARY.md`.
5. ADR создавай только для реальных устойчивых решений; неопределённость не превращай в Accepted ADR.
6. Построй roadmap по dependencies и создай полноценные STEP-файлы.
7. Обеспечь traceability REQ↔STEP↔ADR.
8. Обнови только generated project block `README.md`, generated `PROJECT-CONTEXT` block `AGENTS.md` и manifest. Статические ссылки Harness в README не переписывай.
   README project block после INIT должен оставаться кратким: `# <Project Name>`, 1–2 абзаца описания проекта, текущая стадия/следующая рекомендуемая команда и ссылки на `docs/PROJECT.md`, requirements, architecture и roadmap. Не возвращай в README длинную инструкцию Harness — она находится в `docs/harness/`.
9. Выполни consistency audit: уникальность IDs, valid links, dependency cycles, REQ coverage.
10. Сохрани `.github/workflows/harness-integrity.yml` как baseline Harness CI. Если стек уже определён достаточно точно, product-specific CI проектируй отдельным STEP/документом; не выдумывай команды сборки до появления реального tooling.
11. Не создавай production code.
12. Финальный отчёт: созданные артефакты, unresolved questions, agent profile recommendation, следующий STEP/команда.
