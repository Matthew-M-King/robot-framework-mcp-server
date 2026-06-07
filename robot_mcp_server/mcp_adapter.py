from __future__ import annotations

from typing import Any

from .server import RobotResultAnalyzerServer

try:
    import mcp
    MCP_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    mcp = None  # type: ignore[assignment]
    MCP_SDK_AVAILABLE = False


def create_mcp_server(analyzer: RobotResultAnalyzerServer) -> Any:
    """Create an MCP server using the official MCP SDK, if available."""
    if not MCP_SDK_AVAILABLE:
        raise ImportError(
            "Official MCP Python SDK is not installed. Install it with `pip install mcp` and retry."
        )

    if hasattr(mcp, "MCPServer"):
        server = mcp.MCPServer(
            name="robot-framework-result-review",
            description="Local MCP server for Robot Framework failure analysis.",
        )
        server.register_tool("load_result_file", analyzer.load_result_file)
        server.register_tool("get_failed_tests", analyzer.get_failed_tests)
        server.register_tool("get_test_details", analyzer.get_test_details)
        server.register_tool("get_keyword_trace", analyzer.get_keyword_trace)
        server.register_tool("summarize_failures", analyzer.summarize_failures)
        server.register_tool("compare_with_previous_run", analyzer.compare_with_previous_run)
        server.register_tool("generate_bug_report_data", analyzer.generate_bug_report_data)
        return server

    raise RuntimeError("Installed MCP package does not expose a supported MCPServer class.")
