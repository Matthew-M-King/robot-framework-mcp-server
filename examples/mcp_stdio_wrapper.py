"""Simple MCP stdio wrapper that proxies registered tools to a local HTTP server.

This wrapper expects the `mcp` package to be installed. It registers callable tools
that forward requests to the HTTP API exposed by the FastAPI server.

Set `BASE_URL` environment variable to point at the HTTP server (default: http://127.0.0.1:8000).
"""
from __future__ import annotations

import os
import sys
from typing import Any
from urllib.parse import quote

import requests

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - runtime helper
    print(
        "Required package 'mcp' is missing. Install it in your Python environment:\n    python -m pip install mcp",
        file=sys.stderr,
    )
    sys.exit(2)

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000")

# Endpoints that parse all output.xml files can take a long time on large suites.
_QUICK_TIMEOUT = 30
_PARSE_TIMEOUT = 300

mcp = FastMCP("robot-framework-failure-review")

# Endpoints whose server-side work is bounded by XML parsing time.
_PARSE_PATHS = {"/tools/ingest", "/tools/generate_failure_matrix", "/tools/triage_queue"}


def http_post(path: str, payload: Any) -> Any:
    url = BASE_URL.rstrip("/") + path
    timeout = _PARSE_TIMEOUT if path in _PARSE_PATHS else _QUICK_TIMEOUT
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def http_get(path: str, params: Any = None) -> Any:
    url = BASE_URL.rstrip("/") + path
    resp = requests.get(url, params=params or {}, timeout=_QUICK_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
def ingest_results(results_dir: str) -> Any:
    """Parse Robot Framework output.xml files in results_dir into a local SQLite DB.
    Run before get_triage_queue or generate_failure_matrix. Returns run_id and total_failures."""
    return http_post("/tools/ingest", {"results_dir": results_dir})


@mcp.tool()
def load_result_file(path: str) -> Any:
    """Load a Robot Framework result XML file for analysis."""
    return http_post("/tools/load_result_file", {"path": path})


@mcp.tool()
def get_failed_tests(limit: int = 50) -> Any:
    """Return failed tests from the loaded result file. Messages are truncated to 200 chars.
    Use limit to control how many are returned (default 50). Response includes total count."""
    return http_get("/tools/failed_tests", params={"limit": limit, "message_len": 200})


@mcp.tool()
def get_test_details(test_name: str) -> Any:
    """Return detailed information about a specific test."""
    return http_get(f"/tools/tests/{quote(test_name, safe='')}")


@mcp.tool()
def get_keyword_trace(test_name: str) -> Any:
    """Return the keyword execution trace for a specific test."""
    return http_get(f"/tools/tests/{quote(test_name, safe='')}/keywords")


@mcp.tool()
def summarize_failures() -> Any:
    """Return failure groups. test_names capped at 10 per group; use get_group_tests for the full list."""
    groups = http_get("/tools/summarize_failures")
    if isinstance(groups, list):
        for g in groups:
            names = g.get("test_names", [])
            if len(names) > 10:
                g["test_names"] = names[:10]
                g["test_names_total"] = len(names)
    return groups


@mcp.tool()
def compare_with_previous_run(current_path: str, previous_path: str) -> Any:
    """Compare the current result file with a previous run."""
    return http_post("/tools/compare", {"current_path": current_path, "previous_path": previous_path})


@mcp.tool()
def generate_bug_report_data(test_name: str) -> Any:
    """Generate bug report data for a specific failed test."""
    return http_get(f"/tools/generate_bug_report_data?test_name={quote(test_name, safe='')}")


@mcp.tool()
def generate_failure_matrix(
    results_dir: str,
    area_filter: str = "",
    output_path: str = "",
    output_format: str = "html",
) -> Any:
    """Scan a results directory and produce a scored, prioritised failure report.

    Args:
        results_dir: Directory whose subdirectories each contain robot/output.xml.
        area_filter: Optional folder-name substring filter, e.g. 'EstateManagement'.
        output_path: File path to write the report. Extension sets format (.html or .md).
        output_format: "html" (default, interactive with chart) or "markdown".
    """
    # Auto-set output_path extension to match format if caller gave a bare path
    resolved_path = output_path
    if resolved_path and output_format == "html" and not resolved_path.lower().endswith(".html"):
        resolved_path = resolved_path.rsplit(".", 1)[0] + ".html"

    result = http_post("/tools/generate_failure_matrix", {
        "results_dir": results_dir,
        "area_filter": area_filter,
        "output_path": resolved_path,
        "output_format": output_format,
    })
    # Drop the full report content — it's already written to output_path.
    # Returning it would consume thousands of tokens for no benefit.
    result.pop("content", None)
    result.pop("markdown", None)
    return result


@mcp.tool()
def get_triage_queue(
    results_dir: str,
    area_filter: str = "",
    top_n: int = 15,
    exclude_known_defects: bool = True,
    exclude_infra: bool = True,
) -> Any:
    """Return a prioritised investigation queue of failing test groups.

    Args:
        results_dir: Directory whose subdirectories each contain robot/output.xml.
        area_filter: Optional folder-name substring filter, e.g. 'EstateManagement'.
        top_n: Maximum number of groups to return (default 15).
        exclude_known_defects: Skip groups where all tests already have defectid= tags.
        exclude_infra: Skip pure test-infrastructure failures.
    """
    return http_post("/tools/triage_queue", {
        "results_dir": results_dir,
        "area_filter": area_filter,
        "top_n": top_n,
        "exclude_known_defects": exclude_known_defects,
        "exclude_infra": exclude_infra,
    })


@mcp.tool()
def prepare_debug_context(xml_path: str, test_name: str) -> Any:
    """Load a failing test from output.xml and return debug context for the robot-tests skill.

    Returns debug_category, product_file_hints, keyword_trace (FAIL path only),
    innermost_failure, failure_message, tags, priority, severity, defect_ids, suite_path.

    Args:
        xml_path: Path to the output.xml (use xml_path from get_triage_queue).
        test_name: Test case name (use representative_test from get_triage_queue).
    """
    return http_post("/tools/prepare_debug_context", {
        "xml_path": xml_path,
        "test_name": test_name,
    })


@mcp.tool()
def get_group_tests(results_dir: str, failure_pattern: str, area_filter: str = "") -> Any:
    """Fetch all tests in one failure group by its fingerprint.

    Args:
        results_dir: Same directory passed to get_triage_queue.
        failure_pattern: The failure_pattern string from the TriageItem.
        area_filter: Optional area filter (same value used for the queue).
    """
    return http_post("/tools/group_tests", {
        "results_dir": results_dir,
        "failure_pattern": failure_pattern,
        "area_filter": area_filter,
    })


@mcp.tool()
def execute_query(results_dir: str, sql: str) -> Any:
    """Run a read-only SELECT against the failure analysis SQLite DB. Returns {columns, rows, count}.
    Results are capped at 200 rows; response includes truncated=true when the cap is hit.

    Schema:
      runs(id, results_dir, hash, ingested_at)
      scored_tests(id, run_id, area, suite, name, tags, message, failure_type,
        priority, severity, defect_ids, is_quarantined, fp, base_score,
        xml_path, api_endpoint, escalated, received_code, response_error)

    Args:
        results_dir: Same directory passed to ingest_results.
        sql: A read-only SELECT statement.
    """
    return http_post("/tools/query", {"results_dir": results_dir, "sql": sql})


if __name__ == "__main__":
    mcp.run(transport="stdio")
