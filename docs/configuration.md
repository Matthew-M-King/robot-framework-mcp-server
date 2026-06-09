# Configuration

## Results directory layout

The server expects results organised as:

```
results_dir/
  Area_One/
    robot/
      output.xml
  Area_Two/
    robot/
      output.xml
```

Each immediate child folder is treated as one area. The area label is derived by stripping `Product_` and replacing underscores with spaces (e.g. `Product_User_Profile` → `User Profile`).

## Database initialisation

Before using `get_triage_queue`, `generate_failure_matrix`, or `execute_query`, ingest the results once:

```
ingest_results(results_dir="/path/to/results")
```

This parses all `robot/output.xml` files found in child folders, scores every failing test, and writes everything to `failure_analysis.db` inside `results_dir`.

The ingest is **idempotent** — if nothing has changed (SHA-1 hash of all xml mtimes matches) it returns immediately. On a fresh run expect ~3 minutes for a large suite; subsequent calls complete in under 1 second.

You only need to re-run ingest after a new test run produces new `output.xml` files.

## Area category configuration (optional)

`prepare_debug_context` can route each failure to a named debug category and supply product-file hints for an external Claude skill. This mapping is **entirely optional** — the server works without it and all tests default to the `GENERIC` category.

To add your own mappings, create `area_categories.json` in the project root (or set `RF_AREA_CATEGORIES` to an absolute path):

```json
[
  {
    "folder_fragment": "Checkout",
    "category": "CHECKOUT",
    "hints": ["checkout/checkout.md"]
  },
  {
    "folder_fragment": "Auth",
    "category": "AUTH",
    "hints": ["auth/auth.md"]
  }
]
```

Each `folder_fragment` is matched case-insensitively against the parent folder of each `output.xml`. An example with sample entries ships as `area_categories.json`.

## API failure pattern (optional)

By default the server escalates failures whose message contains `Wrong response code received`. To match your own HTTP keyword library's error format, set:

```bash
export RF_API_FAILURE_PATTERN="your pattern here"
```

Set it to an empty string to disable API escalation entirely.
