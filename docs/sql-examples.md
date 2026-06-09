# SQL Query Examples

The `execute_query` tool runs a read-only SELECT against the `scored_tests` table. Results are capped at 200 rows.

Ask Claude a plain-English question and it will write the SQL — or write your own.

## Schema

```sql
CREATE TABLE scored_tests (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER,
    area            TEXT,      -- derived from folder name
    suite           TEXT,      -- RF suite name
    name            TEXT,      -- test case name
    tags            TEXT,      -- JSON array of tag strings
    message         TEXT,      -- failure message
    failure_type    TEXT,      -- functional | infra-keyword | infra-setup | setup-other
    priority        TEXT,      -- critical | high | medium | low
    severity        TEXT,      -- critical | high | medium | low
    defect_ids      TEXT,      -- JSON array of defectid= values
    is_quarantined  INTEGER,   -- 1 if any quarantine-* tag present
    fp              TEXT,      -- normalised fingerprint for grouping
    base_score      INTEGER,   -- score before group bonus
    xml_path        TEXT,
    api_endpoint    TEXT,      -- set for API response failures
    escalated       INTEGER,   -- 1 if score was forced by API escalation
    received_code   INTEGER,   -- HTTP status code actually received
    response_error  TEXT       -- extracted error from response body
);
```

## Example queries

```sql
-- How many failures per area?
SELECT area, COUNT(*) AS failures
FROM scored_tests
GROUP BY area
ORDER BY failures DESC

-- Which quarantined tests have the highest score?
SELECT name, area, base_score
FROM scored_tests
WHERE is_quarantined = 1
ORDER BY base_score DESC

-- All API-escalated failures grouped by endpoint
SELECT api_endpoint, COUNT(*) AS n, received_code
FROM scored_tests
WHERE escalated = 1
GROUP BY api_endpoint
ORDER BY n DESC

-- Critical failures with no tracked defect
SELECT name, area, base_score
FROM scored_tests
WHERE priority = 'critical'
  AND defect_ids = '[]'
  AND is_quarantined = 0
ORDER BY base_score DESC

-- Infra failures by area (to spot environment problems)
SELECT area, COUNT(*) AS infra_failures
FROM scored_tests
WHERE failure_type IN ('infra-keyword', 'infra-setup')
GROUP BY area
ORDER BY infra_failures DESC

-- Failures introduced since yesterday (by xml mtime proxy)
SELECT name, area, base_score, message
FROM scored_tests
ORDER BY base_score DESC
LIMIT 20
```
