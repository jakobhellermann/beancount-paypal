_default:
    just --list

check:
    uv run ruff check && uv run ty check

format:
    uv run ruff format

test:
    uv run tests/run.py test tests/files --expected tests/files

test-check:
    uv run bean-check tests/journal.beancount

test-generate:
    uv run tests/run.py generate tests/files --expected tests/files --force
