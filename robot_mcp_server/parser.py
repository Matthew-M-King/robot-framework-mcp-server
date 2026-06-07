from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Iterable, List, Optional

from robot.api import ExecutionResult
from robot.errors import DataError

from .models import (
    BugReportData,
    FailureGroup,
    FailedTestSummary,
    KeywordTraceEntry,
    RobotRunSummary,
    RunComparisonResult,
    TestDetails,
)


class RobotResultParser:
    """Parse Robot Framework output files and expose structured result objects."""

    def __init__(self) -> None:
        self._result: Optional[ExecutionResult] = None
        self._source_path: str = ""

    def parse_run(self, path: str) -> RobotRunSummary:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Robot Framework result file not found: {path}")

        try:
            result = ExecutionResult(path)
        except DataError as exc:
            raise ValueError(f"Invalid Robot Framework output XML: {path}") from exc

        self._result = result
        self._source_path = path

        stats = result.statistics.total
        total = getattr(stats, "total", 0)
        passed = getattr(stats, "passed", 0)
        failed = getattr(stats, "failed", 0)
        skipped = getattr(stats, "skipped", 0)

        return RobotRunSummary(
            total=int(total),
            passed=int(passed),
            failed=int(failed),
            skipped=int(skipped),
            elapsed_time_seconds=self._elapsed_seconds(result),
            start_time=self._parse_time(getattr(result, "starttime", None)),
            end_time=self._parse_time(getattr(result, "endtime", None)),
            source_path=path,
        )

    def get_failed_tests(self) -> List[FailedTestSummary]:
        self._ensure_loaded()
        return [self._build_test_summary(test) for test in self._iter_test_cases(self._result.suite) if test.status == "FAIL"]

    def get_test_details(self, test_name: str) -> TestDetails:
        self._ensure_loaded()
        case = self._find_test_case(test_name)
        keyword_trace = self._build_keyword_trace(case)
        failed_keyword = next((entry.keyword_name for entry in keyword_trace if entry.status == "FAIL"), None)

        return TestDetails(
            suite_path=self._build_suite_path(case.parent),
            test_name=case.name,
            status=case.status,
            message=self._extract_message(case.message),
            tags=list(case.tags or []),
            setup_status=getattr(getattr(case, "setup", None), "status", None),
            teardown_status=getattr(getattr(case, "teardown", None), "status", None),
            keyword_trace=keyword_trace,
            failed_keyword=failed_keyword,
            start_time=self._parse_time(getattr(case, "starttime", None)),
            end_time=self._parse_time(getattr(case, "endtime", None)),
            source=self._find_source_for_case(case),
        )

    def get_keyword_trace(self, test_name: str) -> List[KeywordTraceEntry]:
        self._ensure_loaded()
        case = self._find_test_case(test_name)
        return self._build_keyword_trace(case)

    def summarize_failures(self) -> List[FailureGroup]:
        self._ensure_loaded()
        failed_tests = self.get_failed_tests()
        groups: dict[str, list[FailedTestSummary]] = {}

        for summary in failed_tests:
            key = self._build_failure_group_key(summary)
            groups.setdefault(key, []).append(summary)

        failure_groups: List[FailureGroup] = []
        for index, (key, candidates) in enumerate(groups.items(), start=1):
            message_snippet = self._short_message_snippet(candidates[0].message)
            failed_keywords = sorted({self._extract_keyword_name(candidate.message) or "Unknown" for candidate in candidates})
            failure_groups.append(
                FailureGroup(
                    group_id=f"failure-group-{index}",
                    test_names=[candidate.full_name for candidate in candidates],
                    common_keyword=self._common_failed_keyword(candidates),
                    message_snippet=message_snippet,
                    failed_keywords=failed_keywords,
                    shared_tags=self._common_tags(candidates),
                )
            )

        return failure_groups

    def compare_with_previous_run(self, current_path: str, previous_path: str) -> RunComparisonResult:
        current = RobotResultParser()
        previous = RobotResultParser()
        current.parse_run(current_path)
        previous.parse_run(previous_path)

        current_failed = {test.full_name: test for test in current.get_failed_tests()}
        previous_failed = {test.full_name: test for test in previous.get_failed_tests()}

        current_names = set(current_failed)
        previous_names = set(previous_failed)

        new_failures = sorted(current_names - previous_names)
        repeated_failures = sorted(current_names & previous_names)
        fixed_tests = sorted(previous_names - current_names)
        consistent_failures = [name for name in repeated_failures if current_failed[name].message == previous_failed[name].message]

        return RunComparisonResult(
            new_failures=new_failures,
            repeated_failures=repeated_failures,
            fixed_tests=fixed_tests,
            consistent_failures=sorted(consistent_failures),
        )

    def generate_bug_report_data(self, test_name: str, artifacts: Optional[List[str]] = None) -> BugReportData:
        self._ensure_loaded()
        details = self.get_test_details(test_name)
        expected, actual = self._infer_expected_actual(details.message)
        reproduction_hints = [
            f"Run the failed test directly using Robot Framework: robot --test \"{details.test_name}\" {self._source_path}",
        ]

        if details.source:
            reproduction_hints.append(f"Source file: {details.source}")

        if details.keyword_trace:
            reproduction_hints.append(
                "Test steps include: " + ", ".join(entry.keyword_name for entry in details.keyword_trace[:4])
            )

        return BugReportData(
            title=f"Robot Framework failure: {details.suite_path} / {details.test_name}",
            failing_test=f"{details.suite_path} / {details.test_name}",
            failure_message=details.message,
            reproduction_hints=reproduction_hints,
            expected=expected,
            actual=actual,
            artifacts=[self._source_path] + (artifacts or []),
        )

    def _ensure_loaded(self) -> None:
        if self._result is None:
            raise ValueError("No Robot Framework result file has been loaded.")

    def _iter_test_cases(self, suite: Any) -> Iterable[Any]:
        for test in getattr(suite, "tests", []):
            yield test

        for subsuite in getattr(suite, "suites", []):
            yield from self._iter_test_cases(subsuite)

    def _find_test_case(self, test_name: str) -> Any:
        candidates = [
            test
            for test in self._iter_test_cases(self._result.suite)
            if test.name == test_name or getattr(test, "longname", None) == test_name
        ]

        if len(candidates) == 1:
            return candidates[0]

        partial_matches = [
            test
            for test in self._iter_test_cases(self._result.suite)
            if test_name in getattr(test, "longname", "")
        ]
        if len(partial_matches) == 1:
            return partial_matches[0]

        if not candidates and not partial_matches:
            raise ValueError(f"Test case not found: {test_name}")

        raise ValueError(
            f"Ambiguous test name: {test_name}. Provide a full or unique test name."
        )

    def _build_suite_path(self, suite: Any) -> str:
        if suite is None:
            return ""
        segments = []
        current = suite
        while current is not None and getattr(current, "name", None):
            segments.insert(0, current.name)
            current = getattr(current, "parent", None)
        return " > ".join(segments)

    def _build_test_summary(self, test: Any) -> FailedTestSummary:
        return FailedTestSummary(
            suite_name=self._build_suite_path(test.parent),
            full_name=getattr(test, "longname", f"{test.name}"),
            test_name=test.name,
            status=test.status,
            message=self._extract_message(test.message),
            tags=list(getattr(test, "tags", []) or []),
            elapsed_time_seconds=self._elapsed_seconds(test),
            source=self._find_source_for_case(test),
        )

    def _find_source_for_case(self, case: Any) -> Optional[str]:
        return getattr(case, "source", None) or getattr(getattr(case, "parent", None), "source", None)

    def _build_keyword_trace(self, case: Any) -> List[KeywordTraceEntry]:
        trace: List[KeywordTraceEntry] = []
        body = getattr(case, "body", None) or getattr(case, "keywords", None) or []

        for keyword in body:
            trace.extend(self._walk_keyword(keyword, depth=0))

        return trace

    def _walk_keyword(self, keyword: Any, depth: int = 0) -> List[KeywordTraceEntry]:
        entries: List[KeywordTraceEntry] = []
        kw_type = getattr(keyword, "type", None)
        if kw_type not in ("kw", "KEYWORD"):
            return entries

        entries.append(
            KeywordTraceEntry(
                keyword_name=keyword.name,
                status=getattr(keyword, "status", "UNKNOWN"),
                elapsed_time_seconds=self._elapsed_seconds(keyword),
                message=self._extract_message(getattr(keyword, "message", None)),
                source=getattr(keyword, "source", None),
                depth=depth,
            )
        )

        for child in getattr(keyword, "keywords", []) or []:
            entries.extend(self._walk_keyword(child, depth=depth + 1))

        return entries

    def _build_failure_group_key(self, summary: FailedTestSummary) -> str:
        keyword = self._extract_keyword_name(summary.message) or "unknown"
        snippet = self._short_message_snippet(summary.message) or ""
        return f"{keyword}|{snippet}"

    def _common_failed_keyword(self, tests: List[FailedTestSummary]) -> Optional[str]:
        names = [self._extract_keyword_name(test.message) or "Unknown" for test in tests if test.message]
        unique = sorted(set(names))
        return unique[0] if len(unique) == 1 else None

    def _common_tags(self, tests: List[FailedTestSummary]) -> List[str]:
        tag_sets = [set(test.tags) for test in tests if test.tags]
        if not tag_sets:
            return []
        common = set.intersection(*tag_sets)
        return sorted(common)

    def _short_message_snippet(self, message: str) -> Optional[str]:
        if not message:
            return None
        snippet = message.strip().splitlines()[0]
        return snippet[:120]

    def _extract_keyword_name(self, message: str) -> Optional[str]:
        if not message:
            return None
        match = re.search(r"Keyword\s+['\"]?([A-Za-z0-9_ ]+)['\"]?", message)
        return match.group(1).strip() if match else None

    def _extract_message(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return " ".join(str(item).strip() for item in value if item)
        return str(value).strip()

    def _parse_time(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        for format_string in ("%Y%m%d %H:%M:%S.%f", "%Y%m%d %H:%M:%S"):
            try:
                return datetime.strptime(value, format_string)
            except (TypeError, ValueError):
                continue
        return None

    def _elapsed_seconds(self, item: Any) -> float:
        elapsed = getattr(item, "elapsedtime", None)
        if elapsed is not None:
            try:
                return float(elapsed) / 1000.0
            except (TypeError, ValueError):
                pass

        start = self._parse_time(getattr(item, "starttime", None))
        end = self._parse_time(getattr(item, "endtime", None))
        if start and end:
            return max(0.0, (end - start).total_seconds())

        return 0.0

    def _infer_expected_actual(self, message: str) -> tuple[Optional[str], Optional[str]]:
        if not message:
            return None, None

        expected_match = re.search(r"[Ee]xpected\s+(.+?)\s+(?:but|but was|but got|but found)", message)
        actual_match = re.search(r"(?:but|but was|but got|but found)\s+(.+)", message)

        expected = expected_match.group(1).strip() if expected_match else None
        actual = actual_match.group(1).strip() if actual_match else None
        return expected, actual
