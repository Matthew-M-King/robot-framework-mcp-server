# MCP Tools

## Typical workflow

```
1. Start FastAPI server (uvicorn)
2. ingest_results(results_dir=...)       — one-time parse; instant if unchanged
3. generate_failure_matrix(output_path=...) → HTML report written to disk
4. get_triage_queue()                    → ranked groups, highest-impact first
5. prepare_debug_context(xml, test)      → keyword trace + routing hints per test
6. execute_query(sql=...)                → ad-hoc questions against scored_tests
```

## Tool reference

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

## Notes

- All tools are read-only — no test results are modified
- `mcp_stdio_wrapper.py` requires the FastAPI server to be running on port 8000
- The SQLite database (`failure_analysis.db`) lives inside the results directory
- Compatible with Robot Framework 6.x (`output.xml` format changes from RF 4/5 handled)
