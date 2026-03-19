# AHVS — Adaptive Hypothesis Validation System

AHVS is a cyclic hypothesis-validation pipeline built on top of ARC (AutoResearchClaw). It autonomously generates, selects, executes, and evaluates improvement hypotheses for any target LLM or RAG system — then archives what it learned for the next cycle.

---

## Table of Contents

1. [Overview](#1-overview)
2. [How AHVS Relates to ARC](#2-how-ahvs-relates-to-arc)
3. [The 8-Stage Cycle](#3-the-8-stage-cycle)
4. [Three Ways to Use AHVS](#4-three-ways-to-use-ahvs)
5. [Quick Start](#5-quick-start)
6. [Onboarding a Target Repository](#6-onboarding-a-target-repository)
7. [CLI Reference](#7-cli-reference)
8. [Hypothesis Types](#8-hypothesis-types)
9. [Skill Library](#9-skill-library)
10. [Cross-Cycle Memory](#10-cross-cycle-memory)
11. [Python API](#11-python-api)
12. [Configuration Reference](#12-configuration-reference)
13. [Directory Layout](#13-directory-layout)
14. [Advanced Usage](#14-advanced-usage)
    - [Model Selection Strategy](#model-selection-strategy)
    - [Budget Planning for Experiments](#budget-planning-for-experiments)
    - [Execution Modes](#execution-modes)
    - [Prompt Engineering Tips](#prompt-engineering-tips)

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

If the target path is not a git repository, worktree creation fails and the hypothesis is marked as an error. Pass `--allow-sandbox-only` to permit sandbox-only fallback for non-git targets (see [Execution modes](#execution-modes)).

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

## 4. Three Ways to Use AHVS

AHVS supports three usage modes depending on your workflow. All three produce identical results — same 8-stage cycle, same artifacts, same cross-cycle memory.

### Mode 1: Conversational in Claude Code (recommended for most users)

Just describe what you want in natural language. No commands to memorize.

**Onboarding a new repo:**
```
> Onboard /path/to/my-project for AHVS — I want to improve precision without tanking F1
```

The `ahvs_onboarding` skill will scan your repo, create a headless eval script if needed, write `.ahvs/baseline_metric.json`, and verify everything works.

**Running a cycle:**
```
> Run AHVS on /path/to/my-project — improve precision above 0.80 using only
  Gemini 3.1 Flash Lite. Don't let F1 drop below 0.62. Propose algorithmic
  changes, not just prompt tweaks. Use 2 hypotheses.
```

**Reviewing results:**
```
> Show me the results from the last AHVS cycle on /path/to/my-project
```

**Iterating:**
```
> Run another AHVS cycle — the keyword strategy worked well last time,
  focus on that direction with 3 hypotheses
```

Claude Code reads `.ahvs/baseline_metric.json` for all the details (eval command, constraints, system levers, prior experiments) so you don't need to repeat them every time.

### Mode 2: CLI command

For scripting, CI integration, or when you prefer explicit commands:

```bash
researchclaw ahvs \
  --repo /path/to/my-project \
  --question "Improve precision above 0.80 while keeping F1 >= 0.62" \
  --max-hypotheses 2 \
  --provider openrouter \
  --model anthropic/claude-sonnet-4-6 \
  --api-key-env OPENROUTER_API_KEY
```

Add `--auto-approve` for unattended runs. See [CLI Reference](#7-cli-reference) for all flags.

### Mode 3: Python API

For integration into existing scripts or notebooks:

```python
from researchclaw.ahvs import AHVSConfig, execute_ahvs_cycle

config = AHVSConfig(
    repo_path="/path/to/my-project",
    question="Improve precision above 0.80 while keeping F1 >= 0.62",
    max_hypotheses=2,
    llm_model="claude-sonnet-4-6",
    llm_api_key_env="OPENROUTER_API_KEY",
)

results = execute_ahvs_cycle(config, auto_approve=True)
for r in results:
    print(r.stage.name, r.status.value)
```

See [Python API](#11-python-api) for resumption, callbacks, and result inspection.

### Which mode should I use?

| Scenario | Recommended mode |
|----------|-----------------|
| First time using AHVS | **Conversational** — Claude guides you through onboarding |
| Exploring what to optimize | **Conversational** — describe goals in natural language |
| Running a specific experiment | **CLI** or **Conversational** — both work equally |
| CI/CD integration | **CLI** with `--auto-approve` |
| Scripting multi-cycle campaigns | **CLI** (bash loop) or **Python API** |
| Embedding in existing workflows | **Python API** |

---

## 5. Quick Start

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

> "Onboard this repo for AHVS — I want to improve precision without tanking F1"

The `ahvs_onboarding` skill will:
1. Deep-scan your repo to understand its evaluation pipeline
2. Create a headless CLI eval script if evaluation only exists in notebooks
3. Ask about your optimization goals, budget constraints, and hypothesis diversity
4. Gather prior experiment results to prevent repeating dead ends
5. Write an enriched `.ahvs/baseline_metric.json` with metrics, constraints, system levers, and prior experiments
6. Verify the eval command produces parseable output

It refuses to proceed until the setup is verified. See `skills/ahvs_onboarding/SKILL.md` for details.

**Option B: Manual setup**

Create `.ahvs/baseline_metric.json` in your target repository (minimal):

```json
{
  "primary_metric": "answer_relevance",
  "answer_relevance": 0.74,
  "recorded_at": "2026-03-18T10:00:00Z",
  "commit": "abc1234",
  "eval_command": "python scripts/eval.py --dataset data/test.jsonl"
}
```

For better hypothesis quality, include the enriched fields (see [Section 6.1](#61-baseline-metric-file)).

### Step 3 — Run a cycle

**Option A: Conversational (in Claude Code)**

```
> Run AHVS on /path/to/your-rag-project — improve answer_relevance by at least 5%.
  Use 3 hypotheses.
```

**Option B: CLI**

```bash
researchclaw ahvs \
  --repo /path/to/your-rag-project \
  --question "How can we improve answer_relevance by at least 5%?" \
  --max-hypotheses 3
```

Both modes pause at Stage 4 to display generated hypotheses. Enter the IDs you want to test (e.g. `H1 H3`) or `all`. Pass `--auto-approve` to skip this gate.

### Step 4 — Review results

```bash
cat /path/to/your-rag-project/.ahvs/cycles/<timestamp>/cycle_summary.json
cat /path/to/your-rag-project/.ahvs/cycles/<timestamp>/report.md
```

Or conversationally: `> Show me the results from the last AHVS cycle`

---

## 6. Onboarding a Target Repository

AHVS needs four things from a target repo:

### 6.1 Baseline metric file

`.ahvs/baseline_metric.json` — required fields:

| Field | Description |
|---|---|
| `primary_metric` | Name of the metric to optimise (e.g. `precision`) |
| `<primary_metric>` | Current numeric value of that metric (float) |
| `recorded_at` | ISO-8601 timestamp when this baseline was measured |
| `eval_command` | Headless shell command that prints `metric_name: value` to stdout |
| `commit` | Git commit SHA when baseline was recorded. *(Recommended — AHVS emits a pre-flight warning if absent, since it cannot verify the baseline matches the current repo state.)* |

Enriched fields (optional but strongly recommended — improves hypothesis quality):

| Field | Description |
|---|---|
| `optimization_goal` | Plain English description of what to optimize and constraints |
| `regression_floor` | Secondary metrics with minimum acceptable values, e.g. `{"f1_score": 0.62}` |
| `constraints` | Budget limits, model restrictions, hypothesis scope requirements |
| `system_levers` | Tunable parameters: strategies, modes, algorithmic areas with file paths |
| `prior_experiments` | Results from past experiments with config details and identified problems |
| `notes` | Additional context (dataset size, key insights, known hard cases) |

**Minimal example:**
```json
{
  "primary_metric": "f1_score",
  "f1_score": 0.81,
  "recorded_at": "2026-03-18T09:00:00Z",
  "commit": "d4e5f6a",
  "eval_command": "python scripts/eval.py --dataset data/test.jsonl"
}
```

**Enriched example** (produces better hypotheses):
```json
{
  "primary_metric": "precision",
  "precision": 0.7128,
  "f1_score": 0.6699,
  "recorded_at": "2026-03-19T10:00:00Z",
  "commit": "9c41b35",
  "eval_command": "cd /path/to/project && python -m package.run_eval --eval-only",
  "optimization_goal": "Maximize precision while keeping f1_score >= 0.62",
  "regression_floor": {"f1_score": 0.62},
  "constraints": {
    "model_budget": "Gemini 3.1 Flash Lite only. No expensive models.",
    "hypothesis_scope": "Must include algorithmic changes, not just prompt rewrites."
  },
  "system_levers": {
    "strategies": ["random", "keyword", "semantic"],
    "algorithmic_areas": ["post_selector.py: selection strategy", "parsing.py: threshold tuning"]
  },
  "prior_experiments": {
    "best_precision": {"config": "gpt54_kw_prv2", "precision": 0.76, "f1": 0.57, "problem": "F1 too low"}
  }
}
```

### 6.2 Evaluation setup

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

### 6.3 Regression guard (optional but recommended)

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

### 6.4 Domain context (automatic)

AHVS infers domain tags (`llm`, `rag`, `ml`, `prompt-driven`) by scanning `requirements.txt`, `pyproject.toml`, and `package.json`. These tags guide hypothesis generation without any manual setup.

---

## 7. CLI Reference

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
| `--base-url` | *(per provider)* | Override LLM base URL (required for `openai-compatible`) |
| `--provider` | `anthropic` | LLM provider: `anthropic`, `openai`, `openai-compatible`, `openrouter`, `deepseek`, `acp` |
| `--acp-agent` | `claude` | ACP agent CLI name (only with `--provider acp`) |
| `--acpx-command` | *(auto-detect)* | Path to acpx binary (only with `--provider acp`) |
| `--acp-session-name` | `researchclaw-ahvs` | ACP session name (only with `--provider acp`) |
| `--acp-timeout` | `1800` | ACP per-prompt timeout in seconds (only with `--provider acp`) |
| `--allow-sandbox-only` | off | Allow sandbox-only fallback when worktree creation fails |
| `--apply-best` | off | Auto-apply best improving hypothesis patch and update baseline |
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

## 8. Hypothesis Types

AHVS generates hypotheses of these types. Each type controls what instructions, constraints, and package hints CodeAgent receives:

| Type | Focus area | Required tools |
|---|---|---|
| `prompt_rewrite` | System prompts, few-shot examples, instruction wording | `promptfoo` |
| `model_comparison` | Swap model IDs, compare across providers | `promptfoo` |
| `config_change` | Hyperparameters (temperature, chunk_size, top_k) | `promptfoo` |
| `dspy_optimize` | DSPy modules for programmatic prompt optimization | `dspy`, `promptfoo` |
| `code_change` | Algorithms, retrieval logic, ranking functions, data processing | *(none — uses local sandbox)* |
| `architecture_change` | Pipeline redesign, new components, caching, re-rankers | *(none — uses local sandbox)* |
| `multi_llm_judge` | Multi-model consensus or judge-based evaluation | *(none — uses local sandbox)* |
| `phoenix_eval` | Arize Phoenix evaluation | `arize-phoenix` |

### How types affect execution

All hypothesis types share the same execution engine: **CodeAgent**. There is no separate executor per type. Instead, each type injects **type-specific execution strategies** (defined in `_TYPE_EXECUTION_STRATEGIES` in `executor.py`) that shape CodeAgent's behaviour:

- **System instructions** — type-specific guidance appended to CodeAgent's system prompt (e.g., `code_change` is told to focus on algorithms and retrieval logic, not prompt wording)
- **Constraints** — hard boundaries on what the type may modify (e.g., `prompt_rewrite` is scoped to prompt template files only)
- **Success guidance** — how to measure whether the change achieved its goal
- **Package hints** — which pip packages and tools to prefer

This means the taxonomy controls *what CodeAgent is instructed to do*, not *which runtime engine runs*. A `code_change` hypothesis produces genuinely different code than a `prompt_rewrite` because CodeAgent receives different instructions, constraints, and success criteria — but both flow through the same `CodeAgent.generate()` call.

### Pre-flight tool checks

AHVS runs a secondary pre-flight check *after* hypothesis selection (Stage 4) to verify the tools needed for selected hypothesis types are available. This check skips the LLM connectivity test (already verified at Stage 1) and focuses only on tool availability. If a tool is missing, AHVS warns and asks for confirmation before proceeding.

---

## 9. Skill Library

Skills are pre-built guidance templates injected into CodeAgent's prompt context. CodeAgent reads them, picks the right one, and references it in its implementation plan. Skills are **informational** — they tell CodeAgent what tools are available and how to use them, but AHVS does not enforce or dispatch skill invocations at runtime. The `skill_planned` field in `HypothesisResult` reflects the plan's declared skill, not a runtime observation.

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

## 10. Cross-Cycle Memory

AHVS uses ARC's `EvolutionStore` to persist lessons across cycles. This means:

- **Successful hypotheses** are recorded as positive lessons — future cycles know what worked
- **Failed attempts** (measured but not improved) are marked as rejected approaches — the LLM is explicitly told not to repeat them
- **Infrastructure failures** (`extraction_failed`, `sandbox_error`) are recorded as warnings noting the hypothesis was never actually tested — they do *not* count as rejected approaches, so the idea can be retried in future cycles
- **Errors** during execution are logged as warnings with enough context to diagnose

The EvolutionStore lives at `<repo>/.ahvs/evolution/`. It is cumulative — never cleared between cycles.

At Stage 2 (`AHVS_CONTEXT_LOAD`), AHVS queries the last 12 lessons from the store using structured `LessonEntry` fields (category, severity) — not keyword matching on prose. Lessons with severity `"info"` are treated as positive outcomes; those with `"warning"` or `"error"` are surfaced as rejected approaches. The LLM sees both what has worked and what has been ruled out, producing increasingly targeted hypotheses over time.

---

## 11. Python API

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

## 12. Configuration Reference

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

## 13. Directory Layout

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

## 14. Advanced Usage

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
  --provider openai \
  --model gpt-4o \
  --api-key-env OPENAI_API_KEY
```

For OpenRouter:
```bash
export OPENROUTER_API_KEY=...
researchclaw ahvs \
  --repo . \
  --question "..." \
  --provider openrouter \
  --model anthropic/claude-opus-4-6 \
  --api-key-env OPENROUTER_API_KEY
```

### Inspecting what CodeAgent generated

Every hypothesis has its own workspace under `tool_runs/<ID>/`. You can inspect:

- The files CodeAgent generated
- `result.json` — the numeric metric output
- Any intermediate artifacts from Promptfoo/DSPy/custom scripts

### Keeping a successful hypothesis

**Automatic promotion (recommended):**

Use `--apply-best` to let AHVS apply the winning patch and update the baseline in one step:

```bash
researchclaw ahvs \
  --repo . --question "..." \
  --auto-approve --apply-best
```

When the cycle completes successfully and a hypothesis improved the metric, AHVS will:
1. Run `git apply` with the best hypothesis patch on your working tree
2. Update `.ahvs/baseline_metric.json` with the new metric value and commit SHA
3. Print a confirmation of what was applied

**Manual promotion:**

If you prefer to review before applying, inspect `cycle_summary.json` and apply manually:

```bash
# Apply the patch
git apply <cycle_dir>/tool_runs/H1/H1.patch
```

The `cycle_summary.json` includes:
- `kept_worktree`: path to the git worktree of the best hypothesis (if one improved)
- `kept_patch`: path to its `.patch` file (relative to cycle_dir)
- `all_patches`: list of `.patch` paths for every hypothesis (audit trail)
- `per_hypothesis`: per-hypothesis details including `execution_mode` (`repo_grounded` or `sandbox_only`)
- `all_unmeasured`: `true` if no hypothesis produced a valid measurement (cycle is invalid)

After manual application, update the baseline yourself or let `--apply-best` handle it on the next run.

### Execution modes

By default, AHVS requires repo-grounded execution via git worktrees. If a worktree cannot be created (e.g. non-git target), the hypothesis **fails** rather than silently falling back to sandbox-only mode. This ensures cycle results are always comparable and reproducible.

To permit sandbox-only fallback for non-git directories or single-file projects, pass `--allow-sandbox-only`. Results from sandbox-only execution are stamped with `execution_mode: "sandbox_only"` in `results.json` and `per_hypothesis` in `cycle_summary.json`.

### Model selection strategy

AHVS makes LLM calls at three points in the cycle, each with different quality requirements:

| Call site | What it does | Model recommendation |
|-----------|-------------|---------------------|
| **Hypothesis generation** (Stage 3) | Proposes concrete, diverse improvement strategies | Use the **strongest reasoning model** available (e.g. `claude-opus-4-6`, `o3`). This is the highest-leverage call — a weak model here produces shallow, repetitive hypotheses that waste the entire cycle budget. |
| **Validation planning** (Stage 5) | Writes implementation steps and eval criteria | Same strong model. The plan quality directly determines whether CodeAgent produces useful code. |
| **CodeAgent execution** (Stage 6) | Generates and runs implementation code | Strong model again. This is where real code is written — algorithms, retrieval pipelines, evaluation harnesses. A capable coding model produces implementations that actually test the hypothesis rather than trivial wrappers. |
| **Report writing** (Stage 7) | Summarizes results and extracts lessons | A lighter model is acceptable here (e.g. `claude-sonnet-4-6`, `gpt-4o-mini`) since it only summarizes data that already exists. |

**The general principle:** Invest in intelligence where it has multiplicative impact — hypothesis quality and code quality compound across cycles. A single good hypothesis from a strong model is worth more than five shallow ones from a cheap model.

### Budget planning for experiments

Before running AHVS cycles, estimate your costs:

**Per-cycle cost breakdown (typical):**

| Component | Token usage | Notes |
|-----------|------------|-------|
| Hypothesis generation | ~2K input + ~2K output | One LLM call |
| Validation planning | ~3K input + ~2.5K output | One LLM call |
| CodeAgent execution | ~10–50K per hypothesis | Depends on complexity; `code_change` and `architecture_change` types use more tokens than `prompt_rewrite` |
| Report writing | ~3K input + ~1.5K output | One LLM call |
| **Total per cycle** | **~20–70K tokens** (with 2–3 hypotheses) | |

**Cost control levers:**

- `--max-hypotheses 1–2` for exploratory cycles; save `3–5` for when you have high-confidence directions
- Start with `prompt_rewrite` and `config_change` hypotheses (cheaper, faster) before moving to `code_change` and `architecture_change` (more tokens, longer sandbox runs)
- Use `--auto-approve` carefully — unattended cycles with 5 hypotheses can accumulate cost without human judgment on which ideas are worth testing
- Set up a regression guard early — it prevents wasted cycles on regressions before you inspect results

**Planning a multi-cycle experiment:**

| Phase | Cycles | Strategy |
|-------|--------|----------|
| **Exploration** (1–3 cycles) | 1–2 hypotheses per cycle | Cast a wide net: mix `prompt_rewrite`, `config_change`, `code_change`. Learn which levers move the metric. |
| **Exploitation** (3–5 cycles) | 2–3 hypotheses per cycle | Double down on the type that showed movement. Use prior lessons to refine. |
| **Diminishing returns** | Stop when delta < noise floor | If 2–3 consecutive cycles show no improvement, the metric may be saturated for this approach. Change the question or target a different metric. |

A typical improvement campaign runs 5–10 cycles. Budget accordingly — with a strong model at ~$15/M input tokens, a 5-cycle campaign with 3 hypotheses each costs roughly $5–15 in API calls.

### Prompt engineering tips

- Keep `--question` specific and metric-anchored: *"Improve answer\_relevance from 0.74 to above 0.78 by improving the retrieval step"* generates better hypotheses than *"make the system better"*.
- Use `--max-hypotheses 2` for faster cycles during exploration; increase to 5 when you want broader coverage.
- The `--auto-approve` flag is safe for unattended runs but be sure your regression guard is set up — it prevents a bad hypothesis from being silently "improved".
- Reference concrete code paths in your question when possible: *"The chunking in `src/pipeline/splitter.py` uses fixed 512-token windows — can we improve answer\_relevance by switching to semantic chunking?"* gives CodeAgent much better starting context.
