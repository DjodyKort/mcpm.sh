---
name: code-style
description: "Enforce consistent code style across the project."
activation: always
license: MIT
metadata:
  author: mcpm
  version: "1.0.0"
---

## Code Style

- Use 4 spaces for indentation (never tabs)
- Maximum line length: 120 characters
- Use double quotes for strings unless the string contains double quotes
- Trailing commas in multi-line collections
- No wildcard imports
- Sort imports: stdlib, third-party, local (automated by ruff)
- One blank line between functions, two blank lines between classes
- Docstrings on all public functions and classes (Google style)
