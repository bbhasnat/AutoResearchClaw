# AHVS — Adaptive Hypothesis Validation System

AHVS is a cyclic hypothesis-validation pipeline built on top of ARC (AutoResearchClaw). It autonomously generates, selects, executes, and evaluates improvement hypotheses for any target LLM or RAG system — then archives what it learned for the next cycle.

---

## Table of Contents

1. [Overview](#1-overview)
2. [How AHVS Relates to ARC](#2-how-ahvs-relates-to-arc)
3. [The 8-Stage Cycle](#3-the-8-stage-cycle)
4. [Quick Start](#4-quick-start)
5. [Onboarding a Target Repository](#5-onboarding-a-target-repository)
6. [CLI Reference](#6-cli-reference)
7. [Hypothesis Types](#7-hypothesis-types)
8. [Skill Library](#8-skill-library)
9. [Cross-Cycle Memory](#9-cross-cycle-memory)
10. [Python API](#10-python-api)
11. [Configuration Reference](#11-configuration-reference)
12. [Directory Layout](#12-directory-layout)
13. [Advanced Usage](#13-advanced-usage)

---

## 1. Overview

Given a target repository and a single question — *"How can we improve answer\_relevance by 5%?"* — AHVS:

1. Reads the current baseline metric and all lessons from previous cycles
2. Asks an LLM to generate concrete, typed hypotheses
3. Pauses for a human (or runs non-interactively) to select which to test
4. Builds a detailed implementation + evaluation plan per hypothesis
5. Invokes **CodeAgent** to implement each hypothesis, applies the generated files to a **git worktree** of the target repo, and runs the `eval_command` against it
6. Writes a cycle report and archives every lesson into ARC's **EvolutionStore**
7. Produces a `cycle_summary.json` with a clear keep/revert recommendation and the path to the kept worktree/patch

Each cycle is self-contained and idempotent. The accumulated lessons steer future cycles away from dead ends and toward approaches that have worked before.

---

## 2. How AHVS Relates to ARC

AHVS and ARC are separate pipelines that **compose** — they share infrastructure but do not interfere with each other.

```
┌────────────────────────────────────────────────────────────────────┐
│  ARC  (23-stage research pipeline)                                  │
│  Stage enum, STAGE_SEQUENCE, PromptManager, StageContract, ...     │
│                                                                     │
│           ┌──────────────────────────────────────────────────┐     │
│           │  AHVS  (8-stage cyclic hypothesis loop)           │     │
│           │                                                   │     │
│           │  Uses from ARC:                                   │     │
│           │    • CodeAgent      — implement & execute hyps.  │     │
│           │    • EvolutionStore — cross-cycle memory          │     │
│           │    • LLMClient      — LLM calls                   │     │
│           │    • ExperimentSandbox — isolated execution       │     │
│           │    • StageStatus    — done / failed primitives    │     │
│           │                                                   │     │
│           │  Does NOT touch:                                  │     │
│           │    • Stage enum (separate AHVSStage IntEnum)      │     │
│           │    • ARC's 23-stage pipeline runner               │     │
│           │    • ARC's PromptManager (separate AHVSPromptMgr) │     │
│           │    • StageContract (separate AHVSStageContract)   │     │
│           └──────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────┘
```

### Why not extend ARC's Stage enum?

`Stage` is an `IntEnum` and `STAGE_SEQUENCE = tuple(Stage)` iterates every member. Adding AHVS stages to the same enum would inject them into ARC's 23-stage loop, breaking the research pipeline. AHVS uses its own `AHVSStage` enum in `researchclaw/ahvs/stages.py`.

### Why a separate PromptManager?

ARC's `PromptManager._load_overrides()` only updates stages already in `_DEFAULT_STAGES` — new stage names are silently skipped. `AHVSPromptManager` (in `researchclaw/ahvs/prompts.py`) uses the same `RenderedPrompt` output type but allows any stage name, enabling YAML overrides for AHVS-specific prompts.

### CodeAgent as the execution engine

AHVS does **not** call Promptfoo, DSPy, or Phoenix directly. Instead, it gives CodeAgent:

- The hypothesis description and implementation plan
- The available **skill library** (which tools exist and how to invoke them)
- A required output contract (`result.json` with the metric as a float)
- Instructions that generated files will be applied to a git worktree (repo-relative paths)
- The `eval_command` that will measure the result in the worktree

CodeAgent decides which skill to use, generates all implementation code, and runs it in the sandbox. The generated files are then applied to a **detached git worktree** of the target repo (created at HEAD with `git worktree add --detach`), and the `eval_command` from `baseline_metric.json` is executed inside that worktree to produce a real measurement.

### Worktree execution model

Each hypothesis gets its own worktree under `<cycle_dir>/worktrees/<ID>/`. This ensures:

- **Repo-grounded execution:** Code is tested against the actual repo, not in an isolated sandbox
- **No branch pollution:** Worktrees are detached (no branches created)
- **Safe concurrency:** Each hypothesis has its own copy of the repo
- **Path containment:** All CodeAgent-generated file paths are validated by a shared `validate_safe_relpath()` utility before writing — to both `tool_runs/` and worktree directories. Absolute paths, `..` traversal, and symlink escapes are rejected. The containment check uses `Path.is_relative_to()` (not string-prefix matching) to prevent false-positive bypasses
- **Audit trail:** A `.patch` file is saved for every hypothesis

After all hypotheses run, AHVS identifies the best improvement and keeps its worktree. All other worktrees are cleaned up. The kept worktree path and all patch paths are recorded in `cycle_summary.json`.

If the target path is not a git repository, worktree creation fails gracefully and AHVS falls back to sandbox-only execution with a warning.

---

## 3. The 8-Stage Cycle

```
Stage 1  AHVS_SETUP            Pre-flight checks (baseline, clean repo, LLM connectivity — always runs), cycle dir init
Stage 2  AHVS_CONTEXT_LOAD     Load baseline + EvolutionStore → context_bundle.json
Stage 3  AHVS_HYPOTHESIS_GEN   LLM generates 1–5 typed hypotheses
Stage 4  AHVS_HUMAN_SELECTION  ── GATE ── operator selects which to run
Stage 5  AHVS_VALIDATION_PLAN  LLM writes per-hypothesis implementation plan
Stage 6  AHVS_EXECUTION        CodeAgent executes each hypothesis; worktree + eval_command
Stage 7  AHVS_REPORT_MEMORY    LLM writes cycle report; lessons → EvolutionStore
Stage 8  AHVS_CYCLE_VERIFY     Validate all artifacts; write cycle_summary.json
```

The gate at Stage 4 pauses for human input unless `--auto-approve` is passed. If the operator aborts, the cycle can be resumed from Stage 3 to regenerate hypotheses.

Every stage writes a checkpoint. A failed stage stops the cycle; later stages are not run.

> **Clean repo required:** Stage 1 pre-flight **fails** if the target repo has uncommitted changes. This is a hard requirement because AHVS creates hypothesis worktrees from committed `HEAD` — uncommitted changes in the working tree would not be included in the experiment. Commit or stash changes before starting a cycle.

---

## 4. Quick Start

### Prerequisites

- Python 3.11+
- ARC installed (`pip install -e .` from this repo)
- **API mode:** An API key for a Claude model (or any OpenAI-compatible endpoint)
- **ACP mode:** A local ACP-compatible agent CLI (Claude Code, Codex, etc.) + `acpx`

AHVS supports two LLM modes for its own orchestration calls (hypothesis generation, validation planning, reporting):

| Mode | Flag | API key needed? | What runs the LLM? |
|------|------|-----------------|---------------------|
| API provider (default) | `--provider anthropic` | Yes | Direct API call |
| ACP local agent | `--provider acp` | No (for AHVS) | Claude Code / Codex via acpx |

> **Control-plane vs runtime inference:** The `--provider` flag only controls AHVS's own orchestration LLM calls. Runtime inference inside the target repo's evaluated code (e.g. an OpenAI-powered RAG pipeline) still uses whatever credentials that codebase requires.

### Step 1a — API mode (default)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### Step 1b — ACP mode (no API key needed for AHVS)

```bash
# Ensure acpx is installed
npm install -g acpx

# Use a local agent for AHVS orchestration
researchclaw ahvs \
  --repo /path/to/repo \
  --question "How can we improve answer_relevance?" \
  --provider acp \
  --acp-agent claude   # or codex, gemini, etc.
```

### Step 2 — Onboard your target repo

**Option A: Conversational onboarding (recommended)**

If you're using Claude Code, just tell it what you want:

> "Onboard this repo for AHVS — I want to improve answer relevance"

The `ahvs_onboarding` skill will inspect your repo, identify evaluation paths, ask follow-up questions, and write `.ahvs/baseline_metric.json` for you. It refuses to proceed until the setup is valid. See `skills/ahvs_onboarding/SKILL.md` for details.

**Option B: Manual setup**

Create `.ahvs/baseline_metric.json` in your target repository:

```json
{
  "primary_metric": "answer_relevance",
  "answer_relevance": 0.74,
  "recorded_at": "2026-03-18T10:00:00Z",
  "commit": "abc1234",
  "eval_command": "promptfoo eval --config .ahvs/eval/baseline.yaml"
}
```

### Step 3 — Run a cycle

```bash
researchclaw ahvs \
  --repo /path/to/your-rag-project \
  --question "How can we improve answer_relevance by at least 5%?" \
  --max-hypotheses 3
```

The CLI will pause at Stage 4 and display the generated hypotheses. Enter the IDs you want to test (e.g. `H1 H3`) or `all`.

### Step 4 — Review results

```bash
cat /path/to/your-rag-project/.ahvs/cycles/<timestamp>/cycle_summary.json
cat /path/to/your-rag-project/.ahvs/cycles/<timestamp>/report.md
```

---

## 5. Onboarding a Target Repository

AHVS needs four things from a target repo:

### 5.1 Baseline metric file

`.ahvs/baseline_metric.json` — required fields:

| Field | Description |
|---|---|
| `primary_metric` | Name of the metric to optimise (e.g. `answer_relevance`) |
| `<primary_metric>` | Current numeric value of that metric (float) |
| `recorded_at` | ISO-8601 timestamp when this baseline was measured |
| `eval_command` | Shell command that reproduces the baseline measurement |
| `commit` | Git commit SHA when baseline was recorded. *(Recommended — AHVS emits a pre-flight warning if absent, since it cannot verify the baseline matches the current repo state.)* |

**Example:**
```json
{
  "primary_metric": "f1_score",
  "f1_score": 0.81,
  "recorded_at": "2026-03-18T09:00:00Z",
  "commit": "d4e5f6a",
  "eval_command": "python scripts/eval.py --dataset data/test.jsonl"
}
```

### 5.2 Evaluation setup

Your `eval_command` is **executed in a git worktree** of the target repo after CodeAgent's generated files are applied. It must be reproducible and must write a numeric result that can be parsed.

AHVS extracts metrics using a five-tier strategy (in priority order):

| Tier | Source | When used |
|---|---|---|
| **0** | `eval_command` stdout (run in worktree) | eval_command configured and ran successfully |
| 1 | `result.json` in work_dir or `agent_runs/*/` | Sandbox copy-back |
| 2 | `CodeAgentResult.best_metrics` | Parsed from sandbox stdout |
| 3 | `CodeAgentResult.best_stdout` | Raw `key: value` patterns |
| 4 | `extraction_failed` | All tiers failed — hypothesis is treated as **failed** |

When `eval_command` is empty or missing, Tier 0 is skipped — backward compatible with repos that don't have it. When `eval_command` fails (non-zero exit), AHVS logs a warning and falls through to the sandbox tiers.

**Important:** A hypothesis with `measurement_status="extraction_failed"` is treated as an invalid experiment — it cannot count as "improved" even if the baseline value happens to produce `delta > 0`. If *all* hypotheses in a cycle fail measurement, Stage 8 marks the entire cycle as **FAILED** with an "INVALID CYCLE" recommendation.

### 5.3 Regression guard (optional but recommended)

A shell script that exits 0 if a result passes quality checks, non-zero if it regresses. The guard receives the path to a **canonical `result.json`** as its first argument — this file is always written after metric extraction (from any tier), so the guard never inspects a stale or missing file. **When configured, the guard is fail-closed:** if the script is missing, times out, or throws an error, AHVS treats the guard as failed and rejects the hypothesis.

```bash
# .ahvs/regression_guard.sh
#!/bin/bash
RESULT=$(jq '.answer_relevance' "$1")
# Fail if more than 5% below baseline
python -c "import sys; sys.exit(0 if float('$RESULT') >= 0.70 else 1)"
```

Pass it to AHVS:
```bash
researchclaw ahvs --repo . --question "..." \
  --regression-guard .ahvs/regression_guard.sh
```

### 5.4 Domain context (automatic)

AHVS infers domain tags (`llm`, `rag`, `ml`, `prompt-driven`) by scanning `requirements.txt`, `pyproject.toml`, and `package.json`. These tags guide hypothesis generation without any manual setup.

---

## 6. CLI Reference

```
researchclaw ahvs [options]
```

| Flag | Default | Description |
|---|---|---|
| `--repo`, `-r` | *(required)* | Path to target repository |
| `--question`, `-q` | *(required)* | The cycle question (what to improve) |
| `--max-hypotheses` | `3` | How many hypotheses to generate (max 5) |
| `--auto-approve` | off | Skip interactive gate; run all hypotheses |
| `--from-stage` | *(stage 1)* | Resume from a specific stage name |
| `--resume` | off | Resume from last written checkpoint |
| `--regression-guard` | none | Path to regression guard shell script |
| `--skill-registry` | none | Path to custom skill registry YAML |
| `--prompts` | none | Path to AHVS prompts override YAML |
| `--model` | `claude-opus-4-6` | LLM model ID |
| `--api-key-env` | `ANTHROPIC_API_KEY` | Env var holding the API key |
| `--provider` | `anthropic` | LLM provider: `anthropic`, `openai`, `openai-compatible`, `openrouter`, `deepseek`, `acp` |
| `--acp-agent` | `claude` | ACP agent CLI name (only with `--provider acp`) |
| `--acpx-command` | *(auto-detect)* | Path to acpx binary (only with `--provider acp`) |
| `--acp-session-name` | `researchclaw-ahvs` | ACP session name (only with `--provider acp`) |
| `--acp-timeout` | `1800` | ACP per-prompt timeout in seconds (only with `--provider acp`) |
| `--run-dir` | `<repo>/.ahvs/cycles/<ts>` | Override cycle output directory |

### Resuming a failed cycle

```bash
# From a specific stage:
researchclaw ahvs --repo . --question "..." \
  --from-stage AHVS_HYPOTHESIS_GEN

# From last checkpoint (auto-detects latest cycle under .ahvs/cycles/):
researchclaw ahvs --repo . --question "..." --resume

# Or from a specific cycle directory:
researchclaw ahvs --repo . --question "..." \
  --run-dir .ahvs/cycles/20260318_120000 \
  --resume
```

### Non-interactive / CI mode

```bash
researchclaw ahvs \
  --repo . \
  --question "Can we reduce latency while keeping answer_relevance above 0.74?" \
  --auto-approve \
  --max-hypotheses 2
```

---

## 7. Hypothesis Types

AHVS generates hypotheses of these types. Each type maps to the tools CodeAgent will invoke:

| Type | CodeAgent uses | Required tools |
|---|---|---|
| `prompt_rewrite` | Promptfoo eval | `promptfoo` |
| `model_comparison` | Promptfoo with multiple model configs | `promptfoo` |
| `config_change` | Promptfoo eval on modified config | `promptfoo` |
| `dspy_optimize` | DSPy compile → Promptfoo held-out eval | `dspy`, `promptfoo` |
| `code_change` | Custom Python script + pytest | *(none — uses local sandbox)* |
| `architecture_change` | New module + integration tests in sandbox | *(none — uses local sandbox)* |
| `multi_llm_judge` | Build a judge chain, evaluate with it | *(none — uses local sandbox)* |
| `phoenix_eval` | Arize Phoenix evaluation | `arize-phoenix` |

AHVS runs a secondary pre-flight check *after* hypothesis selection (Stage 4) to verify the tools needed for selected hypothesis types are available. This check skips the LLM connectivity test (already verified at Stage 1) and focuses only on tool availability. If a tool is missing, AHVS warns and asks for confirmation before proceeding.

> **Note:** In the current implementation, all hypothesis types share the same execution path through CodeAgent. The type primarily influences which skills and package hints are injected into CodeAgent's context, and which tools are checked at pre-flight. CodeAgent decides the actual execution strategy based on these inputs.

---

## 8. Skill Library

Skills are pre-built guidance templates injected into CodeAgent's prompt context. CodeAgent reads them, picks the right one, and references it in its implementation plan. Skills are **informational** — they tell CodeAgent what tools are available and how to use them, but AHVS does not enforce or dispatch skill invocations at runtime. The `skill_used` field in `HypothesisResult` reflects the plan's declared skill, not a runtime observation.

### Built-in skills

| Skill | Applicable types |
|---|---|
| `promptfoo_eval` | `prompt_rewrite`, `model_comparison`, `config_change` |
| `dspy_compile` | `dspy_optimize` |
| `phoenix_eval` | `prompt_rewrite`, `model_comparison`, `config_change`, `code_change` |
| `sandbox_run` | `code_change`, `architecture_change`, `multi_llm_judge` |
| `regression_guard` | all types |
| `metric_capture` | all types |

### Adding custom skills

Create a YAML file and pass it with `--skill-registry`:

```yaml
# my_skills.yaml
skills:
  - name: my_custom_eval
    description: >
      Run our internal evaluation harness at scripts/eval.py.
      Reads from data/test.jsonl and writes {"answer_relevance": <float>} to stdout.
    invocation_template: |
      SKILL: my_custom_eval
        entry_point: scripts/eval.py
        dataset: data/test.jsonl
        output_path: tool_runs/{hypothesis_id}/result.json
    applicable_types:
      - prompt_rewrite
      - code_change
    required_tools:
      - python
```

---

## 9. Cross-Cycle Memory

AHVS uses ARC's `EvolutionStore` to persist lessons across cycles. This means:

- **Successful hypotheses** are recorded as positive lessons — future cycles know what worked
- **Failed attempts** (measured but not improved) are marked as rejected approaches — the LLM is explicitly told not to repeat them
- **Infrastructure failures** (`extraction_failed`, `sandbox_error`) are recorded as warnings noting the hypothesis was never actually tested — they do *not* count as rejected approaches, so the idea can be retried in future cycles
- **Errors** during execution are logged as warnings with enough context to diagnose

The EvolutionStore lives at `<repo>/.ahvs/evolution/`. It is cumulative — never cleared between cycles.

At Stage 2 (`AHVS_CONTEXT_LOAD`), AHVS queries the last 12 lessons from the store using structured `LessonEntry` fields (category, severity) — not keyword matching on prose. Lessons with severity `"info"` are treated as positive outcomes; those with `"warning"` or `"error"` are surfaced as rejected approaches. The LLM sees both what has worked and what has been ruled out, producing increasingly targeted hypotheses over time.

---

## 10. Python API

```python
from researchclaw.ahvs import AHVSConfig, execute_ahvs_cycle

config = AHVSConfig(
    repo_path="/path/to/your-rag-project",
    question="How can we improve answer_relevance by 5%?",
    max_hypotheses=3,
    llm_model="claude-opus-4-6",
    llm_api_key_env="ANTHROPIC_API_KEY",
)

results = execute_ahvs_cycle(config, auto_approve=True)

for r in results:
    print(r.stage.name, r.status.value)
```

### Resuming from checkpoint

```python
from pathlib import Path
from researchclaw.ahvs import AHVSConfig, execute_ahvs_cycle, read_ahvs_checkpoint
from researchclaw.ahvs.stages import AHVS_NEXT_STAGE

cycle_dir = Path("/path/to/repo/.ahvs/cycles/20260318_120000")
config = AHVSConfig(
    repo_path="/path/to/repo",
    question="...",
    run_dir=cycle_dir,
)

last_done = read_ahvs_checkpoint(cycle_dir)
from_stage = AHVS_NEXT_STAGE.get(last_done) if last_done else None

results = execute_ahvs_cycle(config, from_stage=from_stage, auto_approve=True)
```

### Stage completion callback

```python
def on_done(stage_result):
    print(f"Stage {stage_result.stage.name}: {stage_result.status.value}")

results = execute_ahvs_cycle(config, on_stage_complete=on_done)
```

### Reading results programmatically

```python
from researchclaw.ahvs.result import load_results

results = load_results(cycle_dir / "results.json")
for r in results:
    print(f"{r.hypothesis_id}: delta={r.delta:+.4f} improved={r.improved}")
```

### Result Fields: `measurement_status`

Each `HypothesisResult` includes a `measurement_status` field that tracks whether the metric was successfully captured. This prevents silent fallback to the baseline value when measurement fails.

| Value | Meaning |
|---|---|
| `"measured"` | Metric was successfully extracted from at least one source |
| `"extraction_failed"` | Hypothesis ran but no metric could be parsed from any source — treated as a **failed** hypothesis (cannot count as improved) |
| `"sandbox_error"` | CodeAgent execution raised an exception before metric extraction |
| `"not_executed"` | Hypothesis was not executed (default state) |

**Five-tier metric extraction strategy** (in priority order):

0. `eval_command` stdout from the hypothesis worktree (highest priority — real repo measurement)
1. `result.json` in the hypothesis work directory (or `agent_runs/*/result.json` from sandbox copy-back)
2. Structured metrics from `CodeAgentResult.best_metrics` (parsed from sandbox stdout)
3. Raw `CodeAgentResult.best_stdout` parsed for `metric_name: value` patterns
4. If all tiers fail, `measurement_status` is set to `"extraction_failed"` and a warning is logged

**Diagnosing `extraction_failed`:**
- Check `tool_runs/<ID>/` for generated files — did CodeAgent produce code?
- Check `tool_runs/<ID>/agent_runs/*/` for sandbox artifacts — did the code run?
- Ensure the hypothesis code writes the metric in a parseable format (JSON or `key: value`)

---

## 11. Configuration Reference

### `AHVSConfig` fields

| Field | Type | Default | Description |
|---|---|---|---|
| `repo_path` | `Path` | *(required)* | Root of target repository |
| `question` | `str` | *(required)* | Cycle question |
| `run_dir` | `Path` | `<repo>/.ahvs/cycles/<ts>` | Cycle output directory |
| `max_hypotheses` | `int` | `3` | Max hypotheses to generate (hard cap: 5) |
| `regression_guard_path` | `Path \| None` | `None` | Path to regression guard script |
| `skill_registry_path` | `Path \| None` | `None` | Custom skills YAML |
| `prompts_override_path` | `Path \| None` | `None` | AHVS prompts override YAML |
| `llm_model` | `str` | `"claude-opus-4-6"` | LLM model ID |
| `llm_api_key_env` | `str` | `"ANTHROPIC_API_KEY"` | API key env var name |
| `llm_base_url` | `str` | `""` | Override LLM base URL |
| `llm_api_key` | `str` | `""` | Inline API key (prefer env var) |

### Derived paths (automatic)

| Path | Location |
|---|---|
| Baseline metric | `<repo>/.ahvs/baseline_metric.json` |
| EvolutionStore | `<repo>/.ahvs/evolution/` |
| Cycle artifacts | `<repo>/.ahvs/cycles/<timestamp>/` |

### Custom prompts override

To override any AHVS stage prompt without touching Python source, create a YAML file and pass it with `--prompts`:

```yaml
# ahvs_prompts.yaml
stages:
  ahvs_hypothesis_gen:
    system: >
      You are a specialist in RAG pipeline optimisation.
      Focus exclusively on retrieval-side improvements.
    max_tokens: 3000
  ahvs_report:
    max_tokens: 2000
```

Only the fields you specify are overridden; unspecified fields retain their defaults.

---

## 12. Directory Layout

### Package structure

```
researchclaw/ahvs/
├── __init__.py          # Public API: execute_ahvs_cycle, AHVSConfig, ...
├── stages.py            # AHVSStage IntEnum, AHVS_STAGE_SEQUENCE, gate rules
├── contracts.py         # AHVSStageContract (input/output/DoD per stage)
├── config.py            # AHVSConfig dataclass
├── result.py            # HypothesisResult — tool-agnostic output contract
├── context_loader.py    # load_context_bundle() — baseline + EvolutionStore
├── health.py            # Pre-flight checks (tools, baseline, guard, branch)
├── skills.py            # SkillLibrary + 6 built-in skills
├── prompts.py           # AHVSPromptManager (3 stage prompts + YAML overrides)
├── worktree.py          # HypothesisWorktree — git worktree lifecycle per hypothesis
├── executor.py          # 8 stage handlers + execute_ahvs_stage() dispatcher
└── runner.py            # execute_ahvs_cycle() — outer orchestration loop

skills/ahvs_onboarding/        # Claude Code onboarding skill
├── SKILL.md                   # Conversational wizard: repo → .ahvs/baseline_metric.json
└── references/                # Policy docs loaded as needed
    ├── artifact_contract.md   # Baseline JSON schema
    ├── eval_command_policy.md  # Eval command acceptance rules
    └── git_mode_policy.md     # Git vs non-git trust model
```

### Per-cycle artifacts

```
<repo>/.ahvs/
├── baseline_metric.json         # Required: baseline metric snapshot
├── evolution/                   # EvolutionStore: cumulative lessons across cycles
└── cycles/
    └── 20260318_120000/         # One directory per cycle run
        ├── ahvs_checkpoint.json      # Stage resumption checkpoint
        ├── cycle_manifest.json       # Cycle metadata + preflight results
        ├── context_bundle.json       # Stage 2 output: baseline + lessons
        ├── hypotheses.md             # Stage 3 output: generated hypotheses
        ├── selection.md              # Stage 4 output: operator selection
        ├── selection.json            # Machine-readable selection
        ├── validation_plan.md        # Stage 5 output: per-hypothesis plans
        ├── results.json              # Stage 6 output: HypothesisResult list
        ├── report.md                 # Stage 7 output: LLM cycle report
        ├── friction_log.md           # Stage 7 output: errors + measurement issues + operator notes
        ├── cycle_summary.json        # Stage 8 output: keep/revert + worktree/patch refs
        ├── worktrees/
        │   └── H1/                   # Git worktree for hypothesis H1 (kept if best)
        └── tool_runs/
            ├── H1/                   # CodeAgent workspace for hypothesis H1
            │   ├── result.json       # Canonical metric result (written after any-tier extraction)
            │   ├── H1.patch          # Diff of all changes applied to worktree
            │   └── <generated files>
            └── H2/
```

---

## 13. Advanced Usage

### Running multiple cycles in sequence

```bash
for i in 1 2 3; do
  researchclaw ahvs \
    --repo /path/to/project \
    --question "How can we further improve answer_relevance?" \
    --auto-approve \
    --max-hypotheses 2
  echo "--- Cycle $i complete ---"
done
```

Each cycle reads the lessons left by the previous one, building progressively more targeted hypotheses.

### Using with OpenAI or OpenRouter

```bash
export OPENAI_API_KEY=sk-...
researchclaw ahvs \
  --repo . \
  --question "..." \
  --model gpt-4o \
  --api-key-env OPENAI_API_KEY
```

For OpenRouter:
```bash
export OPENROUTER_API_KEY=...
researchclaw ahvs \
  --repo . \
  --question "..." \
  --model anthropic/claude-opus-4-6 \
  --api-key-env OPENROUTER_API_KEY
```

### Inspecting what CodeAgent generated

Every hypothesis has its own workspace under `tool_runs/<ID>/`. You can inspect:

- The files CodeAgent generated
- `result.json` — the numeric metric output
- Any intermediate artifacts from Promptfoo/DSPy/custom scripts

### Keeping a successful hypothesis

After reviewing `cycle_summary.json`, you can apply the best hypothesis from its kept worktree or patch file:

```bash
# Option 1: Apply the patch directly
git apply <cycle_dir>/tool_runs/H1/H1.patch

# Option 2: Cherry-pick from the kept worktree (path in cycle_summary.json → kept_worktree)
cd <kept_worktree_path>
git diff --cached  # Review the changes
```

The `cycle_summary.json` includes:
- `kept_worktree`: path to the git worktree of the best hypothesis (if one improved)
- `kept_patch`: path to its `.patch` file (relative to cycle_dir)
- `all_patches`: list of `.patch` paths for every hypothesis (audit trail)
- `all_unmeasured`: `true` if no hypothesis produced a valid measurement (cycle is invalid)
- `hypotheses_measured`: count of hypotheses with successful metric extraction

After applying the change, update the baseline:

```json
{
  "primary_metric": "answer_relevance",
  "answer_relevance": 0.79,
  "recorded_at": "2026-03-18T14:00:00Z",
  "commit": "new-commit-sha",
  "eval_command": "promptfoo eval --config .ahvs/eval/baseline.yaml"
}
```

Run the next cycle with the updated baseline. AHVS will treat the new value as the target to beat.

### Prompt engineering tips

- Keep `--question` specific and metric-anchored: *"Improve answer\_relevance from 0.74 to above 0.78 by improving the retrieval step"* generates better hypotheses than *"make the system better"*.
- Use `--max-hypotheses 2` for faster cycles during exploration; increase to 5 when you want broader coverage.
- The `--auto-approve` flag is safe for unattended runs but be sure your regression guard is set up — it prevents a bad hypothesis from being silently "improved".
