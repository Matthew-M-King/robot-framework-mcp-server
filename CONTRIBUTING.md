# Contributing

## Setup

```bash
git clone https://github.com/Matthew-M-King/robot-framework-mcp-server.git
cd robot-framework-mcp-server
pip install -e ".[test]"
pip install mcp ruff
```

## Running the tests

```bash
pytest
```

## Linting

```bash
ruff check .
```

CI enforces both on every push to `main`.

## Making changes

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Add or update tests if you're changing behaviour
4. Run `pytest` and `ruff check .` locally before pushing
5. Open a pull request — describe what changed and why

## What's in scope

- Bug fixes in the scoring, grouping, or parsing logic
- New MCP tools exposed via the FastAPI layer
- Improvements to the HTML report renderer
- Additional SQL query examples or documentation

## What's out of scope

- Changes to the MCP protocol transport itself
- Integrations with non-Robot-Framework test frameworks (raise an issue to discuss first)
