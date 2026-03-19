# AHVS LLM Manual Plan — AutoResearchClaw Adaptation Analysis

**Date:** 2026-03-17 (revised)
**Branch:** avhs_man_llm
**Purpose:** Map the AHVS LLM Manual Plan (V2) onto the AutoResearchClaw codebase and define the minimum concrete changes needed to adopt ARC as the implementation backbone.

---

## 1. Executive Summary

AutoResearchClaw already implements approximately 70% of the AHVS LLM Manual Plan. The pipeline orchestration, multi-agent hypothesis generation, human gate checkpoints, knowledge archival, report writing, and cycle verification are all present and production-grade.

**Revised framing after clarification:**

ARC's `CodeAgent` is the correct execution engine for AHVS hypotheses — including all invocations of Promptfoo, DSPy, and Phoenix. These tools are not separate "backends" that AHVS wires in independently; they are **tools that CodeAgent calls** as part of implementing and evaluating a hypothesis. This means:

- No standalone `PromptfooBackend` class is required as primary infrastructure
- DSPy and Phoenix follow the same pattern — CodeAgent generates the invocation code and runs it
- Any future eval tool (custom scripts, benchmarks, judge harnesses) follows the same path automatically

**What AHVS provides that CodeAgent alone cannot:** the outer loop — hypothesis lifecycle management, baseline comparison discipline, human selection gates, keep/revert enforcement, and cross-cycle memory accumulation. CodeAgent is a skilled executor; AHVS is the experimental protocol that makes its runs meaningful and cumulative.

The 30% gap is now narrower and cleaner: the main additions required are the AHVS stage set, hypothesis type routing logic, pre-flight dependency checks, and the `.ahvs/` artifact schema mapping.

---

## 2. Why CodeAgent Does Not Replace AHVS

This question deserves an explicit answer: CodeAgent can invoke Promptfoo, DSPy, Phoenix, or any other tool. That capability does not eliminate the need for AHVS. Here is what CodeAgent has no concept of:

| Missing from CodeAgent alone | AHVS provides |
|---|---|
| Generate N candidate hypotheses, let human pick | `AHVS_HYPOTHESIS_GEN` + `AHVS_HUMAN_SELECTION` gate |
| Compare result against a pre-recorded baseline | `baseline_metric.json` + regression guard discipline |
| Revert to clean state if no improvement | Keep/revert enforcement at cycle boundary |
| Remember what failed 3 cycles ago | `EvolutionStore` cross-cycle memory |
| Run H1, H2, H3 and select the best | Multi-hypothesis cycle management |
| Structured `results.json` → `report.md` across cycles | Reporting + artifact schema consistency |

CodeAgent is the **inner loop** (implement + execute one hypothesis). AHVS is the **outer loop** (lifecycle, comparison, discipline, memory). They compose, not compete.

---

## 3. Direct Component Mappings

Every AHVS requirement maps to an existing ARC component.

### 3.1 ClawVault → `evolution.py` + `knowledge/base.py`

ClawVault in the AHVS plan provides four functions:
- `clawvault wake` — load recent repo context at cycle start
- `clawvault search` — find prior decisions and lessons
- `clawvault remember` — store new decisions and lessons
- `clawvault sleep` — checkpoint end of session

ARC's `EvolutionStore` in `researchclaw/evolution.py` implements all four behaviors:

| ClawVault action | ARC equivalent |
|---|---|
| `clawvault wake` | `EvolutionStore.__init__` — loads lessons on instantiation |
| `clawvault search "[question]"` | `EvolutionStore.build_overlay(stage_name)` — time-weighted recall |
| `clawvault remember ...` | `EvolutionStore.append_many(lessons)` |
| `clawvault sleep --summary "..."` | `EvolutionStore.append_many([LessonEntry(category=PIPELINE, ...)])` + flush |

ARC's `knowledge/base.py` provides the Markdown and Obsidian backends for persistent storage, which maps to ClawVault's `vault/decisions/`, `vault/lessons/`, and `vault/handoffs/` directories.

**Action required:** None for V1. Use `EvolutionStore` directly. Map vault subdirectories to ARC's lesson categories (`SYSTEM`, `EXPERIMENT`, `WRITING`, `ANALYSIS`, `LITERATURE`, `PIPELINE`).

### 3.2 AHVS Step 2 (Context Load / `ahvs-context-loader`) → `evolution.py` + Stage 6 `KNOWLEDGE_EXTRACT`

The `ahvs-context-loader` skill must produce `context_bundle.json` containing:
- active question
- current baseline metric
- domain tags
- prior relevant lessons
- rejected approaches

ARC's `evolution.py` already produces time-weighted lesson overlays per stage. The `context_bundle.json` format is a thin wrapper over what `build_overlay()` returns. Baseline metric fields come from `.ahvs/baseline_metric.json`, which is written once by the operator before any cycle runs.

**Action required:** Write a small `ahvs_context_loader.py` module (or a new `BaseAgent` subclass) that calls `EvolutionStore.build_overlay()`, reads `.ahvs/baseline_metric.json`, and serializes `context_bundle.json`. ~60 lines.

### 3.3 AHVS Step 3 (Hypothesis Gen / `ahvs-hypothesis-gen`) → Stage 8 `HYPOTHESIS_GEN`

ARC's Stage 8 multi-agent hypothesis generation is directly applicable. The difference is domain: ARC generates academic research hypotheses from a synthesis of papers; AHVS generates prompt/model/RAG/architecture hypotheses from a context bundle.

The prompt externalization system (`prompts.default.yaml`) makes this a configuration change, not a code change. A new `ahvs_hypothesis_gen` prompt block instructs the agent to generate hypotheses typed by category (see Section 4 — Hypothesis Type Routing).

The AHVS cycle size cap (1–3 default, 5 hard max) maps to ARC's existing agent output constraints.

**Action required:** Add an `ahvs_hypothesis_gen` prompt block to `prompts.default.yaml` with typed hypothesis categories. No code changes required.

### 3.4 AHVS Step 4 (Human Selection) → Gate Stage pattern

ARC already implements human gate checkpoints at Stages 5, 9, and 20. The gate mechanism in `pipeline/runner.py` pauses, surfaces the artifact, waits for approval, and records the decision. The AHVS human selection step (producing `selection.md`) uses this pattern exactly.

**Action required:** Wire a gate at the `AHVS_HUMAN_SELECTION` stage. The gate logic is already written.

### 3.5 AHVS Step 5 (Validation Plan / `ahvs-validation-protocol`) → Stage 9 `EXPERIMENT_DESIGN`

ARC's Stage 9 produces `exp_plan.yaml` specifying baselines, metrics, run order, and success criteria — structurally identical to AHVS's `validation_plan.md`. For AHVS, the validation plan also specifies the **implementation approach** per hypothesis type (see Section 4).

**Action required:** Extend the Stage 9 equivalent to emit a typed execution spec per hypothesis — what CodeAgent should build and what eval method to use.

### 3.6 AHVS Step 6 (Execution / `ahvs-results-capture`) → CodeAgent + Sandbox + Stages 12–14

This is where the architecture is most important to get right.

**CodeAgent is the execution engine.** It receives the typed hypothesis + implementation spec and:
- Generates any required code (new prompt file, new Python module, new eval harness)
- Executes the implementation in ARC's sandbox (`docker_sandbox.py` or `local_sandbox.py`)
- Invokes eval tools (Promptfoo, DSPy, Phoenix, custom scripts) as needed — via subprocess inside the sandbox
- Captures the output metric and normalizes it into `results.json`

This means there is no separate `PromptfooBackend` class sitting between AHVS and CodeAgent. Promptfoo is a CLI tool that CodeAgent calls, just as it might call any other test runner. The `PromptfooResult` dataclass (Section 5.1) is still useful as a typed return value from CodeAgent's output capture, but it is not a standalone execution path.

**For hypotheses that go well beyond prompt changes** (multi-LLM judge, new retrieval strategy, architectural change): CodeAgent generates the full implementation, runs it in sandbox, and the custom eval script captures results. Promptfoo is not involved.

**Action required:** Wire `AHVS_EXECUTION` to invoke ARC's CodeAgent with the typed hypothesis + implementation spec as its problem statement. CodeAgent handles the rest.

### 3.7 AHVS Step 7 (Report + Memory) → Stage 21 `KNOWLEDGE_ARCHIVE` + `evolution.py`

ARC's Stage 21 extracts lessons from all stage outputs and writes them to the evolution store with time-decay. This is precisely what `ahvs-history-writer` does. ARC's Stage 17 report drafting can be repurposed via prompt customization to generate the short cycle `report.md`.

**Action required:** Add an `ahvs_report` prompt block to `prompts.default.yaml` that answers the 7 AHVS reporting questions defined in Section 12 of the AHVS plan.

### 3.8 AHVS Step 8 (Cycle Verification / `ahvs-cycle-verifier`) → Stage 20 `QUALITY_GATE` + `contracts.py`

ARC's `contracts.py` defines `input_files` and `output_files` for every stage, and `runner.py` validates them at stage completion. This is the exact mechanism the AHVS cycle verifier needs.

**Action required:** Define the AHVS artifact contract in `contracts.py` for the new AHVS stages. ARC's runner validates them automatically.

### 3.9 Pipeline Orchestration → `pipeline/runner.py` + `executor.py` + `stages.py`

The AHVS 8-step cycle is a pipeline. ARC's pipeline infrastructure (checkpoint/resume, rollback, gate stages, stage state machine) is fully reusable. The 8 AHVS steps become 8 new `STAGE` enum entries.

**Action required:** Add 8 new entries to the `STAGE` enum in `pipeline/stages.py`. No changes to runner or executor logic.

---

## 4. Hypothesis Type Routing

This is the dispatch logic that determines, for each hypothesis, which implementation path and eval path CodeAgent follows.

```
Hypothesis Type              Implementation Agent        Eval Method
─────────────────────────────────────────────────────────────────────
prompt_rewrite               AHVS agent (LLM call)       Promptfoo or Phoenix
config_change (temp, top_k)  AHVS agent (file edit)      Promptfoo
model_comparison             AHVS agent (config swap)    Promptfoo
dspy_optimize                CodeAgent → DSPy compile    Promptfoo (held-out)
code_change (new strategy)   CodeAgent + Sandbox         Custom eval script
architecture_change          CodeAgent + AIDE tree-search Custom eval script
multi_llm_judge              CodeAgent + Sandbox         Custom eval script
```

The hypothesis type is declared in `hypotheses.md` and propagated into `validation_plan.md`. CodeAgent reads the type and selects its approach. No AHVS code switches on type — it is CodeAgent's input context.

### Routing in practice

**Path A — Eval-only (prompt/config surface):**
```
hypothesis → AHVS agent generates artifact (new_prompt.txt, config_delta.yaml)
           → CodeAgent invokes Promptfoo/Phoenix CLI in sandbox
           → captures metric from JSON output
           → writes results.json
```

**Path B — Code-change (structural/architectural):**
```
hypothesis → CodeAgent generates Python module / new harness
           → Sandbox executes it (docker_sandbox or local)
           → CodeAgent runs custom eval script
           → captures metric from script output
           → writes results.json
```

**Multi-LLM judge example (Path B):**
1. Hypothesis: "Replace single-model scoring with a 3-LLM judge panel (GPT-4o + Claude 3.5 + Gemini 1.5). Does majority-vote scoring reduce score variance?"
2. `AHVS_VALIDATION_PLAN`: specifies type `architecture_change`, eval via custom `run_judge_eval.py`
3. `AHVS_EXECUTION`: CodeAgent generates `judge_panel.py` + `run_judge_eval.py`, executes in sandbox, captures `{"score_variance": 0.03, "majority_agreement_rate": 0.91}`
4. Regression guard checks `majority_agreement_rate >= 0.85`
5. AHVS reports and archives lessons — Promptfoo was never involved

---

## 5. The Remaining Gap — What Needs to Be Added

### 5.1 Typed Result Capture

CodeAgent needs a lightweight normalized result format that all hypothesis types produce. This is not an execution backend — it is a thin data contract CodeAgent writes at the end of each hypothesis run.

**File to add:** `researchclaw/experiment/ahvs_result.py` (~40 lines)

```python
@dataclass
class HypothesisResult:
    hypothesis_id: str            # "H1", "H2", etc.
    hypothesis_type: str          # "prompt_rewrite", "architecture_change", etc.
    primary_metric: str           # metric name
    metric_value: float           # measured value
    baseline_value: float         # from baseline_metric.json
    delta: float                  # metric_value - baseline_value
    regression_guard_passed: bool
    eval_method: str              # "promptfoo", "phoenix", "custom_script", etc.
    artifact_paths: list[Path]    # what was generated
    raw_output_path: Path         # full eval output for audit
    error: str | None
```

This is what CodeAgent writes. `results.json` is a list of `HypothesisResult` dicts. Everything downstream (report, memory, verifier) reads this format.

### 5.2 Promptfoo/Phoenix/DSPy as CodeAgent Tool Invocations

Rather than standalone backend classes, these are **subprocess calls that CodeAgent generates and executes inside the sandbox**. The only infrastructure needed is:
- Pre-flight checks that verify the tools are available before a cycle starts (see 5.3)
- The `HypothesisResult` schema above so CodeAgent knows what to capture

No `PromptfooBackend` class is required as primary architecture. A small utility function for Promptfoo result parsing (~30 lines) can be provided as a helper CodeAgent can reference, but it is not on the critical path.

### 5.3 Dependency Registry + Pre-flight Checks

Pre-flight should be **generalized**, not Promptfoo-specific. Each hypothesis type declares its tool requirements. Pre-flight checks only what the selected hypotheses need.

**File to modify:** `researchclaw/health.py`

```python
HYPOTHESIS_TOOL_REQUIREMENTS: dict[str, list[str]] = {
    "prompt_rewrite":      ["promptfoo"],
    "model_comparison":    ["promptfoo"],
    "dspy_optimize":       ["promptfoo", "dspy"],
    "phoenix_eval":        ["arize-phoenix"],
    "code_change":         ["docker"],
    "architecture_change": ["docker"],
    "multi_llm_judge":     ["docker"],
}

def check_tool(name: str) -> CheckResult:
    """Generic checker: CLI tool (--version), Python package (importlib), Node package (npx)."""
    ...
```

Adding a new tool (Optuna, MLflow, a custom Docker image) requires only a new entry in the registry. `health.py` stays generic.

### 5.4 `.ahvs/` Directory Schema

The AHVS plan uses `.ahvs/` as its root. ARC uses `run_dir/` (set via CLI or config). These are the same concept.

**Option A (recommended):** Set `run_dir = ".ahvs"` in the AHVS config variant. ARC's runner writes all artifacts to `run_dir`. The cycle subdirectory maps to ARC's existing `runs/<run_id>/` structure. No structural changes needed.

### 5.5 `regression_guard.sh` Contract

Add a `regression_guard_path` field to the experiment config. CodeAgent runs this script after each hypothesis and captures the exit code. Exit 0 = safe to keep. Exit non-zero = revert. This is a 5-line addition to `config.py`.

### 5.6 Baseline Metric Pre-flight

AHVS requires `.ahvs/baseline_metric.json` to exist before any cycle starts. Add a pre-flight check that validates the file exists and contains required fields (`primary_metric`, the metric value, `recorded_at`, `commit`, `eval_command`). If missing, fail fast at `AHVS_SETUP`.

---

## 6. Recommended Implementation Path

### Phase 1 — Define the AHVS stage set in ARC (~1 day)

1. Add 8 new entries to `STAGE` enum in `researchclaw/pipeline/stages.py`:
   ```
   AHVS_SETUP
   AHVS_CONTEXT_LOAD
   AHVS_HYPOTHESIS_GEN
   AHVS_HUMAN_SELECTION    # gate stage
   AHVS_VALIDATION_PLAN
   AHVS_EXECUTION
   AHVS_REPORT_AND_MEMORY
   AHVS_CYCLE_VERIFY
   ```

2. Add artifact contracts for each stage in `researchclaw/pipeline/contracts.py`.

3. Add `HypothesisResult` dataclass in `researchclaw/experiment/ahvs_result.py`.

### Phase 2 — Wire CodeAgent into AHVS_EXECUTION (~0.5 day)

Configure `AHVS_EXECUTION` to invoke ARC's existing `CodeAgent` with:
- The selected hypothesis text and type from `selection.md`
- The implementation spec from `validation_plan.md`
- The baseline metric for comparison
- The regression guard path

CodeAgent handles all tool invocations (Promptfoo, DSPy, Phoenix, custom scripts) autonomously within its 5-phase loop. No custom backend wiring is needed.

### Phase 3 — Prompt customizations (~0.5 day)

Add to `prompts.default.yaml`:
- `ahvs_context_load` — produces `context_bundle.json` fields
- `ahvs_hypothesis_gen` — generates typed hypotheses (prompt_rewrite, model_comparison, code_change, architecture_change, etc.)
- `ahvs_validation_plan` — generates `validation_plan.md` with typed implementation spec per hypothesis
- `ahvs_report` — answers the 7 AHVS reporting questions from `results.json`

### Phase 4 — Pre-flight + dependency registry (~0.25 day)

Extend `health.py` with the generalized `HYPOTHESIS_TOOL_REQUIREMENTS` registry and `check_tool()` function.

### Phase 5 — CLI entry point (~0.25 day)

Add an `ahvs` subcommand to `researchclaw/cli.py`:
```bash
researchclaw ahvs --repo . --question "Does adding 3 domain examples improve answer relevance?"
```

---

## 7. What You Do NOT Need to Build

The following are already solved by ARC with zero new code:

- Pipeline orchestration with checkpoint/resume/rollback (`pipeline/runner.py`)
- Human gate checkpoint mechanism (`pipeline/runner.py`)
- Multi-agent hypothesis generation framework (`agents/base.py` + Stage 8 prompts)
- Artifact contract validation per stage (`pipeline/contracts.py`)
- Knowledge archival and lesson extraction (`evolution.py`)
- Time-weighted lesson recall (`EvolutionStore.build_overlay`)
- Report writing via LLM (`pipeline/executor.py` + prompts)
- Cycle verification via contract checks (`pipeline/contracts.py` + `runner.py`)
- MetaClaw cross-run skill injection (`metaclaw_bridge/`)
- **All Promptfoo/DSPy/Phoenix invocation logic** — CodeAgent handles this via its existing code generation + sandbox execution loop. No new backend classes required.

---

## 8. File Change Summary

| File | Change Type | Description |
|---|---|---|
| `researchclaw/pipeline/stages.py` | Add | 8 new `STAGE` enum entries (`AHVS_*`) |
| `researchclaw/pipeline/contracts.py` | Add | Artifact contracts for each AHVS stage |
| `researchclaw/experiment/ahvs_result.py` | New | `HypothesisResult` dataclass — normalized result format all hypothesis types produce |
| `prompts.default.yaml` | Add | 4 new prompt blocks: `ahvs_context_load`, `ahvs_hypothesis_gen`, `ahvs_validation_plan`, `ahvs_report` |
| `researchclaw/health.py` | Add | Generic `HYPOTHESIS_TOOL_REQUIREMENTS` registry + `check_tool()` |
| `researchclaw/cli.py` | Add | `ahvs` subcommand with `--repo` and `--question` args |
| `researchclaw/config.py` | Add | `regression_guard_path` field to experiment config |

No existing files need structural changes. All additions are additive. The `PromptfooBackend` class from the original analysis is removed — its role is absorbed by CodeAgent + the `HypothesisResult` schema.

---

## 9. AHVS Artifact Schema → ARC Path Mapping

| AHVS path | ARC equivalent path |
|---|---|
| `.ahvs/baseline_metric.json` | `.ahvs/baseline_metric.json` (pre-existing, written once by operator) |
| `.ahvs/cycles/YYYYMMDD_HHMMSS/` | `.ahvs/cycles/<run_id>/` (ARC `run_dir`) |
| `.ahvs/cycles/<id>/context_bundle.json` | `<run_dir>/context_bundle.json` |
| `.ahvs/cycles/<id>/hypotheses.md` | `<run_dir>/hypotheses.md` |
| `.ahvs/cycles/<id>/selection.md` | `<run_dir>/selection.md` |
| `.ahvs/cycles/<id>/validation_plan.md` | `<run_dir>/validation_plan.md` |
| `.ahvs/cycles/<id>/results.json` | `<run_dir>/results.json` (list of `HypothesisResult`) |
| `.ahvs/cycles/<id>/report.md` | `<run_dir>/report.md` |
| `.ahvs/cycles/<id>/friction_log.md` | `<run_dir>/friction_log.md` |
| `.ahvs/tool_runs/` | `<run_dir>/tool_runs/` (CodeAgent sandbox outputs) |
| `.ahvs/vault/decisions/` | `evolution/` store (SYSTEM/EXPERIMENT categories) |
| `.ahvs/vault/lessons/` | `evolution/` store (PIPELINE/ANALYSIS categories) |
| `.ahvs/vault/handoffs/` | `evolution/` store (PIPELINE category, `next_cycle` tag) |

---

## 10. Risks and Constraints

### CodeAgent tool invocation scope
CodeAgent must be given explicit permission to invoke external CLI tools (Promptfoo, DSPy, Phoenix, custom scripts) within the sandbox. ARC's sandbox already supports this. The constraint is ensuring CodeAgent's context includes the tool availability information from the pre-flight results so it doesn't attempt tools that aren't installed.

### LLM hypothesis types vs academic hypotheses
ARC's Stage 8 prompt is tuned for academic research hypotheses. The AHVS plan requires typed engineering hypotheses (prompt rewrite, architecture change, etc.). The customization via `prompts.default.yaml` handles this cleanly.

### Cycle size cap enforcement
AHVS imposes a hard cap of 5 hypotheses per cycle. This must be enforced in the `ahvs_hypothesis_gen` prompt and validated in the `AHVS_HYPOTHESIS_GEN` stage contract.

### Keep/revert discipline
AHVS's keep/revert rule requires that each hypothesis starts from a clean baseline state. This is a git discipline concern enforced by the operator, not by ARC. ARC does not manage the git working tree.

---

## 11. Relationship to Future AHVS Iterations

| AHVS Future Work | ARC equivalent readiness |
|---|---|
| V2 — Significance testing (multi-run + p-value) | ARC already runs multiple iterations (Stage 13). Adding scipy p-test to `HypothesisResult` capture is a small addition. |
| V2 — Automated cycle verifier | ARC's `contracts.py` + `runner.py` already automates this. |
| V2 — Skill implementations | ARC's `BaseAgent` + `AgentOrchestrator` is the skill hosting framework. Each AHVS skill becomes a new `BaseAgent` subclass. |
| V3 — Global knowledge promotion | ARC's MetaClaw bridge already implements cross-run lesson promotion. |
| V3 — Batch mode | ARC's pipeline already supports multi-hypothesis runs via stage looping. |
| V4 — ML plan (Optuna, MLflow) | Optuna/MLflow are simply additional entries in `HYPOTHESIS_TOOL_REQUIREMENTS`. CodeAgent invokes them the same way it invokes Promptfoo. |

---

## 12. Conclusion

AutoResearchClaw is the right foundation for the AHVS LLM Manual Plan. The key architectural insight from the revised analysis:

**CodeAgent is AHVS's execution engine, not a peripheral.** It invokes Promptfoo, DSPy, Phoenix, or any other eval tool as needed — no separate backend wrappers required. This makes AHVS-on-ARC naturally extensible to hypotheses that go far beyond prompt tweaking: new retrieval strategies, architectural changes, multi-LLM judge systems, or anything else CodeAgent can implement and measure.

**AHVS is not replaceable by CodeAgent alone.** AHVS provides the outer loop: hypothesis lifecycle, baseline comparison, human gate discipline, keep/revert enforcement, and cross-cycle memory. Without AHVS, CodeAgent runs powerful but undisciplined experiments with no accumulated learning.

Total new code for V1 (revised):

- ~40 lines: `ahvs_result.py` (`HypothesisResult` dataclass)
- ~60 lines: `ahvs_context_loader` agent
- ~50 lines: generic `HYPOTHESIS_TOOL_REQUIREMENTS` registry + `check_tool()` in `health.py`
- ~40 lines: new STAGE entries + contracts
- ~30 lines: CLI subcommand + pre-flight wiring
- ~200 lines: 4 new prompt blocks in `prompts.default.yaml`

**~420 lines total.** Everything else is configuration and prompt customization. No existing ARC code needs structural modification.
