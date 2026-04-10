---
name: mcp-server-dev
description: "Build MCP servers following best practices. Use when creating or modifying MCP server implementations, defining tools/resources/prompts, or debugging MCP protocol issues."
globs: "src/**/*.py,src/**/*.ts"
activation: auto
license: MIT
metadata:
  author: mcpm
  version: "1.0.0"
  tags: "mcp,server,development"
---

## MCP Server Development

When building or modifying MCP servers, follow these practices:

### Architecture

- Use the FastMCP framework for Python servers (`from fastmcp import FastMCP`)
- Use the `@mcp.tool()`, `@mcp.resource()`, and `@mcp.prompt()` decorators
- Keep tools focused: one tool per distinct action, clear input/output schemas
- Resources should be read-only data endpoints; tools should be for actions with side effects

### Tool Design

- Tool names should be verb-noun format: `search_files`, `create_issue`, `run_query`
- Always include clear descriptions in tool decorators -- agents use these for discovery
- Define input schemas with Pydantic models or typed parameters
- Return structured data (dicts/lists), not formatted strings -- let the client format
- Handle errors gracefully: return error info in the response, don't raise exceptions

### Testing

- Test tools with real inputs, not mocks -- MCP tools are integration points
- Use `mcp.test_client()` for end-to-end tool testing
- Test error cases: missing params, invalid inputs, service unavailable

### Transport

- Default to stdio transport for local servers
- Use streamable-http for remote/shared servers
- SSE is legacy -- prefer streamable-http for new servers
- Always support environment variable configuration via `${env:VAR_NAME}` syntax

### Common Pitfalls

- Don't put business logic inside tool handlers -- extract to separate functions
- Don't hardcode paths or URLs -- use environment variables
- Don't return raw HTML/XML in tool responses -- return structured data
- Don't create tools that require multi-step sequences -- each tool should be self-contained
