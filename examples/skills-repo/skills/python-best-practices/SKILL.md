---
name: python-best-practices
description: "Python development best practices for modern Python 3.11+ projects. Use when writing Python code, reviewing Python PRs, or setting up Python project structure."
globs: "**/*.py,pyproject.toml,setup.cfg"
activation: auto
license: MIT
metadata:
  author: mcpm
  version: "1.0.0"
  tags: "python,development,best-practices"
---

## Python Best Practices

### Project Setup

- Use `pyproject.toml` for all project configuration (no `setup.py` or `setup.cfg`)
- Use `uv` for dependency management and virtual environments
- Pin dependencies with version ranges in `pyproject.toml`, exact versions in lockfile
- Use `ruff` for both linting and formatting (replaces flake8, black, isort)

### Type Hints

- Use type hints on all public function signatures
- Use `from __future__ import annotations` for modern syntax in older Python
- Prefer `str | None` over `Optional[str]` (Python 3.10+)
- Use `TypeAlias` for complex types, not bare assignments

### Data Models

- Use Pydantic `BaseModel` for data validation at system boundaries
- Use `dataclass` for internal data structures without validation needs
- Use `model_dump()` / `model_validate()` (Pydantic v2), never `dict()` / `parse_obj()`
- Use `ConfigDict` instead of inner `class Config` (deprecated in Pydantic v2)

### Error Handling

- Use specific exception types, not bare `except Exception`
- Log errors with `logger.error()` including context, don't just `print()`
- Let exceptions propagate to the appropriate handler -- don't swallow them
- Use `raise ... from e` to preserve exception chains

### Testing

- Use `pytest` with `tmp_path` fixture for file operations
- Use `monkeypatch` over `unittest.mock.patch` when possible
- Structure tests as: Arrange (setup), Act (call), Assert (verify)
- One assertion concept per test, clear test function names

### Imports

- Standard library, then third-party, then local (ruff handles this)
- Prefer explicit imports over wildcards
- Use `from __future__ import annotations` if supporting Python < 3.12
