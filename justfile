# Recipe descriptions come from these comments: `just` with no arguments lists
# them all, so the list cannot fall out of date with the recipes themselves.

set shell := ["bash", "-euo", "pipefail", "-c"]

# Show every recipe with its description
default:
    @just --list --unsorted

# Install dependencies and create .env
setup:
    uv sync
    @[ -f .env ] || cp .env.example .env
    @echo "Done. Run 'just hooks' to install git hooks."

# Install git hooks (pre-commit, commit-msg, pre-push)
hooks:
    uv run pre-commit install --install-hooks
    @echo "Hooks installed."

# Bump pinned hook revisions (deliberate, reviewable change)
update-hooks:
    uv run pre-commit autoupdate

# Run the whole test suite with coverage
test:
    uv run pytest

# Run the unit tests only, for a tight edit-test loop
test-fast:
    uv run pytest -x -q --no-cov -m "not slow and not integration"

# Write an HTML coverage report to htmlcov/
cov:
    uv run pytest --cov-report=html
    @echo "Report at htmlcov/index.html"

# Check style
lint:
    uv run ruff check .
    uv run ruff format --check .

# Fix style in place
format:
    uv run ruff check --fix .
    uv run ruff format .

# Run the type checker
typecheck:
    uv run ty check

# Check for missing, unused or transitive dependencies
deps:
    uv run deptry src

# Everything CI runs
check: lint typecheck deps test

# Run the ETL pipeline: every stage, in registration order
etl:
    uv run packagename-stage --all

# Regenerate the per-region samples and the manifest of the full datasets
subsample:
    uv run packagename-data subsample

# Warn if a full dataset changed, went missing or is new since the manifest
check-data:
    uv run packagename-data check

# Train a model
train:
    uv run packagename-train

# Remove caches and generated reports
clean:
    find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name .ipynb_checkpoints -exec rm -rf {} + 2>/dev/null || true
    rm -rf .ruff_cache .ty_cache .pytest_cache htmlcov .coverage dist build *.egg-info
