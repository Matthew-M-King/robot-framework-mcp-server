# Robot Framework MCP Server

[![CI](https://github.com/Matthew-M-King/robot-framework-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/Matthew-M-King/robot-framework-mcp-server/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![Robot Framework](https://img.shields.io/badge/Robot_Framework-6.x-green)
![MCP](https://img.shields.io/badge/MCP-Compatible-purple)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

A local Python MCP server for analysing Robot Framework `output.xml` results and exposing structured failure data to Claude Desktop and Claude Code.

---

## Why?

Large Robot Framework suites often produce hundreds of failures across dozens of areas.
Instead of manually reading `output.xml` files, this MCP server:

- groups failures by shared root cause
- prioritises by business impact and severity tags
- escalates API/server errors automatically (5xx → 92, 4xx → 87, 403 → 80)
- generates interactive HTML reports with score-distribution charts
- provides Claude with full keyword traces for rapid debugging

The result: a triage session that takes minutes instead of hours.

---

## Quick Start

```bash
# 1. Install
pip install -r requirements.txt
pip install mcp

# 2. Start the server
python -m uvicorn robot_mcp_server.http_server:app --host 127.0.0.1 --port 8000

# 3. In Claude — ingest your results, then triage
ingest_results(results_dir="/path/to/results")
generate_failure_matrix(output_path="/path/to/report.html")
get_triage_queue()
```

## Interactive HTML Report

![Failure matrix showing score distribution doughnut chart and collapsible failure groups](docs/failure-matrix.png)



API docs available at `http://127.0.0.1:8000/docs` once the server is running.

---

## Why not just inspect output.xml manually?

| Manual review | Robot Framework MCP Server |
|---|---|
| Hundreds of unranked failures | Ranked triage queue — highest impact first |
| Manual root-cause grouping | Automatic fingerprint clustering |
| Raw XML | Interactive HTML with doughnut chart |
| Ctrl+F through log files | SQL queries against a structured database |
| Status code only | Actual API error message extracted from response body |
| Separate tool per task | Single MCP interface for Claude Desktop and Claude Code |

---

## What it does

- Parses Robot Framework `output.xml` files and persists results to a local SQLite database
- Scores every failing test across multiple dimensions (priority, severity, defect ID, quarantine, infra type, group size)
- Groups failures by shared root cause and ranks them into a triage queue
- **Escalates API response-code failures** (`Wrong response code received`) automatically — 5xx forced to score 92, other 4xx to 87, 403 to 80 — regardless of test tags
- Extracts the actual error from the response body JSON so you see the real server message, not just the status code
- Generates a prioritised failure report — **interactive HTML by default** (score-distribution doughnut chart, collapsible API failure groups, collapsible failure groups) or plain Markdown
- Prepares per-test debug context (keyword trace, innermost failure, product-file hints) linked to the `robot-tests` Claude skill
- Supports freeform SQL queries against the failure database for ad-hoc questions (results capped at 200 rows)

---

## Architecture

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
  sample_output.xml     minimal RF output.xml for testing
prompt_templates/
  review_robot_failures.md  Claude prompt template
```

---

## Installation

```bash
python -m pip install -r requirements.txt
pip install mcp   # MCP Python SDK for Claude integration
```

## Running

Start the FastAPI HTTP server (must be running before using any MCP tools):

```bash
python -m uvicorn robot_mcp_server.http_server:app --host 127.0.0.1 --port 8000
```

Check it's up: `http://127.0.0.1:8000/docs`

---

## Connecting to Claude Desktop

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "robot-framework-failure-review": {
      "command": "python",
      "args": ["C:\\path\\to\\robot-framework-mcp-server\\examples\\mcp_stdio_wrapper.py"],
      "env": {
        "BASE_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

Then restart Claude Desktop. The server appears under the **+** → **Connectors** menu.

## Connecting to Claude Code

The `.claude/settings.json` in this repo configures the MCP server automatically for Claude Code when working in this directory.

---

## Area category configuration (optional)

`prepare_debug_context` can route each failure to a named debug category and supply product-file hints for an external skill. This mapping is **entirely optional** — the server works without it, and all tests default to the `GENERIC` category.

To add your own mappings, create `area_categories.json` in the project root (or set `RF_AREA_CATEGORIES` to an absolute path):

```json
[
  {
    "folder_fragment": "Checkout",
    "category": "CHECKOUT",
    "hints": ["checkout/checkout.md"]
  },
  {
    "folder_fragment": "Auth",
    "category": "AUTH",
    "hints": ["auth/auth.md"]
  }
]
```

Each `folder_fragment` is matched case-insensitively against the parent folder of each `output.xml`. An example with sample entries ships as `area_categories.json`.

---

## Database initialisation

Before using `get_triage_queue`, `generate_failure_matrix`, or `execute_query`, ingest the results once:

```
ingest_results(results_dir="F:\path\to\results")
```

This parses all `robot/output.xml` files found in child folders, scores every failing test, and writes everything to `failure_analysis.db` inside `results_dir`. The ingest is **idempotent** — if nothing has changed (SHA-1 hash of all xml mtimes matches) it returns immediately. On a fresh run expect ~3 minutes for a large suite; subsequent calls complete in under 1 second.

You only need to re-run ingest after a new test run produces new `output.xml` files.

---

## Available MCP tools

| Tool | Description |
|------|-------------|
| `ingest_results` | Parse all output.xml files and write to SQLite — run once per test run |
| `generate_failure_matrix` | Score all failures and write an interactive HTML report (default) or Markdown |
| `get_triage_queue` | Return a ranked list of failure groups — highest impact first |
| `prepare_debug_context` | Load a single test's keyword trace and product-file hints for deep analysis |
| `get_group_tests` | Fetch all tests in one failure group (on demand, keeps queue payload small) |
| `execute_query` | Run a read-only SELECT against the failure database for ad-hoc questions |
| `load_result_file` | Load a specific `output.xml` into the server |
| `get_failed_tests` | List all failed tests from the loaded result |
| `get_test_details` | Full details for one test |
| `get_keyword_trace` | Keyword-by-keyword trace for one test |
| `summarize_failures` | Grouped failure summary for the loaded result |
| `compare_with_previous_run` | Diff two output.xml files |
| `generate_bug_report_data` | Structured data for filing a bug report |

---

## Failure scoring

Scores run 0–100. Higher = investigate first.

| Factor | Points |
|--------|--------|
| API escalation — 5xx server error | forced 92 |
| API escalation — 4xx client error (exc. 403) | forced 87 |
| API escalation — 403 Forbidden | forced 80 |
| Priority / Severity critical | +40 each |
| Priority / Severity high | +25 each |
| Priority / Severity medium (default) | 0 |
| Priority / Severity low | −20 each |
| `defectid=` tag | −25 |
| `quarantine-*` tag | **+10** (flagged risk — elevated, not suppressed) |
| Infra failure (missing keyword/library) | −30 |
| Infra failure (connection/deadlock in setup) | −20 |
| Other setup failure | −10 |
| Shared fingerprint group bonus | up to +20 |

---

## Typical workflow

```
1. Start FastAPI server (uvicorn)
2. Call ingest_results(results_dir=...) — one-time parse, ~3 min; instant if unchanged
3. Call generate_failure_matrix(output_path=...) → interactive HTML report written to disk
4. Call get_triage_queue → ranked groups, highest-impact first
5. For each group: call prepare_debug_context → keyword trace + routing hints
6. Use the robot-tests Claude skill (triage command) to drive the full session
7. Ad-hoc questions: call execute_query with a SELECT against scored_tests
```

---

## Ad-hoc queries (execute_query)

Ask questions in plain English — Claude writes the SQL. Results are capped at 200 rows; the response includes `truncated: true` and `returned` when the cap is hit. Examples:

```sql
-- How many failures per area?
SELECT area, COUNT(*) AS failures FROM scored_tests GROUP BY area ORDER BY failures DESC

-- Which quarantined tests have the highest score?
SELECT name, area, base_score FROM scored_tests WHERE is_quarantined=1 ORDER BY base_score DESC

-- All API escalated failures grouped by endpoint
SELECT api_endpoint, COUNT(*) AS n, received_code
FROM scored_tests WHERE escalated=1
GROUP BY api_endpoint ORDER BY n DESC

-- Critical failures with no tracked defect
SELECT name, area, base_score FROM scored_tests
WHERE priority='critical' AND defect_ids='[]' AND is_quarantined=0
ORDER BY base_score DESC
```

---

## Unit tests

```bash
pytest
```

---

## Notes

- Compatible with Robot Framework 6.x (`output.xml` format changes from RF 4/5 handled)
- All analysis is read-only; no test results are modified
- The `mcp_stdio_wrapper.py` requires the FastAPI server to be running separately on port 8000
- The SQLite database (`failure_analysis.db`) lives inside the results directory alongside the xml folders
