# `ahvs_onboarding` Skill Spec

## Purpose

`ahvs_onboarding` is a conversational pre-flight skill for AHVS. Its job is to translate user intent and repository context into the exact onboarding artifacts AHVS needs, without making the user manually author `.ahvs/baseline_metric.json`.

It should act as a hard readiness gate:

- if onboarding is complete and validated, it writes the required artifacts and returns `ready`
- if onboarding is incomplete or ambiguous, it returns `needs_user_input`
- if onboarding cannot be completed safely, it returns `blocked`

It must not allow AHVS to proceed on a weak or guessed setup.

## Why This Skill Exists

Today AHVS expects users to know internal implementation details:

- where `.ahvs/` belongs
- what `baseline_metric.json` must contain
- how to supply a valid `eval_command`
- when git/non-git mode changes reliability

That is too technical for the first-run experience.

This skill should become the user-facing onboarding layer while keeping:

- `.ahvs/baseline_metric.json`
- optional `.ahvs/regression_guard.sh`
- optional `.ahvs/eval/*`

as internal machine-readable artifacts.

## Product Positioning

Think of `ahvs_onboarding` as:

- a conversational wizard
- a repo-aware validator
- an artifact generator
- a gatekeeper before `researchclaw ahvs`

Not as:

- a hypothesis generator
- an experiment runner
- a silent config guesser

## Core Principle

Natural language in, strict contract out.

The user should be able to say something like:

> Improve answer relevance in this RAG repo. We currently evaluate with Promptfoo.

and the skill should guide the repo into a valid AHVS-ready state.

## Inputs

The skill should accept a mix of:

- user natural-language goals
- explicit repo path
- optional existing eval setup
- optional known baseline value
- optional regression policy

Expected user-provided information, whether directly or through follow-up:

- target repo or target file/directory path
- optimization objective
- metric name
- current baseline value, if already known
- how that metric is measured
- whether regressions should be blocked

## Outputs

The skill should produce one of three statuses.

### 1. `ready`

Meaning:

- AHVS can safely start

Required side effects:

- write `.ahvs/baseline_metric.json`
- optionally create supporting files such as `.ahvs/regression_guard.sh`
- summarize what was inferred vs explicitly confirmed

### 2. `needs_user_input`

Meaning:

- onboarding is plausible, but not yet safe to finalize

Required behavior:

- ask targeted follow-up question(s)
- do not write a misleading or incomplete baseline file
- preserve gathered context for the next turn/session if your framework supports it

### 3. `blocked`

Meaning:

- AHVS should not proceed

Examples:

- repo path does not exist
- no reproducible evaluation path can be established
- metric semantics are too vague
- candidate eval command fails and no alternative is available

Required behavior:

- explain the blocker concretely
- state what must be fixed before retry

## Required Artifact Contract

The skill owns preparation of:

- `<repo>/.ahvs/baseline_metric.json`

Minimum required fields:

- `primary_metric`
- `<primary_metric>` numeric value
- `recorded_at`
- `eval_command`

Recommended field:

- `commit`

Optional related artifacts:

- `<repo>/.ahvs/regression_guard.sh`
- `<repo>/.ahvs/eval/*`

## Hard Gating Rules

The skill must not return `ready` unless all of the following are true.

1. Target path is known and exists.
2. The optimization metric is clearly identified.
3. A reproducible evaluation path exists.
4. The baseline value is known or has just been measured.
5. The resulting baseline artifact is internally consistent.

If any of these are not satisfied, return `needs_user_input` or `blocked`.

## Strong Recommendation Rules

These should not block onboarding by default, but they must be surfaced clearly.

1. Target is not a git repo.
2. No `commit` can be recorded.
3. Regression guard is missing.
4. Evaluation command exists but is slow, flaky, or network-dependent.

For non-git targets, the skill should say clearly that AHVS can still run in a weaker sandbox-only mode, but reproducibility and patch tracking are reduced.

## Conversation Design

The skill should prefer a short QA flow, not a long form.

Ideal interaction style:

1. inspect repo
2. infer what can be inferred
3. ask only the smallest high-value follow-up questions
4. confirm risky assumptions
5. write artifacts

Good questions:

- "What metric do you want AHVS to optimize?"
- "Do you already have a command that measures that metric?"
- "Should AHVS block changes that regress a secondary quality check?"

Bad questions:

- "Please manually write a JSON file"
- "Please explain your entire architecture"
- "Please provide every field required by AHVS"

## Repo Inspection Responsibilities

The skill should inspect the repo before asking unnecessary questions.

Suggested inspection targets:

- `README*`
- `pyproject.toml`
- `requirements.txt`
- `package.json`
- `Makefile`
- `.github/workflows/*`
- `promptfoo` config files
- evaluation scripts such as `eval.py`, `scripts/eval.py`, `tests/`, `benchmarks/`
- existing `.ahvs/` contents

The purpose of inspection is to infer:

- probable project type
- likely evaluation framework
- candidate metric names
- candidate evaluation command

## Eval Command Policy

This is the most important part of onboarding.

The skill should try to identify or synthesize a reproducible `eval_command`.

Acceptable sources:

- existing repo eval script
- existing CI/test command that emits the target metric
- existing Promptfoo or benchmark config
- a newly created helper script, if necessary and explicitly explained

The skill should not mark onboarding `ready` if `eval_command` is just a vague placeholder.

Preferred behavior:

1. propose a candidate command
2. optionally dry-run or sanity-check it
3. confirm it with the user if the command is risky, expensive, or ambiguous
4. store it in the baseline file

## Baseline Value Policy

Baseline value should come from one of:

1. user-provided known value
2. parsed result from a verified eval command
3. existing repo artifact that clearly records the metric

The skill must not invent a baseline value.

If the metric name is known but the value is unknown, it should prefer:

- running the evaluation
- or asking the user for the current known baseline

If neither is possible, onboarding is not `ready`.

## Git Awareness

The skill should explicitly check whether the target path is a git repo.

### If the target is a git repo

Record:

- current commit SHA in `baseline_metric.json`

Tell the user:

- AHVS can use detached worktrees
- this is the higher-trust path

### If the target is not a git repo

Do not block by default, but warn clearly:

- AHVS will fall back to sandbox-only execution
- patch tracking and reproducibility are weaker

If the target is a single file or loose directory, the skill should still be able to onboard it, but should state the trust tradeoff plainly.

## Regression Guard Policy

Regression guard is optional but recommended.

The skill should:

- detect if a suitable existing command/script already exists
- offer to create a simple guard wrapper if appropriate
- explain what the guard protects against

The absence of a regression guard should usually be a warning, not a blocker.

## Proposed Skill Interface

Recommended logical inputs:

- `target_path`
- `goal`
- `metric_name`
- `baseline_value`
- `eval_command`
- `regression_policy`
- `auto_inspect_repo`

Recommended logical outputs:

- `status`
- `summary`
- `repo_mode`
- `baseline_file_path`
- `artifacts_written`
- `warnings`
- `open_questions`

## Suggested State Machine

### State 1. Discover

Collect:

- target path
- repo shape
- likely eval artifacts
- whether `.ahvs/` already exists

### State 2. Infer

Infer candidate:

- metric
- baseline source
- eval command
- git mode

### State 3. Clarify

Ask the smallest necessary follow-up question set.

### State 4. Validate

Check:

- target exists
- metric is unambiguous
- baseline value is present
- eval command is reproducible enough
- generated artifact is coherent

### State 5. Materialize

Write:

- `.ahvs/baseline_metric.json`
- optional helper artifacts

### State 6. Gate

Return:

- `ready`
- `needs_user_input`
- `blocked`

## Integration Recommendation

There are two reasonable integration paths.

### Option A. Explicit onboarding command

Example:

```bash
researchclaw ahvs-onboard --repo /path/to/repo
```

This is the cleanest UX.

### Option B. Auto-gate inside `researchclaw ahvs`

Behavior:

- before Stage 1, detect whether onboarding is complete
- if not complete, invoke `ahvs_onboarding`
- only continue if the skill returns `ready`

My recommendation:

- implement both eventually
- start with an explicit onboarding entrypoint for clarity and easier debugging

## Draft Acceptance Criteria

The skill is complete when it can:

1. onboard a git-backed repo with an existing eval command
2. onboard a non-git directory with a clearly explained reduced-trust mode
3. detect when no valid evaluation path exists and refuse to advance
4. create a valid `.ahvs/baseline_metric.json`
5. ask concise follow-up questions instead of requiring raw JSON editing

## Example Dialogues

### Example 1. Happy path with existing eval command

User:

> I want AHVS to improve answer relevance in this RAG repo.

Skill:

> I found a Promptfoo config under `.ahvs/eval/` and a likely evaluation command. I still need to confirm the target metric: should AHVS optimize `answer_relevance`?

User:

> Yes.

Skill:

> I ran the evaluation setup check, recorded the current baseline, and created `.ahvs/baseline_metric.json`. AHVS is ready.

Result:

- `status = ready`

### Example 2. Metric known, baseline unknown

User:

> Optimize factuality in this project.

Skill:

> I found an evaluation script, but I do not yet know the current factuality baseline. I can try to measure it using `python scripts/eval.py --suite factuality`. Should I use that as the baseline command?

User:

> Yes.

Skill:

> The command did not emit a parseable metric. Onboarding is blocked until we either fix the eval output or use a different measurement path.

Result:

- `status = blocked`

### Example 3. Single directory, not a git repo

User:

> My code is just in this folder, not git.

Skill:

> I can still onboard it, but AHVS will run in sandbox-only mode instead of detached worktrees. That reduces reproducibility and patch tracking. I found a valid eval script and can proceed if you want that lower-trust mode.

User:

> Proceed.

Skill:

> I created `.ahvs/baseline_metric.json` and marked the repo as non-git in the onboarding summary. AHVS is ready, with reduced-trust warnings.

Result:

- `status = ready`

## Suggested Skill Folder Shape

If your SWE implements this as a Codex skill, a good layout is:

```text
ahvs_onboarding/
├── SKILL.md
├── references/
│   ├── artifact_contract.md
│   ├── eval_command_policy.md
│   └── git_mode_policy.md
└── scripts/
    ├── inspect_repo.sh
    ├── detect_eval_candidates.py
    └── write_baseline.py
```

## Draft `SKILL.md`

The following is a good starting point for the skill body.

```md
---
name: ahvs_onboarding
description: Conversationally prepare a repository or directory for AHVS by inspecting the target, identifying or validating the evaluation path, gathering missing metric details, writing .ahvs/baseline_metric.json, and refusing to advance when onboarding is incomplete or unsafe.
---

# AHVS Onboarding

Use this skill when the user wants to prepare a repo, folder, or single-file project for AHVS, especially when they do not want to manually author `.ahvs/baseline_metric.json`.

## Workflow

1. Inspect the target path and existing eval-related files.
2. Infer the likely metric and evaluation path where possible.
3. Ask only the smallest necessary follow-up questions.
4. Do not guess baseline values.
5. Write `.ahvs/baseline_metric.json` only when the setup is coherent.
6. If the target is not a git repo, explain that AHVS will fall back to sandbox-only mode with weaker reproducibility.

## Return Contract

Return one of:

- `ready`
- `needs_user_input`
- `blocked`

Only return `ready` when:

- target exists
- metric is clear
- baseline value is known
- eval command is reproducible enough

## Read As Needed

- `references/artifact_contract.md` for the baseline file schema
- `references/eval_command_policy.md` for how to accept or reject candidate eval commands
- `references/git_mode_policy.md` for how to explain git vs non-git execution

## Scripts

- use `scripts/inspect_repo.sh` for fast repo discovery
- use `scripts/detect_eval_candidates.py` to identify likely eval commands
- use `scripts/write_baseline.py` to materialize `.ahvs/baseline_metric.json`
```

## Final Recommendation

This skill is worth building.

It solves the biggest AHVS adoption issue cleanly:

- users get a natural-language onboarding experience
- AHVS still receives a strict, validated machine contract
- unsafe or incomplete setups are blocked before cycle execution

If you want, I can take the next step and draft the actual `ahvs_onboarding/SKILL.md` plus the three reference files in a ready-to-commit layout. 
