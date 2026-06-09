# Architecture

## Component overview

```
Claude Desktop / Claude Code
        │
        ▼
examples/mcp_stdio_wrapper.py     ← FastMCP stdio transport (MCP protocol)
        │  http
        ▼
robot_mcp_server/http_server.py   ← FastAPI HTTP server (uvicorn, port 8000)
        │
        ▼
robot_mcp_server/
  failure_matrix.py   — scoring, grouping, triage queue, debug context
  db.py               — SQLite persistence (failure_analysis.db)
  parser.py           — output.xml loading, keyword trace extraction
```

Claude communicates with the server over MCP (stdio). The stdio wrapper forwards every tool call as an HTTP request to the FastAPI backend, which does the heavy lifting: parsing, scoring, grouping, and report generation.

## Project structure

```
robot_mcp_server/       Python package
  http_server.py        FastAPI endpoints
  failure_matrix.py     scoring, triage, matrix rendering
  html_report.py        interactive HTML report renderer
  db.py                 SQLite persistence layer
  parser.py             output.xml parsing (RF 6.x compatible)
examples/
  mcp_stdio_wrapper.py  MCP stdio wrapper (connect this to Claude)
  sample_output.xml     minimal RF output.xml for smoke-testing
  sample_results/       multi-area sample results (generates the demo report)
  generate_sample_report.py  script to regenerate docs/failure-matrix.png source
prompt_templates/
  review_robot_failures.md  Claude prompt template
docs/
  architecture.md       this file
  configuration.md      area categories, database initialisation
  tools.md              MCP tool reference and typical workflow
  scoring.md            failure scoring rubric
  sql-examples.md       ad-hoc SQL query examples
```

## Design decisions

**Why SQLite?**
Results directories can be on a shared network drive or CI artifact store. SQLite requires no server and produces a single portable file (`failure_analysis.db`) that lives alongside the results. Group bonuses are computed at query time using a window function rather than stored, so any area filter produces correct scores without re-ingestion.

**Why FastAPI + stdio wrapper instead of a pure MCP server?**
The FastAPI layer is independently testable and inspectable (Swagger UI at `/docs`). The stdio wrapper is a thin shim that translates MCP tool calls into HTTP requests — swapping the transport layer doesn't touch the core logic.

**Why MCP instead of a CLI?**
Claude drives the triage session. A CLI requires a human to decide which commands to run; MCP lets Claude sequence `get_triage_queue` → `prepare_debug_context` → `execute_query` autonomously based on what it finds.

**Why idempotent ingestion?**
Large suites take ~3 minutes to parse. A SHA-1 hash over all `(xml_path, mtime)` pairs detects changes in O(n) without re-reading XML. Subsequent calls on unchanged results return in under 1 second.
