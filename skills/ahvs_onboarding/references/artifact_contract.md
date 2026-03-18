# Artifact Contract

`ahvs_onboarding` should treat `.ahvs/baseline_metric.json` as the required machine-readable onboarding artifact for AHVS.

## Required File

Path:

- `<target>/.ahvs/baseline_metric.json`

## Required Fields

The file must contain:

- `primary_metric`
- a numeric field whose key matches `primary_metric`
- `recorded_at`
- `eval_command`

Recommended:

- `commit`

## Example

```json
{
  "primary_metric": "answer_relevance",
  "answer_relevance": 0.74,
  "recorded_at": "2026-03-18T10:00:00Z",
  "commit": "abc1234",
  "eval_command": "promptfoo eval --config .ahvs/eval/baseline.yaml"
}
```

## Rules

1. The metric value must be numeric.
2. `recorded_at` should be ISO-8601.
3. `eval_command` should be reproducible enough to rerun.
4. `commit` should be included when the target is a git repo.
5. Do not write placeholder values such as `0`, `TODO`, or `fill me in later` unless the user explicitly asks for a draft-only artifact and understands it is not AHVS-ready.

## Optional Related Artifacts

The skill may also prepare:

- `.ahvs/regression_guard.sh`
- `.ahvs/eval/*`

These are helpful but not required for a minimal AHVS-ready state.
