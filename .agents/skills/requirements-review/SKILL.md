---
name: requirements-review
description: Review requirements for clarity, testability, duplication, conflicts and traceability without turning implementation details into product contracts.
---
# requirements-review

Проверяй canonical `docs/requirements/REQ-NNN-*.md` на атомарность, наблюдаемое acceptance, дубликаты/конфликты, приоритет, source и STEP coverage. `SPEC.md` и `STATUS.md` рассматривай как projections, а не как competing source requirement definition. Новый REQ нужен только когда меняется требуемое поведение/качество продукта или обязательный system contract. Технический refactor/bug correction может ссылаться на existing REQ или быть purely corrective task.
