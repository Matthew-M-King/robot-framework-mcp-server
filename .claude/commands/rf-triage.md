# Robot Framework Failure Triage

Analyse Robot Framework test results using the rf-test-analysis-mcp server and produce a prioritised investigation plan. Works with any Robot Framework test suite — no product-specific knowledge required.

## Prerequisites

The FastAPI HTTP server must be running:
```
python -m uvicorn robot_mcp_server.http_server:app --host 127.0.0.1 --port 8000
```

## Usage

```
/rf-triage <results_dir> [area_filter]
```

- `results_dir` — path to the directory that contains your Robot Framework result folders (each folder should have a `robot/output.xml` inside)
- `area_filter` — optional substring to restrict analysis to one area (e.g. `Checkout`)

## Workflow

Follow these steps in order. Use the MCP tools exposed by the running server.

### Step 1 — Ingest

Call `ingest_results(results_dir=<results_dir>)`.

- If `already_current: true` is returned, the data is already up to date — skip to Step 3.
- On a fresh run this may take a few minutes; wait for the response before continuing.

### Step 2 — Generate failure matrix

Call `generate_failure_matrix(results_dir=<results_dir>, output_format="html")`.

Report the path of the generated HTML file to the user so they can open it in a browser.

### Step 3 — Get triage queue

Call `get_triage_queue(results_dir=<results_dir>, area_filter=<area_filter>, top_n=20)`.

For each item in the queue, note:
- `rank`, `score`, `priority_label` (P1–P4)
- `failure_count` and `areas_affected`
- `failure_type` (`functional` / `infra-keyword` / `infra-setup` / `setup-other`)
- `failure_pattern` (normalised root-cause fingerprint)
- `representative_test` and `xml_path`
- `investigation_hints`
- `escalated` (true = API response-code failure, treat as P1 regardless of label)

### Step 4 — Expand high-priority groups

For each group with `score >= 55` (P1 or P2):

Call `get_group_tests(results_dir=<results_dir>, failure_pattern=<failure_pattern>)`.

List all affected test names and areas so the user sees the full blast radius.

### Step 5 — Deep-dive on top failures

For each of the top 5 items (or all P1s):

Call `prepare_debug_context(xml_path=<xml_path>, test_name=<representative_test>)`.

Use the returned data to explain:
1. **Root cause** — what the innermost failure message says
2. **Keyword trace** — which keyword in the chain failed and at what depth
3. **Classification** — `failure_type` and `debug_category`
4. **Tags context** — priority, severity, any defect IDs or quarantine flags

### Step 6 — Produce the investigation plan

Write a structured report:

```
## Executive Summary
<total failures, unique groups, count per priority band>

## API Escalations  (if any escalated=true items exist)
<table: endpoint | count | HTTP code | representative test>

## P1 Failures  (score >= 70)
For each group:
  - **Pattern**: <failure_pattern>
  - **Tests affected**: <count> across <areas>
  - **Root cause**: <innermost failure message>
  - **Hint**: <investigation_hints>

## P2 Failures  (score 55–69)
<same structure, more concise>

## Infrastructure Issues  (failure_type = infra-*)
<list: test name | failure_type | message snippet>

## Known Defects  (tests with defectid= tags)
<list if any appeared in queue>

## Recommended Next Actions
1. <highest-impact action>
2. ...
```

### Step 7 — Ad-hoc queries (optional)

If the user asks follow-up questions ("how many failures in area X?", "which tests are quarantined?"), use `execute_query` with a read-only SELECT against the `scored_tests` table.

Schema reference (available columns):
```
run_id, area, suite, name, tags, message, failure_type,
priority, severity, defect_ids, is_quarantined, fp,
base_score, xml_path, api_endpoint, escalated,
received_code, response_error
```

## Scoring reference

| Score | Priority | Meaning |
|-------|----------|---------|
| 70–100 | P1 | Critical — investigate immediately |
| 55–69  | P2 | High — investigate this sprint |
| 40–54  | P3 | Medium — schedule for next sprint |
| 0–39   | P4 | Low — monitor or defer |

API escalation overrides: 5xx → 92, 4xx → 87, 403 → 80 regardless of tags.

## Notes

- Re-run `ingest_results` after each new Robot Framework test run.
- The `failure_analysis.db` SQLite database lives inside `results_dir` and is safe to delete to force a full re-parse.
- `area_categories.json` in the project root lets you map folder names to custom debug categories — see README for format. Without it, all areas default to GENERIC.
