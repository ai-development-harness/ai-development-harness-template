# Документация проекта

После `INIT PROJECT` этот каталог становится project knowledge base.

## Продуктовые документы

- `PROJECT.md` — назначение, пользователи, границы, цели и ограничения проекта.
- `requirements/SPEC.md` — канонические продуктовые требования.
- `requirements/STATUS.md` — projection состояния REQ.
- `architecture.md` — текущий архитектурный baseline.
- `adr/` — immutable history устойчивых архитектурных решений.
- `development.md` — команды, environments, testing/build conventions после появления кода.
- `OPEN_QUESTIONS.md` — нерешённые вопросы, которые нельзя молча угадывать.
- `GLOSSARY.md` — продуктовые/доменные термины конкретного проекта.
- `skills/` — provenance/registry дополнительных project/technology skills.

## Документация Harness

`harness/` описывает правила самого AI Development Harness и не должна смешиваться с product docs.

Начни с:

- `harness/README.md` — оглавление;
- `harness/DOCUMENT_MODEL.md` — связи REQ/ADR/STEP/PLAN/STATUS/Evidence/Review;
- `harness/GLOSSARY.md` — определения терминов Harness.

Product-specific subsystem docs добавляются по мере появления устойчивых подсистем. Не создавай десятки пустых файлов во время INIT без необходимости.
