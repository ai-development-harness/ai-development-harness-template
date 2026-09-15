---
name: requirements-review
description: Review requirements for clarity, testability, duplication, conflicts and traceability without turning implementation details into product contracts.
---
# requirements-review

Проверяй REQ на атомарность, наблюдаемое acceptance, дубликаты/конфликты, приоритет, source и STEP coverage. Новый REQ нужен только когда меняется требуемое поведение/качество продукта или обязательный system contract. Технический refactor/bug correction может ссылаться на existing REQ или быть purely corrective task.
