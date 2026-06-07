from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import quote, unquote

from .models import (
    BugReportData,
    FailureGroup,
    FailedTestSummary,
    RobotRunSummary,
    RunComparisonResult,
    TestDetails,
)
from .parser import RobotResultParser


class RobotResultAnalyzerServer:
    """Server-side analyzer that exposes Robot Framework result analysis tools."""

    def __init__(self) -> None:
        self._parser = RobotResultParser()
        self._artifact_paths: List[str] = []
        self._latest_summary: Optional[RobotRunSummary] = None

    def load_result_file(self, path: str) -> RobotRunSummary:
        """Load a Robot Framework output.xml file and return a run summary."""
        summary = self._parser.parse_run(path)
        self._latest_summary = summary
        return summary

    def get_failed_tests(self) -> List[FailedTestSummary]:
        """Return all failed tests from the latest loaded run."""
        return self._parser.get_failed_tests()

    def get_test_details(self, test_name: str) -> TestDetails:
        """Return detailed information for a specific failed test."""
        return self._parser.get_test_details(test_name)

    def get_keyword_trace(self, test_name: str) -> List[Any]:
        """Return the keyword execution trace for a specific failed test."""
        return self._parser.get_keyword_trace(test_name)

    def summarize_failures(self) -> List[FailureGroup]:
        """Return structured failure groups for the latest loaded run."""
        return self._parser.summarize_failures()

    def compare_with_previous_run(self, current_path: str, previous_path: str) -> RunComparisonResult:
        """Compare two Robot Framework run files and identify changes in failures."""
        return self._parser.compare_with_previous_run(current_path, previous_path)

    def generate_bug_report_data(self, test_name: str) -> BugReportData:
        """Generate structured data for writing a bug report for a failed test."""
        return self._parser.generate_bug_report_data(test_name, artifacts=self._artifact_paths)

    def register_artifacts(self, artifact_paths: List[str]) -> None:
        """Register optional artifact paths to include in bug report output."""
        self._artifact_paths = list(artifact_paths)

    def get_resource(self, uri: str) -> Any:
        """Resolve a robot:// resource URI to structured data."""
        if uri == "robot://runs/latest":
            if self._latest_summary is None:
                raise ValueError("No run has been loaded yet.")
            return self._latest_summary

        if uri == "robot://runs/latest/failed":
            return self.get_failed_tests()

        if uri.startswith("robot://tests/"):
            suffix = uri.removeprefix("robot://tests/")
            if suffix.endswith("/keywords"):
                test_name = unquote(suffix[: -len("/keywords")])
                return self.get_keyword_trace(test_name)
            test_name = unquote(suffix)
            return self.get_test_details(test_name)

        raise ValueError(f"Unsupported resource URI: {uri}")

    def list_resource_uris(self) -> List[str]:
        """Return the standard resource URIs supported by the server."""
        return [
            "robot://runs/latest",
            "robot://runs/latest/failed",
            "robot://tests/{test_name}",
            "robot://tests/{test_name}/keywords",
        ]

    def format_test_uri(self, test_name: str) -> str:
        """Return a normalized robot:// URI for a test name."""
        return f"robot://tests/{quote(test_name)}"

    def format_test_keyword_uri(self, test_name: str) -> str:
        """Return a normalized robot:// keyword trace URI for a test name."""
        return f"robot://tests/{quote(test_name)}/keywords"
