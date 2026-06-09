from __future__ import annotations

import threading
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .server import RobotResultAnalyzerServer
from .models import BugReportData, FailureGroup, RobotRunSummary, RunComparisonResult
from . import failure_matrix as _matrix

app = FastAPI(
    title="Robot Framework MCP Server",
    description="Local HTTP-based helper service for Robot Framework failure analysis.",
)

# Single shared analyzer — protected by a lock because uvicorn runs sync
# endpoints in a thread pool, and load_result_file mutates shared parser state.
_analyzer = RobotResultAnalyzerServer()
_analyzer_lock = threading.Lock()


class ResultPathRequest(BaseModel):
    path: str


class CompareRequest(BaseModel):
    current_path: str
    previous_path: str


class IngestRequest(BaseModel):
    results_dir: str


class FailureMatrixRequest(BaseModel):
    results_dir: str
    area_filter: str = ""
    output_path: str = ""
    output_format: str = "markdown"  # "markdown" or "html"


class TriageQueueRequest(BaseModel):
    results_dir: str
    area_filter: str = ""
    top_n: int = 15
    exclude_known_defects: bool = True
    exclude_infra: bool = True


class DebugContextRequest(BaseModel):
    xml_path: str
    test_name: str


class GroupTestsRequest(BaseModel):
    results_dir: str
    failure_pattern: str
    area_filter: str = ""


class QueryRequest(BaseModel):
    results_dir: str
    sql: str


@app.post("/tools/ingest")
def ingest_results(request: IngestRequest) -> dict:
    try:
        return _matrix.ingest_results(request.results_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/tools/load_result_file", response_model=RobotRunSummary)
def load_result_file(request: ResultPathRequest) -> RobotRunSummary:
    try:
        with _analyzer_lock:
            return _analyzer.load_result_file(request.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/tools/failed_tests")
def get_failed_tests(limit: int = 50, message_len: int = 200) -> list:
    try:
        with _analyzer_lock:
            tests = _analyzer.get_failed_tests()
        results = []
        for t in tests[:limit]:
            d = t.__dict__.copy() if hasattr(t, "__dict__") else dict(t)
            if len(d.get("message", "")) > message_len:
                d["message"] = d["message"][:message_len] + "…"
            d.pop("source", None)
            d.pop("elapsed_time_seconds", None)
            results.append(d)
        return {"total": len(tests), "returned": len(results), "tests": results}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


_TRACE_DROP = frozenset(("source", "elapsed_time_seconds"))


def _slim_trace(entries) -> list:
    return [{k: v for k, v in e.__dict__.items() if k not in _TRACE_DROP} for e in entries]


@app.get("/tools/tests/{test_name}")
def get_test_details(test_name: str) -> dict:
    try:
        with _analyzer_lock:
            details = _analyzer.get_test_details(test_name)
        d = details.__dict__.copy()
        for f in ("source", "start_time", "end_time"):
            d.pop(f, None)
        if d.get("keyword_trace"):
            d["keyword_trace"] = _slim_trace(d["keyword_trace"])
        return d
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/tools/tests/{test_name}/keywords")
def get_keyword_trace(test_name: str) -> list:
    try:
        with _analyzer_lock:
            trace = _analyzer.get_keyword_trace(test_name)
        return _slim_trace(trace)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/tools/summarize_failures", response_model=List[FailureGroup])
def summarize_failures() -> List[FailureGroup]:
    try:
        with _analyzer_lock:
            return _analyzer.summarize_failures()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/tools/compare", response_model=RunComparisonResult)
def compare_with_previous_run(request: CompareRequest) -> RunComparisonResult:
    try:
        return _analyzer.compare_with_previous_run(request.current_path, request.previous_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/tools/generate_bug_report_data", response_model=BugReportData)
def generate_bug_report_data(test_name: str) -> BugReportData:
    try:
        with _analyzer_lock:
            return _analyzer.generate_bug_report_data(test_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/tools/generate_failure_matrix")
def generate_failure_matrix(request: FailureMatrixRequest) -> dict:
    try:
        # Derive output path: if html format requested and no explicit path given,
        # auto-append .html; if explicit path given, honour it as-is.
        out = request.output_path or None
        if not out and request.output_format == "html":
            out = None  # caller must supply output_path for file output
        result = _matrix.analyse(
            results_dir=request.results_dir,
            area_filter=request.area_filter,
            output_path=out,
        )
        return {
            "total_failures": result.total_failures,
            "total_groups": result.total_groups,
            "output_path": result.output_path,
            "content": result.markdown,
            "format": "html" if (out or "").lower().endswith(".html") else "markdown",
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/tools/triage_queue")
def get_triage_queue(request: TriageQueueRequest) -> list:
    try:
        items = _matrix.triage_queue(
            results_dir=request.results_dir,
            area_filter=request.area_filter,
            top_n=request.top_n,
            exclude_known_defects=request.exclude_known_defects,
            exclude_infra=request.exclude_infra,
        )
        return [item.__dict__ for item in items]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/tools/prepare_debug_context")
def prepare_debug_context(request: DebugContextRequest) -> dict:
    try:
        ctx = _matrix.prepare_debug_context(request.xml_path, request.test_name)
        d = ctx.__dict__.copy()
        # Truncate failure_message — full API request/response blocks can be 1K+ chars.
        # The key detail is already captured in innermost_failure and keyword_trace.
        msg = d.get("failure_message", "")
        if len(msg) > 400:
            d["failure_message"] = msg[:400] + "…"
        # Slim keyword trace: drop 'type' (nearly always KEYWORD) and omit empty 'message'
        d["keyword_trace"] = [
            {k: v for k, v in entry.items() if k != "type" and not (k == "message" and not v)}
            for entry in (d.get("keyword_trace") or [])
        ]
        if d.get("innermost_failure"):
            inner = d["innermost_failure"].copy()
            inner.pop("type", None)
            if not inner.get("message"):
                inner.pop("message", None)
            d["innermost_failure"] = inner
        return d
    except (FileNotFoundError, ValueError) as exc:
        code = 404 if isinstance(exc, FileNotFoundError) else 400
        raise HTTPException(status_code=code, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/tools/group_tests")
def group_tests(request: GroupTestsRequest) -> list:
    try:
        return _matrix.get_group_tests(
            results_dir=request.results_dir,
            failure_pattern=request.failure_pattern,
            area_filter=request.area_filter,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


_QUERY_ROW_CAP = 200


@app.post("/tools/query")
def execute_query(request: QueryRequest) -> dict:
    import re
    import sqlite3
    from . import db as _db

    # Read-only guard — reject anything that isn't a SELECT
    stripped = request.sql.strip()
    if not re.match(r"^\s*SELECT\b", stripped, re.I):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed.")

    db_path = _db._db_path(request.results_dir)
    if not _db.db_exists(request.results_dir):
        raise HTTPException(status_code=404, detail="No database found — run ingest first.")

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(stripped)
        all_rows = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else []
        conn.close()
        rows = [dict(r) for r in all_rows[:_QUERY_ROW_CAP]]
        result = {"columns": columns, "rows": rows, "count": len(all_rows)}
        if len(all_rows) > _QUERY_ROW_CAP:
            result["truncated"] = True
            result["returned"] = len(rows)
        return result
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=400, detail=f"SQL error: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/resources/uris")
def list_resource_uris() -> List[str]:
    return _analyzer.list_resource_uris()
