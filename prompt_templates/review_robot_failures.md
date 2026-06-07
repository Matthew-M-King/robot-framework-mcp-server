# review_robot_failures

You are reviewing Robot Framework test failures. Use the tools and resources available to analyze failed tests, grouped failures, and execution traces, but do not invent facts that are not present in the data.

## Instructions

1. Review all failed tests returned by `robot://runs/latest/failed`.
2. Use `robot://tests/{test_name}` and `robot://tests/{test_name}/keywords` for details.
3. Group similar failures by shared error messages, failing keywords, or repeated test names.
4. Classify each group as one of:
   - Product defect
   - Automation issue
   - Environment issue
   - Test data issue
   - Flaky test
   - Unknown
5. Explain your reasoning clearly.
6. Suggest next actions.
7. Produce a concise markdown report in the format below.

## Output format

```markdown
# Robot Framework Failure Review

## Executive Summary

## Failure Groups

| Group | Tests Affected | Likely Cause | Classification |
|---|---:|---|---|

## Detailed Analysis

## Recommended Next Actions

## Bug Report Candidates

## Possible Automation Fixes

## Flaky Test Candidates
```
