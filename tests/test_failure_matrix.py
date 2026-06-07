"""Unit tests for failure_matrix.py core functions."""
import pytest

from robot_mcp_server.failure_matrix import (
    _api_escalation_score,
    _base_score,
    _investigation_hints,
    _parse_tags,
    _priority_label,
    API_ESCALATION_4XX,
    API_ESCALATION_5XX,
    API_ESCALATION_403,
    classify_failure,
    extract_api_endpoint,
    extract_received_code,
    extract_response_error,
    fingerprint,
    is_api_response_failure,
    prepare_debug_context,
)


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------

class TestFingerprint:
    def test_strips_quoted_values(self):
        fp = fingerprint("Expected 'foo' but got 'bar'")
        assert "foo" not in fp
        assert "bar" not in fp
        assert "<val>" in fp

    def test_normalises_numbers(self):
        fp = fingerprint("Expected 42 but got 99")
        assert "42" not in fp
        assert "99" not in fp
        assert "N" in fp

    def test_normalises_ticket_ids(self):
        # Numbers are replaced before the ticket pattern runs, so PROJ-1234 → PROJ-N.
        fp = fingerprint("Blocked by PROJ-1234 still open")
        assert "1234" not in fp

    def test_collapses_whitespace(self):
        fp = fingerprint("some   message   here")
        assert "  " not in fp

    def test_truncates_at_200(self):
        long_msg = "x" * 300
        assert len(fingerprint(long_msg)) <= 200

    def test_strips_section_headers(self):
        msg = "**FAILURE REASON**\nActual failure text"
        fp = fingerprint(msg)
        assert "FAILURE REASON" not in fp
        assert "Actual failure text" in fp

    def test_empty_string(self):
        assert fingerprint("") == ""

    def test_none_handled(self):
        assert fingerprint(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# classify_failure
# ---------------------------------------------------------------------------

class TestClassifyFailure:
    def test_infra_keyword_no_keyword(self):
        assert classify_failure("No keyword with name 'Missing Kw'") == "infra-keyword"

    def test_infra_keyword_import_error(self):
        assert classify_failure("ImportError: cannot import name 'foo'") == "infra-keyword"

    def test_infra_setup_connection(self):
        assert classify_failure("Setup failed\nconnection refused") == "infra-setup"

    def test_infra_setup_deadlock(self):
        assert classify_failure("Setup failed\ndeadlock detected in pg") == "infra-setup"

    def test_setup_other(self):
        assert classify_failure("Setup failed\nSome other setup problem") == "setup-other"

    def test_functional(self):
        assert classify_failure("Expected 42 but got 43") == "functional"

    def test_functional_element_not_found(self):
        assert classify_failure("Element with locator 'id:foo' not found") == "functional"


# ---------------------------------------------------------------------------
# _parse_tags
# ---------------------------------------------------------------------------

class TestParseTags:
    def test_defaults(self):
        priority, severity, defects, quarantined = _parse_tags([])
        assert priority == "medium"
        assert severity == "medium"
        assert defects == []
        assert quarantined is False

    def test_priority_and_severity(self):
        priority, severity, _, _ = _parse_tags(["priority=critical", "severity=high"])
        assert priority == "critical"
        assert severity == "high"

    def test_defect_id(self):
        _, _, defects, _ = _parse_tags(["defectid=PROJ-123"])
        assert defects == ["PROJ-123"]

    def test_invalid_defect_id_ignored(self):
        _, _, defects, _ = _parse_tags(["defectid=invalid"])
        assert defects == []

    def test_quarantine_tag(self):
        _, _, _, quarantined = _parse_tags(["quarantine-flaky"])
        assert quarantined is True

    def test_low_priority(self):
        priority, _, _, _ = _parse_tags(["priority=low"])
        assert priority == "low"


# ---------------------------------------------------------------------------
# _base_score
# ---------------------------------------------------------------------------

class TestBaseScore:
    def test_default_medium_medium(self):
        score, escalated = _base_score("medium", "medium", [], False, "functional")
        assert score == 50
        assert escalated is False

    def test_critical_critical(self):
        score, _ = _base_score("critical", "critical", [], False, "functional")
        assert score == 50 + 40 + 40  # 130 — clamped by ScoredTest.score property

    def test_defect_penalty(self):
        score, _ = _base_score("medium", "medium", ["PROJ-1"], False, "functional")
        assert score == 50 - 25

    def test_infra_keyword_penalty(self):
        score, _ = _base_score("medium", "medium", [], False, "infra-keyword")
        assert score == 50 - 30

    def test_infra_setup_penalty(self):
        score, _ = _base_score("medium", "medium", [], False, "infra-setup")
        assert score == 50 - 20

    def test_setup_other_penalty(self):
        score, _ = _base_score("medium", "medium", [], False, "setup-other")
        assert score == 50 - 10

    def test_api_escalation_overrides(self):
        score, escalated = _base_score("low", "low", [], False, "functional", api_escalation=92)
        assert score == 92
        assert escalated is True

    def test_low_priority_penalty(self):
        score, _ = _base_score("low", "low", [], False, "functional")
        assert score == 50 - 20 - 20  # 10


# ---------------------------------------------------------------------------
# _priority_label
# ---------------------------------------------------------------------------

class TestPriorityLabel:
    def test_p1(self):
        assert _priority_label(70) == "P1"
        assert _priority_label(100) == "P1"

    def test_p2(self):
        assert _priority_label(55) == "P2"
        assert _priority_label(69) == "P2"

    def test_p3(self):
        assert _priority_label(40) == "P3"
        assert _priority_label(54) == "P3"

    def test_p4(self):
        assert _priority_label(0) == "P4"
        assert _priority_label(39) == "P4"


# ---------------------------------------------------------------------------
# API response failure detection
# ---------------------------------------------------------------------------

_WRONG_CODE_MSG = (
    "Wrong response code received (expected 200 but received 500)\n"
    "**SENT DETAILS**\n"
    "URL: https://api.example.com/v1/resource\n"
    "Method: GET\n"
    "**RESPONSE DETAILS**\n"
    "Reason: Internal Server Error\n"
    'Response Body: {"Message": "Something went wrong"}\n'
)


class TestApiResponseFailure:
    def test_detects_wrong_response_code(self):
        assert is_api_response_failure(_WRONG_CODE_MSG) is True

    def test_ignores_non_api_message(self):
        assert is_api_response_failure("Expected 42 but got 43") is False

    def test_none_safe(self):
        assert is_api_response_failure(None) is False  # type: ignore[arg-type]


class TestExtractReceivedCode:
    def test_extracts_code(self):
        assert extract_received_code(_WRONG_CODE_MSG) == 500

    def test_extracts_4xx(self):
        msg = "Wrong response code received (expected 200 but received 404)"
        assert extract_received_code(msg) == 404

    def test_returns_none_for_non_api(self):
        assert extract_received_code("Something else") is None


class TestExtractApiEndpoint:
    def test_full_summary(self):
        ep = extract_api_endpoint(_WRONG_CODE_MSG)
        assert ep is not None
        assert "GET" in ep
        assert "https://api.example.com/v1/resource" in ep
        assert "expected 200" in ep
        assert "got 500" in ep

    def test_returns_none_for_non_api(self):
        assert extract_api_endpoint("Some unrelated failure") is None


class TestExtractResponseError:
    def test_extracts_json_message(self):
        err = extract_response_error(_WRONG_CODE_MSG)
        assert err == "Something went wrong"

    def test_falls_back_to_reason(self):
        msg = (
            "Wrong response code received (expected 200 but received 503)\n"
            "Reason: Service Unavailable\n"
        )
        assert extract_response_error(msg) == "Service Unavailable"

    def test_ignores_ok_reason(self):
        msg = (
            "Wrong response code received (expected 201 but received 400)\n"
            "Reason: OK\n"
        )
        assert extract_response_error(msg) is None

    def test_returns_none_when_nothing_useful(self):
        assert extract_response_error("Some failure with no structured body") is None


# ---------------------------------------------------------------------------
# _api_escalation_score
# ---------------------------------------------------------------------------

class TestApiEscalationScore:
    def test_5xx(self):
        assert _api_escalation_score(500) == API_ESCALATION_5XX
        assert _api_escalation_score(503) == API_ESCALATION_5XX

    def test_403(self):
        assert _api_escalation_score(403) == API_ESCALATION_403

    def test_other_4xx(self):
        assert _api_escalation_score(404) == API_ESCALATION_4XX
        assert _api_escalation_score(400) == API_ESCALATION_4XX

    def test_none_is_conservative(self):
        # None means code was unparseable — should not max out at 5xx
        assert _api_escalation_score(None) == API_ESCALATION_4XX

    def test_ordering(self):
        assert API_ESCALATION_5XX > API_ESCALATION_4XX > API_ESCALATION_403


# ---------------------------------------------------------------------------
# _investigation_hints
# ---------------------------------------------------------------------------

class TestInvestigationHints:
    def test_server_error_hint(self):
        hints = _investigation_hints("server error occurred", "functional")
        assert any("server error" in h.lower() or "backend" in h.lower() for h in hints)

    def test_missing_keyword_hint(self):
        hints = _investigation_hints("No keyword with name 'Foo'", "infra-keyword")
        assert any("infrastructure" in h.lower() for h in hints)

    def test_functional_always_gets_keyword_trace_hint(self):
        hints = _investigation_hints("N != N", "functional")
        assert any("keyword_trace" in h or "keyword trace" in h.lower() for h in hints)

    def test_infra_gets_infra_hint(self):
        hints = _investigation_hints("deadlock detected", "infra-setup")
        assert any("infrastructure" in h.lower() for h in hints)

    def test_fallback_hint_when_no_pattern_matches(self):
        hints = _investigation_hints("completely unknown failure message xyz", "functional")
        assert len(hints) >= 1


# ---------------------------------------------------------------------------
# prepare_debug_context — integration test using sample XML
# ---------------------------------------------------------------------------

class TestPrepareDebugContext:
    def test_basic_fields(self):
        ctx = prepare_debug_context("examples/sample_output.xml", "Failing Test")
        assert ctx.test_name == "Failing Test"
        assert ctx.status == "FAIL"
        assert "42" in ctx.failure_message or "43" in ctx.failure_message
        assert ctx.failure_type == "functional"

    def test_keyword_trace_present(self):
        ctx = prepare_debug_context("examples/sample_output.xml", "Failing Test")
        assert len(ctx.keyword_trace) >= 1

    def test_innermost_failure_populated(self):
        ctx = prepare_debug_context("examples/sample_output.xml", "Failing Test")
        assert ctx.innermost_failure is not None
        assert ctx.innermost_failure["status"] == "FAIL"

    def test_debug_category_assigned(self):
        ctx = prepare_debug_context("examples/sample_output.xml", "Failing Test")
        assert ctx.debug_category  # non-empty string

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            prepare_debug_context("examples/does_not_exist.xml", "Any Test")

    def test_missing_test_raises(self):
        with pytest.raises(ValueError, match="not found"):
            prepare_debug_context("examples/sample_output.xml", "No Such Test")
