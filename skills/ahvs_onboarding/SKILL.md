---
name: ahvs_onboarding
description: >-
  Conversational onboarding wizard for AHVS (Automated Hypothesis Validation System).
  Inspects a target repo or directory, identifies evaluation paths and metrics,
  gathers missing details through short follow-up questions, writes
  .ahvs/baseline_metric.json, and refuses to advance when onboarding is unsafe.
  Use this skill whenever the user says "onboard for AHVS", "prepare for AHVS",
  "set up AHVS", "ahvs onboard", "get this repo ready for AHVS", or mentions
  wanting to run AHVS on a project that doesn't have .ahvs/ yet. Also trigger
  when the user asks to "improve a metric" or "optimize evaluation" and AHVS
  setup is missing. If you see a repo without .ahvs/baseline_metric.json and
  the user wants to run researchclaw ahvs, this skill should fire first.
---

# AHVS Onboarding

This skill is a hard readiness gate. It turns natural-language intent into the strict `.ahvs/baseline_metric.json` contract that AHVS needs before a cycle can start.

The user should never need to manually author JSON. Instead, this skill inspects the repo, infers what it can, asks only the smallest necessary follow-up questions, and writes the artifacts when everything checks out.

## What This Skill Does and Does Not Do

**Does:**
1. Inspect the target repo/directory for evaluation artifacts
2. Infer candidate metrics, eval commands, and project type
3. Ask short, targeted follow-up questions
4. Validate that a reproducible evaluation path exists
5. Write `.ahvs/baseline_metric.json` (and optional helpers) when coherent
6. Refuse to advance when onboarding is incomplete or unsafe

**Does not:**
1. Invent baseline values or guess fake eval commands
2. Hide reduced-trust mode when the target is not in git
3. Start an AHVS cycle — that's a separate step after onboarding

## Return Contract

Every onboarding pass ends with one of three statuses:

| Status | Meaning | What happens next |
|--------|---------|-------------------|
| `ready` | All gates passed, artifacts written | User can run `researchclaw ahvs` |
| `needs_user_input` | Promising but missing info | Ask the follow-up, then re-evaluate |
| `blocked` | Cannot proceed safely | Explain the blocker and what must change |

Return `ready` **only** when ALL of these are true:
1. Target path exists
2. Optimization metric is clearly identified
3. A reproducible evaluation path exists
4. Baseline value is known or just measured
5. `.ahvs/baseline_metric.json` is internally consistent

## Workflow

### Phase 1: Discover — Inspect Before Asking

Use Glob and Read to scan the target for existing structure. Check these paths first:

```
README*, pyproject.toml, requirements.txt, package.json, Makefile,
.github/workflows/*, .ahvs/*, promptfoo*, eval.py, scripts/eval*,
tests/, benchmarks/, *.yaml configs with "eval" in the name
```

From this inspection, infer:
- **Project type** (Python package, Node app, RAG pipeline, ML model, etc.)
- **Candidate metric names** (from eval configs, test output, CI logs)
- **Likely eval commands** (from Makefile targets, CI steps, scripts)
- **Whether `.ahvs/` already exists** (if so, validate rather than create)

Use Grep to search for metric-like patterns:
```
accuracy, relevance, f1, precision, recall, score, bleu, rouge, loss
```

### Phase 2: Infer — Build a Candidate Setup

From the inspection, draft a candidate:
- `primary_metric`: the metric name to optimize
- `eval_command`: the command that measures it
- `baseline_value`: from an existing run, artifact, or "unknown"
- `repo_mode`: git (worktree) or non-git (sandbox-only)

### Phase 3: Clarify — Ask Only What's Missing

Good questions:
- "What metric should AHVS optimize?"
- "I found `make eval` — is that the right command to measure [metric]?"
- "Should AHVS block changes that regress a secondary check?"

Bad questions:
- "Please write a JSON file"
- "Explain your architecture"
- "Provide every field AHVS needs"

If the repo inspection already answered a question, don't ask it again.

### Phase 4: Validate — Check Everything

Before writing any files:

1. **Target exists** — verify the path with `ls`
2. **Metric is unambiguous** — a clear name, not "quality" or "goodness"
3. **Eval command is credible** — not a placeholder. Read `references/eval_command_policy.md` for acceptance rules
4. **Baseline value is real** — from the user, an existing artifact, or a verified run. Never invented.
5. **Git status** — run `git rev-parse HEAD` to check. Read `references/git_mode_policy.md`

### Phase 5: Materialize — Write Artifacts

Create `.ahvs/` if needed, then write:

**Required: `.ahvs/baseline_metric.json`**
```json
{
  "primary_metric": "<metric_name>",
  "<metric_name>": <numeric_value>,
  "recorded_at": "<ISO-8601 timestamp>",
  "eval_command": "<reproducible command>",
  "commit": "<git SHA or omit if non-git>"
}
```

See `references/artifact_contract.md` for the full schema and rules.

**Optional:**
- `.ahvs/regression_guard.sh` — if the user wants regression protection
- `.ahvs/eval/*` — if a new eval config was created

After writing, summarize what was **inferred** vs what was **explicitly confirmed** by the user.

### Phase 6: Gate — Return Status

Present a clear status block:

```
## AHVS Onboarding: [STATUS]

**Target:** /path/to/repo (git / non-git)
**Metric:** answer_relevance = 0.74
**Eval command:** promptfoo eval --config .ahvs/eval/baseline.yaml
**Files written:** .ahvs/baseline_metric.json

**Warnings:**
- (any caveats, e.g. "no regression guard configured")

**Next step:** Run `researchclaw ahvs --repo /path/to/repo --question "..."`
```

## Git Mode Policy

Always check `git rev-parse --is-inside-work-tree` on the target.

**Git repo:**
- Record current commit SHA in baseline
- Explain: AHVS uses detached worktrees for per-hypothesis execution — higher trust
- This is the recommended mode

**Not a git repo:**
- Do NOT block by default
- Warn clearly: AHVS falls back to sandbox-only mode with weaker reproducibility
- No patch tracking, no commit anchoring
- Still works for single files and loose directories

## Failure Modes

**Return `blocked` when:**
- Target path does not exist
- Metric is too vague to measure (e.g. "make it better")
- No reproducible eval path can be established
- Candidate eval fails and no credible fallback exists

**Return `needs_user_input` when:**
- Repo looks promising but metric needs confirmation
- Found a likely eval command but it needs approval
- Baseline value is missing but can likely be measured

## Reference Files

Read these as needed — they contain the detailed policies:

- `references/artifact_contract.md` — baseline JSON schema, required vs optional fields
- `references/eval_command_policy.md` — how to accept or reject candidate eval commands
- `references/git_mode_policy.md` — git vs non-git execution trust model
