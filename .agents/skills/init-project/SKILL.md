---
name: init-project
description: Bootstrap a new repository from PROJECT_BRIEF.local.md into a durable project knowledge base and initial roadmap.
---
# init-project

Используй для `PROJECT INIT`.

1. Прочитай `.harness/manifest.yaml`, включая `language`; если initialized=true, остановись и предложи `PROJECT RECONCILE`. После общих repository instructions также прочитай `AGENTS.local.md`, если он существует.
2. Прочитай `PROJECT_BRIEF.local.md`; если файла нет, сообщи точную команду копирования example.
3. Изучи предоставленные референсы настолько, насколько они доступны. Не подменяй недоступный источник общими знаниями без явной пометки.
4. Создай draft project knowledge base на языке `language.documentation`: `docs/PROJECT.md`, canonical REQ, минимальный architecture baseline, OPEN_QUESTIONS и продуктовый `docs/GLOSSARY.md` по необходимости. Каждый REQ создавай отдельным `docs/requirements/REQ-NNN-<slug>.md` по template; удали template-файл `REQ-001-template.md`, если он существует. В `SPEC.md` храни только projection/index REQ, lifecycle — только в `STATUS.md`.
5. До построения roadmap выполни отдельный semantic requirements review по skill `requirements-review`. Исправь объективные drafting defects. Если остаётся contradiction/missing decision, который меняет продуктовый контракт, зафиксируй OPEN_QUESTION или prerequisite RESEARCH/ADR work вместо догадки.
6. ADR создавай только для реальных устойчивых решений; неопределённость не превращай в Accepted ADR.
7. Построй draft roadmap по dependencies и создай полноценные STEP-файлы.
8. Выполни независимый roadmap consistency review: REQ↔REQ, REQ↔ADR, STEP↔REQ, Goal/Scope/Out of scope↔Acceptance, STEP↔STEP ownership, dependencies, architecture prerequisites, blocking OPEN_QUESTIONS и Verification. Не считай собственную генерацию доказательством согласованности.
9. После semantic review запусти deterministic gate:
   ```bash
   python3 .harness/tools/validate.py --mode manual
   ```
   Static validator обязан пройти для planning/requirements invariants. Semantic `BLOCKED` нельзя обходить успешным static PASS.
10. Обеспечь traceability REQ↔STEP↔ADR и обнови только generated project block `README.md`, generated `PROJECT-CONTEXT` block `AGENTS.md` и manifest. Статические ссылки Harness в README не переписывай.
11. `project.initialized: true` и `initializedAt` выставляй только после успешных semantic + deterministic consistency gates. До этого проект считается неинициализированным.
12. Сохрани `.github/workflows/harness-integrity.yml` как baseline Harness CI. Если стек уже определён достаточно точно, product-specific CI проектируй отдельным STEP/документом; не выдумывай команды сборки до появления реального tooling.
13. Не создавай production code.
14. Финальный отчёт: созданные артефакты, результаты consistency gates, unresolved questions, agent profile recommendation, следующий STEP/команда.

Если semantic review после одного исправляющего прохода всё ещё находит существенное противоречие, заверши INIT как `BLOCKED`, а не запускай бесконечный внутренний цикл.
