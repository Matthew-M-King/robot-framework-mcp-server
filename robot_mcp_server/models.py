from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class RobotRunSummary:
    total: int
    passed: int
    failed: int
    skipped: int
    elapsed_time_seconds: float
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    source_path: str


@dataclass
class FailedTestSummary:
    suite_name: str
    test_name: str
    full_name: str
    status: str
    message: str
    tags: List[str]
    elapsed_time_seconds: float
    source: Optional[str]


@dataclass
class KeywordTraceEntry:
    keyword_name: str
    status: str
    elapsed_time_seconds: float
    message: str
    source: Optional[str]
    depth: int = 0


@dataclass
class TestDetails:
    suite_path: str
    test_name: str
    status: str
    message: str
    tags: List[str]
    setup_status: Optional[str]
    teardown_status: Optional[str]
    keyword_trace: List[KeywordTraceEntry]
    failed_keyword: Optional[str]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    source: Optional[str]


@dataclass
class FailureGroup:
    group_id: str
    test_names: List[str]
    common_keyword: Optional[str]
    message_snippet: Optional[str]
    failed_keywords: List[str]
    shared_tags: List[str]


@dataclass
class RunComparisonResult:
    new_failures: List[str]
    repeated_failures: List[str]
    fixed_tests: List[str]
    consistent_failures: List[str]


@dataclass
class BugReportData:
    title: str
    failing_test: str
    failure_message: str
    reproduction_hints: List[str]
    expected: Optional[str]
    actual: Optional[str]
    artifacts: List[str]
