# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.1.0] — 2026-06-09

### Added

- `ingest_results` — idempotent ingestion of Robot Framework `output.xml` files into SQLite
- `generate_failure_matrix` — interactive HTML report with score-distribution doughnut chart and collapsible failure groups
- `get_triage_queue` — ranked list of failure groups, highest impact first
- `prepare_debug_context` — per-test keyword trace and product-file hints for Claude triage skills
- `get_group_tests` — on-demand test list for a failure group
- `execute_query` — read-only SQL against the `scored_tests` table (200-row cap)
- `load_result_file`, `get_failed_tests`, `get_test_details`, `get_keyword_trace` — single-file analysis tools
- `summarize_failures`, `compare_with_previous_run`, `generate_bug_report_data` — higher-level analysis tools
- Multidimensional failure scoring (priority, severity, defect ID, quarantine, infra type, group size)
- API response-code escalation — 5xx forced to 92, 4xx to 87, 403 to 80, regardless of tags
- Actual error extraction from response body JSON
- Fingerprint-based failure grouping with group bonus scoring
- FastMCP stdio transport for Claude Desktop and Claude Code integration
- FastAPI HTTP backend with Swagger UI at `/docs`
- SQLite persistence with idempotent SHA-1 content hashing
- Area category routing for external Claude debug skills
- GitHub Actions CI (pytest + ruff, Python 3.11 and 3.12)
