---
description: Core development workflow and quality standards for signal-market
alwaysApply: true
---

# Development Workflow Standards

## Code Quality & Professionalism

### No Emojis in Code or PRs
- Never use emojis in code comments, commit messages, PR titles, or PR descriptions
- Keep communication professional, direct, and concise

### Production Discipline
- Never mock external market or weather data
- Never use fallback implementations that hide failures
- Fail fast with verbose, actionable errors
- Enable structured logging for new execution paths and integrations

### Professional PR Writing
- Use clear PR titles that explain both what changed and why
- Include context, implementation notes, testing evidence, and risk notes
- Link related issues or prior PRs when relevant

## Git Workflow

### Branch Strategy
- Never commit directly to `main`
- Create a feature/fix branch for all work
- Use descriptive branch names (for example: `feat/auction-smoke-validation`, `fix/ws-ingestion-timeout`)
- Open a PR for every change, including small fixes

## Quality Assurance Process

### Post-Code Quality Checks
Run checks only for the project(s) you changed.

1. Producer (`producer/`)
   - `uv run ruff check .`
   - `uv run mypy signal_producer`
   - `uv run pytest`
2. Consumer (`consumer/`)
   - `uv run ruff check .`
   - `uv run pytest`
3. Shared schema (`shared/`)
   - `uv run python -m compileall .`
4. Dashboard (`dashboard/`)
   - `npm run lint`
   - `npm run build`

### Testing Philosophy
- Prefer integration tests against real APIs/services when feasible
- Do not introduce fake fallback logic to make tests pass
- Validate real error paths and include log assertions where practical
- Keep tests deterministic and explicit about required external dependencies

## Dependency Management

### Version Management
- Keep dependencies current and actively maintained
- Use `uv` for Python dependency updates in `producer` and `consumer`
- Commit lockfile changes with dependency changes (`producer/uv.lock`, `consumer/uv.lock`, `dashboard/package-lock.json`)
- Re-run lint/tests/build after dependency updates

### Library Selection
- Prefer libraries with active maintenance and clear documentation
- Favor strong typing and reliability over novelty
- Consider runtime cost and operational complexity before adding dependencies

## Documentation & Research

### MCP and Documentation Usage
- Use Context7 MCP and official vendor docs for library/API behavior
- Use web search tools only when official docs are insufficient
- Record non-obvious implementation decisions in PR descriptions

### Documentation Updates
- Update `docs/` when behavior, schemas, or interfaces change
- Update README/setup instructions when commands or required env vars change
- Document breaking changes and migration steps clearly

## Code Review Checklist

Before opening a PR, verify:

- [ ] Relevant `uv run ruff check` and/or `npm run lint` passes
- [ ] Relevant tests pass locally (`uv run pytest`)
- [ ] Type checks pass where applicable (`uv run mypy signal_producer`)
- [ ] Build passes where applicable (`npm run build`)
- [ ] No debug-only prints or temporary diagnostics are left behind
- [ ] Error handling is explicit and logs enough context for debugging
- [ ] Documentation and schema updates are included when needed
- [ ] Commit messages are descriptive and follow conventional commits

## Examples

### Good PR Description
```markdown
feat: validate auction payload before websocket broadcast

## Context
Auction smoke signals were occasionally emitted with incomplete metadata.
This adds strict validation so failures are explicit and observable.

## Implementation
- Added schema validation before publish
- Added structured error logging for invalid payloads
- Added integration coverage for rejection path

## Testing
- uv run ruff check .
- uv run mypy signal_producer
- uv run pytest

## Breaking Changes
- Invalid auction messages are now rejected instead of silently tolerated
```

### Good Commit Messages
```text
feat: add auction smoke signal validation before publish
fix: reject malformed websocket payloads with explicit errors
docs: document producer smoke test execution workflow
refactor: extract shared signal serialization helpers
```

### Bad Commit Messages
```text
added stuff
fix bug
misc updates
```
