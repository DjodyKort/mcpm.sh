---
name: security-review
description: "Security review checklist applied to all code changes."
activation: always
license: MIT
metadata:
  author: mcpm
  version: "1.0.0"
  tags: "security,review"
---

## Security Review

When writing or reviewing code, always check:

- Never hardcode secrets, API keys, or credentials in source code
- Use `${env:VAR_NAME}` for environment variable references in configs
- Validate and sanitize all external input (user input, API responses, file contents)
- Use parameterized queries for database operations, never string concatenation
- Avoid `eval()`, `exec()`, and `subprocess.run(shell=True)` with user-provided input
- Check file paths for directory traversal (`..`) before file operations
- Use HTTPS for all external API calls
- Log security-relevant events but never log secrets or PII
- Prefer allowlists over denylists for input validation
