"""Generate an HTML failure matrix from the bundled sample_results directory.

Run from the repo root:
    python examples/generate_sample_report.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robot_mcp_server.failure_matrix import analyse

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "sample_results")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "sample_failure_report.html")

result = analyse(RESULTS_DIR, output_path=OUTPUT_PATH)

print(f"Failures : {result.total_failures}")
print(f"Groups   : {result.total_groups}")
print(f"Report   : {result.output_path}")
