# Failure Scoring

Scores run 0–100. **Higher = investigate first.**

## Scoring rubric

| Factor | Points |
|--------|--------|
| API escalation — 5xx server error | forced 92 |
| API escalation — 4xx client error (exc. 403) | forced 87 |
| API escalation — 403 Forbidden | forced 80 |
| Priority / Severity critical | +40 each |
| Priority / Severity high | +25 each |
| Priority / Severity medium (default for untagged) | 0 |
| Priority / Severity low | −20 each |
| `defectid=` tag (tracked defect) | −25 |
| `quarantine-*` tag (flagged risk) | **+10** — elevated, not suppressed |
| Infra failure: missing keyword / library | −30 |
| Infra failure: connection / deadlock in setup | −20 |
| Other setup failure | −10 |
| Shared fingerprint group bonus | +5 per extra test, up to +20 |

## Tags

Tests are scored based on tags in `output.xml`. Supported tag formats:

| Tag | Effect |
|-----|--------|
| `priority=critical` | +40 |
| `priority=high` | +25 |
| `priority=medium` | 0 (default) |
| `priority=low` | −20 |
| `severity=critical` | +40 |
| `severity=high` | +25 |
| `severity=medium` | 0 (default) |
| `severity=low` | −20 |
| `defectid=PROJ-123` | −25 (known issue) |
| `quarantine-<reason>` | +10 (flagged as unstable) |

## Priority bands

| Band | Score range | Label |
|------|-------------|-------|
| Critical | ≥ 75 | P1 |
| High | 55–74 | P2 |
| Medium | 35–54 | P3 |
| Low | < 35 | P4 |

## API escalation

When a test fails with `Wrong response code received`, the score is **forced** regardless of tags:

- 5xx server errors → 92
- 4xx client errors → 87
- 403 Forbidden → 80

This ensures a broken API endpoint always appears at the top of the triage queue. The actual error message is extracted from the response body JSON so you see the real server message, not just the HTTP status code.

## Fingerprint grouping

Tests sharing the same normalised failure message are grouped together and each receives a group bonus (up to +20). The fingerprint normalises variable values, numbers, and ticket references so that `'confirm-button' not found after 10s` and `'submit-button' not found after 30s` map to the same group.
