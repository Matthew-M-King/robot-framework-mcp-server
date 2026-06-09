"""
Failure scoring matrix for Robot Framework results.

Scans a directory of result folders, scores each failing test using a
multidimensional rubric, groups tests by shared root cause, and produces
a prioritised Markdown report.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from robot.api import ExecutionResult
from robot.errors import DataError

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------
PRIORITY_SCORE: dict[str, int] = {"critical": 40, "high": 25, "medium": 0, "low": -20}
SEVERITY_SCORE: dict[str, int] = {"critical": 40, "high": 25, "medium": 0, "low": -20}

DEFECT_PENALTY = -25
QUARANTINE_BONUS = 10        # quarantine = flagged risk, elevate not suppress
INFRA_KW_PENALTY = -30       # keyword / library missing
INFRA_SETUP_PENALTY = -20    # deadlock / connection failure in setup
SETUP_OTHER_PENALTY = -10    # other setup failure

GROUP_BONUS_PER_EXTRA = 5
GROUP_BONUS_CAP = 20

# API response code failures bypass tag-based scoring.
# 5xx → server error, highest priority. Other 4xx → likely a contract violation.
# 403 → often an auth/permissions issue, slightly lower than other client errors.
API_ESCALATION_5XX = 92
API_ESCALATION_4XX = 87
API_ESCALATION_403 = 80

# ---------------------------------------------------------------------------
# Failure classification regexes
# ---------------------------------------------------------------------------
_INFRA_KW = re.compile(
    r"No keyword with name|No keyword named|Keyword .{1,60} does not exist"
    r"|Cannot import library|Importing library .{1,60} failed"
    r"|ImportError|ModuleNotFoundError",
    re.I,
)
_INFRA_SETUP = re.compile(
    r"deadlock detected|connection (?:refused|reset|timed out|lost)"
    r"|could not connect|FATAL ERROR|OperationalError|TimeoutError",
    re.I,
)


# Detection pattern for API response failures.
#
# The default matches the "Wrong response code received" message produced by a
# specific custom RF HTTP keyword library.  Override with the RF_API_FAILURE_PATTERN
# env var to match your own library's error format, or set it to an empty string
# to disable API escalation entirely.
#
# The structured extraction below (endpoint, received code, response body) expects
# this specific message layout from that library:
#
#   Wrong response code received (expected 200 but received 500)
#   **SENT DETAILS**
#   URL: https://api.example.com/v1/resource
#   Method: GET
#   **RESPONSE DETAILS**
#   Reason: Internal Server Error
#   Response Body: {"Message": "Something went wrong"}
#
# If your library produces a different format, detection will still fire (and
# escalation will still score the failure), but endpoint/body details will be
# absent from the output.
_API_FAILURE_PATTERN_ENV = os.environ.get("RF_API_FAILURE_PATTERN", "Wrong response code received")
_API_RESPONSE_FAILURE = re.compile(_API_FAILURE_PATTERN_ENV, re.I) if _API_FAILURE_PATTERN_ENV else None

# Extraction patterns — only useful when the message matches the format above.
_SENT_URL = re.compile(r"URL:\s*(https?://\S+)", re.I)
_SENT_METHOD = re.compile(r"Method:\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)", re.I)
_RESPONSE_CODE = re.compile(r"Wrong response code received \(expected (\d+) but received (\d+)\)", re.I)
_RESPONSE_BODY_BLOCK = re.compile(r"Response Body:\s*(.+?)(?=\n\s*\*\*|\Z)", re.S | re.I)
_REASON_LINE = re.compile(r"Reason:\s*(.+)", re.I)


def is_api_response_failure(message: str) -> bool:
    """True when the failure message matches the configured API failure pattern."""
    if _API_RESPONSE_FAILURE is None:
        return False
    return bool(_API_RESPONSE_FAILURE.search(message or ""))


def extract_api_endpoint(message: str) -> Optional[str]:
    """
    Parse the structured **SENT DETAILS** block and return a one-line summary:
      METHOD /path (expected 200, got 500)

    Returns None if the message is not an API response failure.
    """
    if not is_api_response_failure(message):
        return None

    url_m = _SENT_URL.search(message)
    method_m = _SENT_METHOD.search(message)
    code_m = _RESPONSE_CODE.search(message)

    url = url_m.group(1) if url_m else "unknown endpoint"
    method = method_m.group(1) if method_m else "HTTP"

    if code_m:
        expected, received = code_m.group(1), code_m.group(2)
        return f"{method} {url} (expected {expected}, got {received})"
    return f"{method} {url}"


def extract_received_code(message: str) -> Optional[int]:
    """Return the HTTP response code actually received, or None."""
    m = _RESPONSE_CODE.search(message or "")
    return int(m.group(2)) if m else None


def extract_response_error(message: str) -> Optional[str]:
    """
    Pull a human-readable error out of the **RESPONSE DETAILS** block.
    Tries to parse Response Body JSON and extract a Message/error field.
    Falls back to the Reason line. Returns None if nothing useful is found.
    """
    body_m = _RESPONSE_BODY_BLOCK.search(message or "")
    if body_m:
        body_text = body_m.group(1).strip()
        if body_text:
            try:
                data = json.loads(body_text)
                if isinstance(data, dict):
                    for key in ("Message", "message", "error", "Error", "detail", "Detail", "title", "Title"):
                        val = data.get(key)
                        if val:
                            if isinstance(val, list):
                                # Join first few items, skip empty strings
                                parts = [str(v).strip() for v in val[:4] if str(v).strip()]
                                text = " ".join(parts)
                            else:
                                text = str(val).strip()
                            if text:
                                return text[:200]
            except (json.JSONDecodeError, ValueError):
                pass

    reason_m = _REASON_LINE.search(message or "")
    if reason_m:
        reason = reason_m.group(1).strip()
        if reason and reason.lower() not in ("ok",):
            return reason

    return None


def _api_escalation_score(received_code: Optional[int]) -> int:
    """Return the escalation score for a given HTTP response code."""
    if received_code is None:
        return API_ESCALATION_4XX  # unparseable code — treat conservatively
    if received_code >= 500:
        return API_ESCALATION_5XX
    if received_code == 403:
        return API_ESCALATION_403
    return API_ESCALATION_4XX  # other 4xx


def classify_failure(message: str) -> str:
    """Return one of: infra-keyword | infra-setup | setup-other | functional."""
    if _INFRA_KW.search(message):
        return "infra-keyword"
    if re.search(r"Setup failed", message, re.I):
        if _INFRA_SETUP.search(message):
            return "infra-setup"
        return "setup-other"
    return "functional"


# ---------------------------------------------------------------------------
# Failure fingerprinting
# ---------------------------------------------------------------------------
_SECTION_HEADER = re.compile(r"^\s*\*\*[^*]+\*\*\s*$")


def _strip_section_headers(msg: str) -> str:
    """Remove markdown bold section labels like '**FAILURE REASON**' from message lines."""
    lines = [ln for ln in msg.splitlines() if not _SECTION_HEADER.match(ln)]
    return "\n".join(lines).strip()


def fingerprint(message: str) -> str:
    """Normalise a failure message to a grouping key."""
    msg = _strip_section_headers(message or "")
    m = re.search(r"The last error was:\s*(.+)", msg, re.S)
    if m:
        msg = m.group(1).strip()
    msg = re.sub(r"'[^']{0,80}'", "<val>", msg)
    msg = re.sub(r'"[^"]{0,80}"', "<val>", msg)
    msg = re.sub(r"\b\d+\b", "N", msg)
    msg = re.sub(r"[A-Z]{2,}-\d+", "<ticket>", msg)
    msg = re.sub(r"\s+", " ", msg).strip()
    return msg[:200]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ScoredTest:
    area: str
    suite: str
    name: str
    tags: list[str]
    message: str
    failure_type: str
    priority: str
    severity: str
    defect_ids: list[str]
    is_quarantined: bool
    fp: str
    base_score: int
    xml_path: str = ""
    group_bonus: int = 0
    api_endpoint: Optional[str] = None   # set when failure is a Wrong response code
    escalated: bool = False              # True when score was forced by API escalation
    received_code: Optional[int] = None  # HTTP status code actually returned
    response_error: Optional[str] = None # extracted error from response body

    @property
    def score(self) -> int:
        return max(0, min(100, self.base_score + self.group_bonus))


@dataclass
class TriageItem:
    """One entry in the triage queue — a failure group to investigate."""
    rank: int
    score: int
    priority_label: str          # P1 / P2 / P3 / P4
    failure_count: int
    areas_affected: list[str]
    failure_type: str
    failure_pattern: str         # human-readable normalised root cause
    representative_test: str     # best single test to start with
    xml_path: str                # output.xml to load_result_file first
    investigation_hints: list[str]
    api_endpoints: list[str]     # non-empty when failure is a Wrong response code
    escalated: bool              # True when score was forced by API escalation rule


@dataclass
class MatrixResult:
    total_failures: int
    total_groups: int
    markdown: str
    output_path: Optional[str]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def _parse_tags(tags) -> tuple[str, str, list[str], bool]:
    priority = "medium"
    severity = "medium"
    defect_ids: list[str] = []
    quarantined = False
    for tag in tags:
        tl = tag.lower()
        if tl.startswith("priority="):
            priority = tl.split("=", 1)[1]
        elif tl.startswith("severity="):
            severity = tl.split("=", 1)[1]
        elif tl.startswith("defectid="):
            val = tag.split("=", 1)[1]
            if val.lower() not in ("invalid", ""):
                defect_ids.append(val)
        elif "quarantine" in tl:
            quarantined = True
    return priority, severity, defect_ids, quarantined


def _base_score(priority: str, severity: str, defect_ids: list[str],
                quarantined: bool, failure_type: str,
                api_escalation: Optional[int] = None) -> tuple[int, bool]:
    """Return (score, escalated).

    When *api_escalation* is provided the score is forced to that value
    regardless of tags — a broken endpoint is always top-of-queue.
    """
    score = 50
    score += PRIORITY_SCORE.get(priority, 0)
    score += SEVERITY_SCORE.get(severity, 0)
    if defect_ids:
        score += DEFECT_PENALTY
    if quarantined:
        score += QUARANTINE_BONUS
    if failure_type == "infra-keyword":
        score += INFRA_KW_PENALTY
    elif failure_type == "infra-setup":
        score += INFRA_SETUP_PENALTY
    elif failure_type == "setup-other":
        score += SETUP_OTHER_PENALTY

    if api_escalation is not None:
        return api_escalation, True
    return score, False


def _walk_tests(suite):
    for t in suite.tests:
        yield t
    for s in suite.suites:
        yield from _walk_tests(s)


# ---------------------------------------------------------------------------
# Investigation hint generation
# ---------------------------------------------------------------------------
_HINT_RULES: list[tuple[str, str]] = [
    (r"server error occurred|Internal Server Error|5\d\d",
     "Backend returning a server error — check recent API/service changes in the affected area."),
    (r"wrong response code|expected N but received N",
     "API response code mismatch — check for contract changes (auth, routing, permissions)."),
    (r"element.*not visible|not visible after N seconds",
     "UI element not rendering in time — could be a CSS/JS regression or a timing issue introduced recently."),
    (r"element.*not found|No element with locator",
     "Locator no longer resolves — check for DOM structure changes or renamed identifiers."),
    (r"page should have contained N element.*but it did contain N",
     "Element count mismatch — the page is rendering a different number of items than expected. Likely a data or UI render regression."),
    (r"stale element|stale element reference",
     "Stale element reference — the page is navigating or re-rendering unexpectedly. Check for async/timing changes."),
    (r"cell.*in generated report|generated report has N more populated",
     "Report generation regression — output data or formatting has changed. Compare with a passing run."),
    (r"chunkedencoding|Response ended prematurely",
     "Network/streaming issue — the server closed the connection early. Check for timeouts or large-response handling."),
    (r"connection status|Device ID",
     "Device connectivity data mismatch — check device status propagation and backend sync."),
    (r"deadlock detected|OperationalError|psycopg",
     "Database deadlock or connection failure during setup — likely a test data conflict rather than a product regression."),
    (r"No keyword with name|No keyword named",
     "Missing keyword — a library or resource file was not imported. This is a test infrastructure issue, not a product regression."),
    (r"N != N|should be true|should be equal",
     "Data assertion failure — a value returned by the system doesn't match the expected value. Check recent business logic changes."),
    (r"text of element.*should have been",
     "UI text regression — displayed text has changed. Check recent copy or i18n changes."),
    (r"search results retrieved|No search results",
     "Search/filter returning unexpected results — likely a backend query or indexing regression."),
]


def _investigation_hints(fp: str, failure_type: str) -> list[str]:
    hints = []
    for pattern, hint in _HINT_RULES:
        if re.search(pattern, fp, re.I):
            hints.append(hint)
            break
    if not hints:
        hints.append("Review the keyword trace for the representative test to identify the failure point.")
    if failure_type == "functional":
        hints.append("Load the representative test's output.xml then call get_keyword_trace to pinpoint the exact step.")
    elif failure_type.startswith("infra"):
        hints.append("This looks like a test infrastructure issue — confirm before raising a product defect.")
    return hints


def _priority_label(score: int) -> str:
    if score >= 70:
        return "P1"
    if score >= 55:
        return "P2"
    if score >= 40:
        return "P3"
    return "P4"


# ---------------------------------------------------------------------------
# Shared loader
# ---------------------------------------------------------------------------
def _parse_xml_to_scored_tests(results_dir: str, area_filter: str) -> list[ScoredTest]:
    """Parse output.xml files and return ScoredTest objects (no group bonuses applied)."""
    failures: list[ScoredTest] = []
    for folder in sorted(os.listdir(results_dir)):
        if area_filter and area_filter.lower() not in folder.lower():
            continue
        xml_path = os.path.join(results_dir, folder, "robot", "output.xml")
        if not os.path.exists(xml_path):
            continue
        try:
            result = ExecutionResult(xml_path)
        except DataError:
            continue
        area = folder.replace("Product_", "").replace("_", " ")
        for t in _walk_tests(result.suite):
            if t.status != "FAIL":
                continue
            msg = t.message or ""
            priority, severity, defect_ids, quarantined = _parse_tags(t.tags)
            ft = classify_failure(msg)
            fp = fingerprint(msg)
            suite_name = t.parent.name if t.parent else ""
            is_api = is_api_response_failure(msg)
            api_ep = extract_api_endpoint(msg) if is_api else None
            rx_code = extract_received_code(msg) if is_api else None
            resp_err = extract_response_error(msg) if is_api else None
            escalation = _api_escalation_score(rx_code) if is_api else None
            score, escalated = _base_score(
                priority, severity, defect_ids, quarantined, ft,
                api_escalation=escalation,
            )
            failures.append(ScoredTest(
                area=area,
                suite=suite_name,
                name=t.name,
                tags=list(t.tags),
                message=msg,
                failure_type=ft,
                priority=priority,
                severity=severity,
                defect_ids=defect_ids,
                is_quarantined=quarantined,
                fp=fp,
                xml_path=xml_path,
                base_score=score,
                api_endpoint=api_ep,
                escalated=escalated,
                received_code=rx_code,
                response_error=resp_err,
            ))
    return failures


def _load_scored_tests(results_dir: str, area_filter: str) -> list[ScoredTest]:
    """Load scored tests — from DB if current, else parse XML directly."""
    from . import db as _db
    run_id = _db.get_current_run_id(results_dir)
    if run_id is not None:
        return _db.load_scored_tests(results_dir, run_id, area_filter)
    return _parse_xml_to_scored_tests(results_dir, area_filter)


def ingest_results(results_dir: str) -> dict:
    """
    Parse all output.xml files in *results_dir* and write results to SQLite.

    Idempotent — if nothing has changed since the last ingest this returns
    immediately without re-parsing.  Always ingests ALL areas (no filter) so
    the DB can serve any subsequent area_filter at query time.

    Returns:
        {run_id, ingested, already_current, total_failures}
    """
    from . import db as _db

    if not os.path.isdir(results_dir):
        raise FileNotFoundError(f"Results directory not found: {results_dir}")

    # Check idempotency before doing any XML work
    if _db.db_exists(results_dir):
        run_id = _db.get_current_run_id(results_dir)
        if run_id is not None:
            return {
                "run_id": run_id,
                "ingested": False,
                "already_current": True,
                "total_failures": None,
            }

    # Parse all XML (no area filter — ingest everything)
    failures = _parse_xml_to_scored_tests(results_dir, area_filter="")
    return _db.ingest(results_dir, failures)


def _assign_group_bonuses(failures: list[ScoredTest]) -> dict[str, list[ScoredTest]]:
    groups: dict[str, list[ScoredTest]] = defaultdict(list)
    for f in failures:
        groups[f.fp].append(f)
    for members in groups.values():
        bonus = min((len(members) - 1) * GROUP_BONUS_PER_EXTRA, GROUP_BONUS_CAP)
        for m in members:
            m.group_bonus = bonus
    return groups


# ---------------------------------------------------------------------------
# Triage queue
# ---------------------------------------------------------------------------
def triage_queue(
    results_dir: str,
    area_filter: str = "",
    top_n: int = 15,
    exclude_known_defects: bool = True,
    exclude_infra: bool = True,
) -> list[TriageItem]:
    """
    Return a prioritised investigation queue from *results_dir*.

    Each entry is a failure group (tests sharing the same root cause).
    Groups are ranked by score and enriched with:
    - which output.xml to load_result_file first
    - the best representative test to start with
    - investigation hints

    Args:
        results_dir: Directory whose children each contain robot/output.xml.
        area_filter: Optional substring to filter folder names.
        top_n: Maximum number of groups to return.
        exclude_known_defects: If True, skip groups where every test has a defectid= tag.
        exclude_infra: If True, skip pure infra-keyword failures.
    """
    if not os.path.isdir(results_dir):
        raise FileNotFoundError(f"Results directory not found: {results_dir}")

    failures = _load_scored_tests(results_dir, area_filter)
    groups = _assign_group_bonuses(failures)

    queue: list[TriageItem] = []
    rank = 0

    sorted_groups = sorted(
        groups.items(),
        key=lambda kv: -(sum(m.score for m in kv[1]) / len(kv[1])),
    )

    for fp, members in sorted_groups:
        avg_score = int(sum(m.score for m in members) / len(members))
        ft = members[0].failure_type
        all_infra_kw = all(m.failure_type == "infra-keyword" for m in members)
        all_known = all(bool(m.defect_ids) or m.is_quarantined for m in members)

        if exclude_infra and all_infra_kw:
            continue
        if exclude_known_defects and all_known:
            continue

        # Pick representative test: functional > not quarantined > shortest name
        candidates = sorted(
            members,
            key=lambda m: (
                0 if m.failure_type == "functional" else 1,
                1 if (m.defect_ids or m.is_quarantined) else 0,
                len(m.name),
            ),
        )
        rep = candidates[0]

        areas = sorted({m.area for m in members})
        hints = _investigation_hints(fp, ft)

        # Collect unique API endpoints touched by this group
        api_endpoints = sorted({
            m.api_endpoint for m in members if m.api_endpoint
        })
        group_escalated = any(m.escalated for m in members)

        rank += 1
        queue.append(TriageItem(
            rank=rank,
            score=avg_score,
            priority_label=_priority_label(avg_score),
            failure_count=len(members),
            areas_affected=areas,
            failure_type=ft,
            failure_pattern=fp,
            representative_test=rep.name,
            xml_path=rep.xml_path,
            investigation_hints=hints,
            api_endpoints=api_endpoints,
            escalated=group_escalated,
        ))

        if rank >= top_n:
            break

    return queue


def get_group_tests(
    results_dir: str,
    failure_pattern: str,
    area_filter: str = "",
) -> list[dict]:
    """Return the full test list for one failure group identified by its fingerprint.

    Called on demand when the user wants to see all tests in a group —
    kept separate from triage_queue so the initial queue payload stays small.

    Returns a list of dicts: [{name, area, xml_path, api_endpoint}].
    """
    if not os.path.isdir(results_dir):
        raise FileNotFoundError(f"Results directory not found: {results_dir}")

    failures = _load_scored_tests(results_dir, area_filter)
    return [
        {
            "name": f.name,
            "area": f.area,
            "xml_path": f.xml_path,
            "api_endpoint": f.api_endpoint,
        }
        for f in failures
        if f.fp == failure_pattern
    ]


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------
def analyse(results_dir: str, area_filter: str = "", output_path: Optional[str] = None) -> MatrixResult:
    """
    Scan *results_dir* for Robot Framework output.xml files, score every
    failing test, and produce a prioritised report.

    Output format is determined by *output_path* extension:
    - ``.html`` → interactive HTML report with chart and collapsible sections
    - anything else (or no path) → Markdown

    Args:
        results_dir: Directory whose immediate children each contain a
                     ``robot/output.xml`` file.
        area_filter: Optional substring filter applied to folder names.
        output_path: If provided, the report is written to this file.
    """
    if not os.path.isdir(results_dir):
        raise FileNotFoundError(f"Results directory not found: {results_dir}")

    failures = _load_scored_tests(results_dir, area_filter)
    groups = _assign_group_bonuses(failures)
    area_label = area_filter or "All Areas"

    if output_path and output_path.lower().endswith(".html"):
        from .html_report import render_html
        content = render_html(failures, groups, area_label)
    else:
        content = _render_md(failures, groups, area_label)

    written_path: Optional[str] = None
    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        written_path = output_path

    return MatrixResult(
        total_failures=len(failures),
        total_groups=len(groups),
        markdown=content,
        output_path=written_path,
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------
def _band(score: int) -> str:
    if score >= 75:
        return "🔴 Critical"
    if score >= 55:
        return "🟠 High"
    if score >= 35:
        return "🟡 Medium"
    return "🟢 Low"


def _ft_label(ft: str) -> str:
    return {
        "infra-keyword": "⚙️ Missing keyword",
        "infra-setup":   "⚙️ Infra setup",
        "setup-other":   "⚙️ Setup issue",
        "functional":    "🐛 Functional",
    }.get(ft, ft)


_SKIP_LINE = re.compile(r"^(Setup failed|Suite setup failed|Test setup failed)\s*:?\s*$", re.I)


def _short(msg: str, n: int = 110) -> str:
    cleaned = _strip_section_headers(msg)
    first = next(
        (ln.strip() for ln in cleaned.splitlines() if ln.strip() and not _SKIP_LINE.match(ln.strip())),
        "",
    )
    return (first[:n] + "…") if len(first) > n else first


def _render_md(failures: list[ScoredTest], groups: dict[str, list[ScoredTest]], area_label: str) -> str:
    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines += [
        f"# Robot Framework Failure Matrix — {area_label}",
        "",
        f"_Generated: {now}_",
        "",
    ]

    # --- Area summary ---
    area_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "functional": 0, "infra": 0, "known": 0})
    for f in failures:
        s = area_stats[f.area]
        s["total"] += 1
        if f.failure_type == "functional":
            s["functional"] += 1
        elif f.failure_type.startswith("infra"):
            s["infra"] += 1
        if f.defect_ids or f.is_quarantined:
            s["known"] += 1

    lines += [
        "## Area Summary",
        "",
        "| Area | Failures | Functional | Infra/Setup | Known Defect |",
        "|------|----------|------------|-------------|--------------|",
    ]
    for area, c in sorted(area_stats.items(), key=lambda x: -x[1]["total"]):
        lines.append(f"| {area} | {c['total']} | {c['functional']} | {c['infra']} | {c['known']} |")
    lines.append("")

    # --- API escalation section ---
    api_failures = [f for f in failures if f.escalated]
    if api_failures:
        lines += [
            "## API Response Failures (Escalated)",
            "",
            "> These tests received a **Wrong response code** from the backend.",
            "> Investigate these before anything else — a broken endpoint affects every test that touches it.",
            "",
        ]
        # Group by endpoint key (method + url + codes) so all tests hitting the same
        # broken endpoint appear together under one heading.
        ep_groups: dict[str, list[ScoredTest]] = defaultdict(list)
        for f in api_failures:
            ep_groups[f.api_endpoint or "Unknown endpoint"].append(f)

        # Sort endpoint groups: highest max-score first, then by received code (5xx > 4xx)
        def _ep_sort_key(kv: tuple[str, list[ScoredTest]]) -> tuple[int, int]:
            members = kv[1]
            max_score = max(m.score for m in members)
            rx = members[0].received_code or 0
            return (-max_score, 0 if rx >= 500 else 1)

        for endpoint, ep_tests in sorted(ep_groups.items(), key=_ep_sort_key):
            # Use the best response_error from any member; prefer the one from the highest-score test
            rep = max(ep_tests, key=lambda f: f.score)
            error_text = rep.response_error
            if not error_text:
                # Try other members
                error_text = next((f.response_error for f in ep_tests if f.response_error), None)
            fallback_msg = _short(rep.message)
            display_error = error_text or fallback_msg

            rx_code = rep.received_code
            code_label = f"HTTP {rx_code}" if rx_code else ""

            lines += [
                f"### {endpoint}",
                "",
                f"**{code_label} Error**: {display_error}",
                "",
                "| Score | Test | Area |",
                "|-------|------|------|",
            ]
            for f in sorted(ep_tests, key=lambda x: -x.score):
                name = f.name[:80].replace("|", "\\|")
                lines.append(f"| {f.score} | {name} | {f.area} |")
            lines.append("")

    # --- Scoring key ---
    lines += [
        "## Scoring Key",
        "",
        "Score 0–100. **Higher = needs more immediate attention.**",
        "",
        "| Factor | Points |",
        "|--------|--------|",
        "| **API escalation** — 5xx server error | **forced 92** |",
        "| **API escalation** — 4xx client error (exc. 403) | **forced 87** |",
        "| **API escalation** — 403 Forbidden | **forced 80** |",
        "| Priority / Severity - critical | +40 each |",
        "| Priority / Severity - high | +25 each |",
        "| Priority / Severity - medium (default for untagged) | 0 |",
        "| Priority / Severity - low | -20 each |",
        "| Has `defectid=` tag (tracked defect) | -25 |",
        "| Has `quarantine-*` tag (flagged risk, needs attention) | +10 |",
        "| Infra failure: missing keyword / library | -30 |",
        "| Infra failure: connection / deadlock in setup | -20 |",
        "| Other setup failure | -10 |",
        "| Shared failure fingerprint: +5 per extra test in group | up to +20 |",
        "",
    ]

    # --- Failure groups ---
    sorted_groups = sorted(
        groups.items(),
        key=lambda kv: -(sum(m.score for m in kv[1]) / len(kv[1])),
    )

    lines += [
        "## Failure Groups (Ranked by Average Score)",
        "",
        "Tests sharing the same root-cause fingerprint are grouped together. "
        "A larger group earns a higher score — widespread failures need more attention. "
        "Groups marked **[API]** were escalated due to wrong response code.",
        "",
        "| Rank | Avg Score | Band | Count | Areas Affected | Type | Root Cause Fingerprint |",
        "|------|-----------|------|-------|----------------|------|------------------------|",
    ]
    for rank, (fp, members) in enumerate(sorted_groups, 1):
        avg = int(sum(m.score for m in members) / len(members))
        areas = sorted({m.area for m in members})
        areas_str = ", ".join(areas[:3]) + (f" +{len(areas)-3}" if len(areas) > 3 else "")
        types = {m.failure_type for m in members}
        ft_str = _ft_label(next(iter(types))) if len(types) == 1 else "Mixed"
        fp_short = (fp[:85] + "…") if len(fp) > 85 else fp
        escalated_marker = " **[API]**" if any(m.escalated for m in members) else ""
        lines.append(
            f"| {rank} | {avg}{escalated_marker} | {_band(avg)} | {len(members)} "
            f"| {areas_str} | {ft_str} | `{fp_short}` |"
        )
    lines.append("")

    # --- Full test matrix ---
    lines += [
        "## Test Detail Matrix",
        "",
        "Sorted highest score first.",
        "",
        "| Score | Band | Test | Area | Priority | Severity | Defect IDs | Type | Failure Message |",
        "|-------|------|------|------|----------|----------|------------|------|-----------------|",
    ]
    for f in sorted(failures, key=lambda x: -x.score):
        defects = ", ".join(f.defect_ids) if f.defect_ids else ("quarantined" if f.is_quarantined else "—")
        pri = f.priority
        sev = f.severity
        msg = _short(f.message).replace("|", "\\|")
        name = f.name[:65].replace("|", "\\|")
        score_cell = f"{f.score} **[API]**" if f.escalated else str(f.score)
        lines.append(
            f"| {score_cell} | {_band(f.score)} | {name} | {f.area} "
            f"| {pri} | {sev} | {defects} | {_ft_label(f.failure_type)} | {msg} |"
        )
    lines.append("")

    # --- Distribution ---
    dist: dict[str, int] = {"🔴 Critical": 0, "🟠 High": 0, "🟡 Medium": 0, "🟢 Low": 0}
    for f in failures:
        dist[_band(f.score)] += 1

    lines += [
        "## Score Distribution",
        "",
        "| Band | Count |",
        "|------|-------|",
    ]
    for band, count in dist.items():
        lines.append(f"| {band} | {count} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Debug context — maps a single test to an optional debug skill's workflow
# ---------------------------------------------------------------------------

def _load_area_categories() -> list[tuple[str, str, list[str]]]:
    """Load area→category mappings from a JSON config file.

    Checks (in order):
      1. RF_AREA_CATEGORIES env var — path to a JSON file
      2. area_categories.json next to the package root
      3. area_categories.json in cwd

    Each entry in the JSON array must have:
      { "folder_fragment": str, "category": str, "hints": [str, ...] }

    Returns an empty list if no config is found, which causes all areas to
    fall through to the GENERIC category.
    """
    config_path = os.environ.get("RF_AREA_CATEGORIES")
    if not config_path:
        module_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.normpath(os.path.join(module_dir, "..", "area_categories.json")),
            os.path.join(os.getcwd(), "area_categories.json"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                config_path = candidate
                break

    if not config_path or not os.path.exists(config_path):
        return []

    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        return [(item["folder_fragment"], item["category"], item.get("hints", [])) for item in data]
    except Exception:
        return []


# Maps (folder-name fragment) → (debug category, [product file hints]).
# Loaded from area_categories.json at startup; empty list = everything → GENERIC.
_AREA_CATEGORY: list[tuple[str, str, list[str]]] = _load_area_categories()

_MSG_CATEGORY: list[tuple[str, str, list[str]]] = [
    (r"403|401|access.?denied|unauthorized",
     "ROLES-AUTH", []),
    (r"no keyword with name|no keyword named",
     "KEYWORD-NOT-FOUND", []),
    (r"database.*timeout|connection.*timed.?out",
     "DB-TIMEOUT", []),
    (r"stale element reference|wait until element|element.*not visible after|elementnotfound",
     "ELEMENT-TIMEOUT", []),
    (r"variable.*(?:none|null|not set|not found)",
     "CONFIG-MISSING", []),
]


def _classify_to_skill_category(xml_path: str, message: str, tags: list[str]) -> tuple[str, list[str]]:
    """Return (debug_category, [product_file_hints]) for the robot-tests debug skill."""
    folder = os.path.basename(os.path.dirname(os.path.dirname(xml_path)))

    # Message-level overrides that apply regardless of area
    msg_lower = (message or "").lower()
    for pattern, cat, hints in _MSG_CATEGORY:
        if re.search(pattern, msg_lower):
            return cat, hints

    # Area-based routing
    for frag, cat, hints in _AREA_CATEGORY:
        if frag.lower() in folder.lower():
            return cat, hints

    return "GENERIC", []


def _extract_kw_message(kw) -> str:
    """Extract the failure message from a keyword node in RF 6.

    RF 6 stores error text as child Message objects (type='MESSAGE', level='FAIL')
    inside the keyword body rather than on keyword.message directly.
    """
    # Try direct attribute first (older RF or wrapped keywords)
    direct = getattr(kw, "message", None)
    if direct:
        return str(direct).strip()

    # Walk body for FAIL-level Message children
    for child in getattr(kw, "body", None) or []:
        child_type = getattr(child, "type", "")
        if child_type == "MESSAGE" and getattr(child, "level", "") == "FAIL":
            return str(getattr(child, "message", "") or "").strip()

    return ""


def _walk_keyword_tree(kw, depth: int = 0) -> list[dict]:
    """Recursively extract keyword entries from a RF 6 keyword node."""
    entries: list[dict] = []
    name = getattr(kw, "name", "") or ""
    if not name:
        return entries

    status = getattr(kw, "status", "")
    message = _extract_kw_message(kw)

    entries.append({
        "name": name,
        "type": getattr(kw, "type", "KEYWORD"),
        "status": status,
        "message": message,
        "depth": depth,
    })

    body = getattr(kw, "body", None) or []
    for child in body:
        if hasattr(child, "name") and hasattr(child, "status"):
            entries.extend(_walk_keyword_tree(child, depth + 1))

    return entries


def _fail_path_trace(kw, depth: int = 0) -> list[dict]:
    """Return only the FAIL path through the keyword tree.

    For each keyword on the path: include it plus any PASS siblings at the
    same level as one-line context entries (no children expanded for PASS nodes).
    This keeps the trace diagnostic without including every passing sub-keyword.
    """
    entries: list[dict] = []
    name = getattr(kw, "name", "") or ""
    if not name:
        return entries

    status = getattr(kw, "status", "")
    message = _extract_kw_message(kw)

    entries.append({
        "name": name,
        "type": getattr(kw, "type", "KEYWORD"),
        "status": status,
        "message": message,
        "depth": depth,
    })

    if status != "FAIL":
        # PASS / NOT RUN node: include as context but don't recurse
        return entries

    # FAIL node: recurse into children, but only expand the failing child
    body = getattr(kw, "body", None) or []
    children = [c for c in body if hasattr(c, "name") and hasattr(c, "status")]

    has_failing_child = any(getattr(c, "status", "") == "FAIL" for c in children)

    for child in children:
        child_status = getattr(child, "status", "")
        if child_status == "FAIL" or not has_failing_child:
            # Recurse into the failing child; expand all children if none failed
            entries.extend(_fail_path_trace(child, depth + 1))
        else:
            # Sibling PASS node: include as one-line context, no recursion
            child_name = getattr(child, "name", "") or ""
            if child_name:
                entries.append({
                    "name": child_name,
                    "type": getattr(child, "type", "KEYWORD"),
                    "status": child_status,
                    "message": "",
                    "depth": depth + 1,
                })

    return entries


def _find_test(suite, test_name: str):
    """Find a test case by name or longname (recursive).

    Mirrors the disambiguation logic in RobotResultParser._find_test_case:
    exact match wins; falls back to a unique partial longname match; returns
    None if not found or if multiple tests match the partial name.
    """
    all_tests = list(_walk_tests(suite))

    exact = [t for t in all_tests if t.name == test_name or getattr(t, "longname", None) == test_name]
    if len(exact) == 1:
        return exact[0]

    partial = [t for t in all_tests if test_name in getattr(t, "longname", "")]
    if len(partial) == 1:
        return partial[0]

    return None


@dataclass
class DebugContext:
    """Everything the robot-tests debug skill needs to start Step 2 without manual log reading."""
    test_name: str
    suite_path: str
    area: str
    status: str
    failure_message: str
    tags: list[str]
    priority: str
    severity: str
    defect_ids: list[str]
    is_quarantined: bool
    # Skill routing
    debug_category: str
    product_file_hints: list[str]
    # Full keyword call stack
    keyword_trace: list[dict]
    # The deepest failing keyword — the proximate cause the skill needs
    innermost_failure: Optional[dict]
    # Restatement of infrastructure vs functional classification
    failure_type: str


def prepare_debug_context(xml_path: str, test_name: str) -> DebugContext:
    """
    Load *xml_path*, locate *test_name*, and return a DebugContext ready
    for the robot-tests debug skill.

    The returned object pre-answers the skill's Step 1 (read the failure)
    and Step 2 (classify), so the skill can jump straight to Step 3 (resolve).

    Args:
        xml_path: Absolute path to a Robot Framework output.xml file.
        test_name: Exact or partial test case name (matches name or longname).
    """
    if not os.path.exists(xml_path):
        raise FileNotFoundError(f"output.xml not found: {xml_path}")

    try:
        result = ExecutionResult(xml_path)
    except DataError as exc:
        raise ValueError(f"Cannot parse output.xml: {xml_path}") from exc

    test = _find_test(result.suite, test_name)
    if test is None:
        raise ValueError(f"Test not found in {xml_path}: {test_name!r}")

    message = test.message or ""
    tags = list(test.tags)
    priority, severity, defect_ids, quarantined = _parse_tags(tags)
    failure_type = classify_failure(message)

    # Build suite path for context
    segments: list[str] = []
    node = test.parent
    while node and getattr(node, "name", None):
        segments.insert(0, node.name)
        node = getattr(node, "parent", None)
    suite_path = " > ".join(segments)

    # Keyword trace — fail path only; PASS siblings included as one-liners
    body = getattr(test, "body", None) or []
    trace: list[dict] = []
    for kw in body:
        if hasattr(kw, "name") and hasattr(kw, "status"):
            trace.extend(_fail_path_trace(kw, depth=0))

    # Innermost failing keyword = deepest FAIL in the trace.
    # RF 6 stores the error text on the test (not the keyword), so copy it
    # onto the innermost entry so the debug skill has everything in one place.
    failed = [e for e in trace if e.get("status") == "FAIL"]
    innermost = max(failed, key=lambda e: e["depth"]) if failed else None
    if innermost and not innermost.get("message"):
        innermost = dict(innermost)
        innermost["message"] = message

    # Extract folder for area label
    folder = os.path.basename(os.path.dirname(os.path.dirname(xml_path)))
    area = folder.replace("Product_", "").replace("_", " ")

    debug_category, product_file_hints = _classify_to_skill_category(xml_path, message, tags)

    return DebugContext(
        test_name=test.name,
        suite_path=suite_path,
        area=area,
        status=test.status,
        failure_message=message,
        tags=tags,
        priority=priority,
        severity=severity,
        defect_ids=defect_ids,
        is_quarantined=quarantined,
        debug_category=debug_category,
        product_file_hints=product_file_hints,
        keyword_trace=trace,
        innermost_failure=innermost,
        failure_type=failure_type,
    )
