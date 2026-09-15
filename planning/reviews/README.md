# Reviews

Каждый `REVIEW STEP-NNN` создаёт новый immutable report в каталоге `planning/reviews/STEP-NNN/`.

Нельзя переписывать старый FAIL report после исправления; повторный review создаёт новый файл. Task хранит ссылку только на latest report/verdict.
