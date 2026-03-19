# AHVS LLM Manual Plan — V2
### Focused Hypothesis Validation Workflow For LLM And RAG Repos

**Philosophy: Start Narrow, Run Real Cycles, Automate Only After Repeated Use**

> This document is the first executable subdivision of the broader AHVS vision. It defines a manual workflow for LLM and RAG repositories only, using existing tools and strong evaluation discipline while avoiding the full complexity of the umbrella multi-domain plan.

---

## 1. Purpose

The goal of this plan is to make AHVS usable now for LLM systems without overbuilding.

This plan exists to:
- Run repeatable hypothesis-validation cycles on real LLM or RAG repos
- Improve prompts, model choice, and retrieval behavior through measurable evaluation
- Preserve useful local knowledge from each cycle
- Reveal which parts of the workflow should be automated later

This plan does **not** try to solve all AI experimentation. It is intentionally narrower than `AHVS_manual_plan.md`.

---

## 2. Scope

### 2.1 In Scope

This workflow is for hypotheses that can be evaluated through Promptfoo or a Promptfoo-compatible held-out eval flow:

- Prompt wording changes
- System prompt changes
- Few-shot example changes
- Model comparison
- Small generation setting changes
- Retrieval parameter changes for RAG
- Context formatting changes for LLM or RAG pipelines
- Optional prompt optimization via DSPy, followed by held-out Promptfoo evaluation

### 2.2 Out Of Scope For V1

These are explicitly deferred:

- General ML training workflows
- Optuna-driven hyperparameter search
- MLflow-based experiment tracking as a required dependency
- AIDE or structural code mutation search
- Global cross-repo promotion workflows
- Large batch research cycles
- Fully autonomous hypothesis selection or execution

> **Cycle size rule:** Default cycle size is 1-3 hypotheses. The hard cap in V1 is 5 hypotheses. Anything beyond that belongs to a future batch-oriented workflow.

---

## 3. Core Philosophy

This LLM workflow is built on four principles:

**Use existing tools first.** Promptfoo is the main evaluation engine. DSPy is optional for prompt optimization hypotheses. The workflow should compose existing tools rather than rebuild them.

**Keep humans at the right checkpoints.** Hypothesis selection is human. Final keep/revert judgment is human. Report review is human. The system supports judgment; it does not replace it.

**Preserve local memory from day one.** ClawVault is a required local memory layer in V1 so the workflow accumulates decisions, rejections, and next-step context across cycles.

**Stay strict on evidence.** Every hypothesis is compared against a recorded baseline using a stable eval set and a required regression guard.

---

## 4. Tool Backbone

This plan intentionally uses a small tool set.

| Tool | Role In LLM Plan | Required? |
|---|---|---|
| **Promptfoo** | Primary eval engine for prompt/model/RAG hypotheses | Yes |
| **ClawVault** | Local context loading, local search, cycle memory, handoff | Yes |
| **DSPy** | Optional prompt optimization path for certain hypotheses | Optional |
| **git** | Cycle branch, keep/revert discipline, reproducibility | Yes |

### 4.1 Execution Routing

Use the following routing rule:

```text
standard prompt/model/RAG hypotheses      -> Promptfoo
prompt optimization hypothesis            -> DSPy compile -> Promptfoo held-out eval
all cycles                                -> ClawVault for local memory
all cycles                                -> git keep/revert discipline
```

### 4.2 What Is Not Required In V1

The following tools are not part of the default LLM workflow:

- MLflow
- Optuna
- AIDE
- global knowledge repo sync
- multi-agent orchestration templates

They may appear later, but they are not part of the required operator path for this document.

---

## 5. Repo Prerequisites

Before any AHVS LLM cycle starts, the target repo must have:

- A stable eval dataset or stable Promptfoo test cases
- A clearly defined primary metric
- A recorded baseline result
- A repo-local `regression_guard.sh`
- A clean cycle branch
- Promptfoo installed and runnable
- ClawVault initialized locally for the repo

If any of these are missing, the repo is not ready for an AHVS LLM cycle.

### 5.1 Baseline Metric Contract

The repo must store a baseline metric file at:

```text
.ahvs/baseline_metric.json
```

Required shape (consistent with `AHVS_manual_plan.md` Section 3.5 Step 1):

```json
{
  "primary_metric": "answer_relevance",
  "answer_relevance": 0.81,
  "recorded_at": "2026-03-16T10:30:00Z",
  "commit": "abc123def456",
  "eval_command": "promptfoo eval --config eval.yaml"
}
```

Fields:

- `primary_metric`: the name of the metric that governs keep/revert decisions — must match a key in the eval output
- the primary metric key itself (e.g. `"answer_relevance": 0.81`) — the actual baseline number
- `recorded_at`: ISO timestamp of when the baseline was recorded
- `commit`: the exact git commit hash the baseline was measured on — enables reproduction of the baseline at any future point
- `eval_command`: the exact command that produces the eval output — so any operator can re-run it without guessing

> **Why `eval_command` is required:** Without it, a different operator picking up the repo weeks later has no reliable way to know whether to run `python eval.py --output json` or `promptfoo eval --config eval.yaml`. See `AHVS_manual_plan.md` Section 3.1.1 for full discussion.

Rules:

1. The `primary_metric` is the metric of record for keep/revert decisions.
2. The baseline must correspond to a known commit.
3. If the eval dataset changes materially, the baseline must be re-recorded.
4. A cycle compares all tested hypotheses against the baseline, not just against one another.

### 5.2 Regression Guard Contract

Every repo must provide:

```bash
bash regression_guard.sh
```

Exit code contract:

- `0` = pass
- non-zero = fail

The guard can check:

- latency thresholds
- cost thresholds
- existing tests
- lint or schema checks
- RAG-specific safety or format checks

If the primary metric improves but the regression guard fails, the hypothesis is rejected.

---

## 6. Local Structure

Each repo should maintain the following local structure:

```text
.ahvs/
  baseline_metric.json
  cycles/
    YYYYMMDD_HHMMSS/
      context_bundle.json
      hypotheses.md
      selection.md
      validation_plan.md
      promptfoo_H1.yaml
      promptfoo_H2.yaml
      dspy_H3.py              # optional — DSPy hypotheses only
      promptfoo_H3_dspy_eval.yaml  # optional — DSPy hypotheses only
      results.json
      report.md
      friction_log.md
  tool_runs/                  # raw tool outputs — consistent with umbrella plan
    promptfoo/                # Promptfoo JSON output files per hypothesis
    dspy/                     # DSPy compiled program outputs per hypothesis
  vault/                      # ClawVault vault root
    decisions/
    lessons/
    tasks/
    backlog/
    handoffs/
  .clawvault/
```

> **Why `tool_runs/` not `raw_results/`:** The umbrella plan (`AHVS_manual_plan.md`) stores raw tool outputs in `.ahvs/tool_runs/` so that `ahvs-results-capture` (Skill 6) has a consistent input path across all repos and all plan variants. This LLM plan uses the same structure to ensure compatibility when the skill is built.

### 6.1 Artifact Roles

- `context_bundle.json`: current question, repo context, prior relevant lessons, selected execution path
- `hypotheses.md`: ranked candidate hypotheses
- `selection.md`: human choices and rationale
- `validation_plan.md`: exact execution plan, success criteria, guard command, run order
- `promptfoo_*.yaml`: Promptfoo eval config for standard hypotheses
- `dspy_HX.py`: DSPy optimization script for optional DSPy-type hypotheses
- `promptfoo_HX_dspy_eval.yaml`: held-out Promptfoo eval for DSPy output
- `tool_runs/promptfoo/`: raw Promptfoo JSON outputs per hypothesis — read by `ahvs-results-capture`
- `tool_runs/dspy/`: DSPy compiled program outputs — read by `ahvs-results-capture`
- `results.json`: normalized cycle result record
- `report.md`: short human-readable summary
- `friction_log.md`: required observations about process overhead or confusion

---

## 7. ClawVault In V1

ClawVault is a required dependency in this LLM plan, but its scope is local-first.

### 7.1 Role

ClawVault is used for:

- loading recent repo context at the start of the cycle
- finding prior successful or rejected hypotheses
- storing cycle decisions and lessons
- storing handoff context for the next cycle
- checkpointing the end of the session

### 7.2 Local-First Rule

In V1, all knowledge remains local to the repo.

This means:

- No required global knowledge repo
- No required cross-repo promotion workflow
- No required synchronization beyond the local repo vault

The objective of V1 is to prove that local cycle memory is useful before expanding to shared/global memory.

### 7.3 Minimum ClawVault Actions Per Cycle

At minimum, each cycle should use:

```text
clawvault wake
clawvault search "[active question]"
clawvault remember ...
clawvault sleep --summary "..."
```

The exact wrapper skill names may vary later, but this behavior is required in the manual workflow.

---

## 8. Supported Hypothesis Types

Only hypotheses that fit the evaluation backbone should be used in V1.

### 8.1 Standard Promptfoo Hypotheses

These should be the default:

- Rewrite a prompt instruction
- Add or remove few-shot examples
- Change the system prompt
- Compare models
- Change temperature or decoding-related settings when supported
- Adjust retrieval settings such as `top_k`
- Reformat context injected into the prompt

### 8.2 Optional DSPy Hypotheses

Use DSPy only when the hypothesis is fundamentally:

> "Find a better prompt/program structure for this task and metric."

DSPy is not the default path. It is an optional branch for prompt optimization hypotheses where manual prompt variants are not the best framing.

DSPy flow:

1. Compile or optimize the prompt/program
2. Save the optimized output or program metadata
3. Run held-out Promptfoo evaluation on the optimized result
4. Compare the held-out result to baseline using the same keep/revert rules as standard hypotheses

---

## 9. Cycle Flow

This plan uses an 8-step operator workflow. Each step maps directly to a named skill from the umbrella AHVS plan (`AHVS_manual_plan.md`). The skill names are preserved here — even though the skills are not yet built — so that each cycle run also acts as a specification test for the skills that will be built next.

```
┌──────────────────────────────────────────────────────────────────┐
│                  ONE AHVS LLM CYCLE                              │
├────┬─────────────────────────────────────────────────────────────┤
│ 1  │ Cycle Setup          [Manual — no skill yet]                │
│ 2  │ Context Load         [SKILL: ahvs-context-loader]           │
│ 3  │ Hypothesis Gen       [SKILL: ahvs-hypothesis-gen]           │
│ 4  │ Human Selection      [HUMAN CHECKPOINT]                     │
│ 5  │ Validation Plan      [SKILL: ahvs-validation-protocol]      │
│ 6  │ Execution + Results  [Step 5 execution + ahvs-results-capture]│
│ 7  │ Report + Memory      [ahvs-report-writer + ahvs-history-writer]│
│ 8  │ Cycle Verification   [SKILL: ahvs-cycle-verifier — simplified]│
└────┴─────────────────────────────────────────────────────────────┘
```

> **Rule:** Never skip a step. If a step feels unnecessary for a given cycle, note it in the friction log — that is data. Do not silently omit it.

---

### Step 1 — Cycle Setup

Before work begins:

- Confirm `.ahvs/baseline_metric.json` exists
- Confirm Promptfoo is installed and runnable
- Confirm `regression_guard.sh` exists
- Confirm the repo is on a clean cycle branch
- Create a new cycle directory under `.ahvs/cycles/`
- Write the active question in plain language

Output:

- cycle directory created

### Step 2 — Context Load `[SKILL: ahvs-context-loader]`
*Umbrella plan reference: Skill 1. Input: repo path + active question. Output: `context_bundle.json`.*

Start the cycle by loading repo-local memory and current context.

Actions:

- Run `clawvault wake`
- Search local vault for relevant prior decisions and lessons
- Inspect current repo state and baseline info
- Produce `context_bundle.json`

The context bundle should include:

- active question
- repo path
- current baseline metric
- domain tags such as `llm_prompt` or `rag_retrieval`
- prior relevant lessons
- rejected approaches worth avoiding
- whether the likely backend is `promptfoo` or `dspy -> promptfoo`

Output:

- `context_bundle.json`

### Step 3 — Hypothesis Generation `[SKILL: ahvs-hypothesis-gen]`
*Umbrella plan reference: Skill 2. Input: `context_bundle.json`. Output: `hypotheses.md`.*

Generate a ranked list of candidate hypotheses from the context bundle.

Rules:

- Default target: 1-3 hypotheses
- Hard cap: 5 hypotheses
- Prefer concrete, isolated changes
- Prefer lower-cost, higher-signal experiments first
- Avoid repeating recently rejected ideas unless context changed

For each hypothesis record:

- ID
- title
- exact change
- expected effect
- backend
- confidence
- cost estimate
- prior evidence

Output:

- `hypotheses.md`

### Step 4 — Human Selection `[HUMAN CHECKPOINT]`
*Umbrella plan reference: Step 3 human checkpoint. Input: `hypotheses.md`. Output: `selection.md`.*

Human review is mandatory.

The cycle runner reviews `hypotheses.md` and writes:

- which hypotheses were selected
- which were deferred
- why the selected set is the right size for this cycle

Selection rules:

- Prefer 1-3 hypotheses
- Do not exceed 5
- Keep the selected set small enough to finish carefully in one cycle
- If a DSPy hypothesis is selected, note that it is more expensive than standard Promptfoo variants

Output:

- `selection.md`

### Step 5 — Validation Plan `[SKILL: ahvs-validation-protocol]`
*Umbrella plan reference: Skill 4. Input: `selection.md` + `context_bundle.json`. Output: `validation_plan.md` + Promptfoo YAML files + optional DSPy script.*

Translate selected hypotheses into an explicit execution plan.

The validation plan must define:

- selected hypotheses
- execution order
- backend per hypothesis
- Promptfoo config path(s)
- DSPy script path if needed
- primary metric
- regression guard command
- success condition
- keep/revert rule

Outputs:

- `validation_plan.md`
- `promptfoo_HX.yaml` for each standard hypothesis
- optional `dspy_HX.py`
- optional `promptfoo_HX_dspy_eval.yaml`

### Step 6 — Execution And Results Capture `[Step 5 execution + SKILL: ahvs-results-capture]`
*Umbrella plan reference: Step 5 (execution) + Skill 6. This step is compressed in V1 — execution and results normalisation are combined. In the umbrella plan they are separate. Input: `validation_plan.md` + Promptfoo configs. Output: `tool_runs/` raw files + `results.json`.*

Run hypotheses one at a time.

Per-hypothesis rule:

1. Start from clean baseline state
2. Apply the hypothesis change
3. Run the backend
4. Run `regression_guard.sh`
5. Normalize results
6. Make keep/revert decision
7. Return to clean state before the next hypothesis unless the kept change is intentionally committed

#### Standard Promptfoo Path

```bash
promptfoo eval --config .ahvs/cycles/YYYYMMDD_HHMMSS/promptfoo_H1.yaml \
               --output json > .ahvs/tool_runs/promptfoo/h1_results.json
bash regression_guard.sh
# Then: keep or revert per Section 10
```

#### Optional DSPy Path

```bash
python .ahvs/cycles/YYYYMMDD_HHMMSS/dspy_H3.py
# Output: .ahvs/tool_runs/dspy/h3_optimized.json
promptfoo eval --config .ahvs/cycles/YYYYMMDD_HHMMSS/promptfoo_H3_dspy_eval.yaml \
               --output json > .ahvs/tool_runs/promptfoo/h3_dspy_results.json
bash regression_guard.sh
# Then: keep or revert per Section 10
```

#### Validation Rigor Rule

Default:

- one run per hypothesis is enough

Rerun only when:

- the result is close to baseline
- the output appears unstable
- there is visible noise that makes the decision unclear

### Step 7 — Report And Memory Update `[SKILL: ahvs-report-writer + ahvs-history-writer]`
*Umbrella plan reference: Skill 7 + Skill 8. This step is compressed in V1 — reporting and memory writing are combined. In the umbrella plan they are separate. Input: `results.json` + `selection.md`. Output: `report.md` + `friction_log.md` + ClawVault vault entries.*

Close the cycle by writing the human-readable summary and updating local memory.

Actions:

- write `report.md`
- complete `friction_log.md`
- store decisions and lessons in ClawVault
- store handoff notes for the next cycle
- run `clawvault sleep --summary "..."`

Outputs:

- `report.md`
- `friction_log.md`
- new local ClawVault entries in `decisions/`, `lessons/`, and `handoffs/`

### Step 8 — Cycle Verification `[SKILL: ahvs-cycle-verifier — simplified]`
*Umbrella plan reference: Skill 10. This is a simplified version of the full `ahvs-cycle-verifier`. The full verifier also pushes to GitHub and writes to the global knowledge index — both deferred to a future iteration. This V1 version performs local artifact checks and ClawVault checkpoint validation only.*

This step is mandatory and always last. It runs after the friction log is complete. Its purpose is to catch silent failures — a missing `results.json`, a ClawVault sleep that didn't run, a report section that was skipped.

**Checks performed (manual in V1 — will be automated by `ahvs-cycle-verifier` skill):**

```
✓ context_bundle.json         — exists in cycle directory, valid JSON
✓ hypotheses.md               — exists, contains ≥1 hypothesis block
✓ selection.md                — exists, contains ≥1 selected hypothesis
✓ validation_plan.md          — exists, all selected hypotheses have a plan entry
✓ tool_runs/promptfoo/        — contains output file(s) for each executed hypothesis
✓ results.json                — exists, valid JSON, all planned hypotheses present
✓ report.md                   — exists, all 7 reporting questions answered
✓ friction_log.md             — exists and non-empty (all 4 sections filled in)
✓ vault/decisions/            — new entry exists for each promoted hypothesis
✓ vault/lessons/              — new cycle lesson entry exists
✓ vault/handoffs/             — next cycle context entry exists
✓ .clawvault/last-checkpoint.json — updated timestamp confirms clawvault sleep ran
```

**How to run in V1 (manually check each item above):**

```bash
# Check all required cycle files exist:
CYCLE=".ahvs/cycles/YYYYMMDD_HHMMSS"
ls $CYCLE/context_bundle.json $CYCLE/hypotheses.md $CYCLE/selection.md \
   $CYCLE/validation_plan.md $CYCLE/results.json $CYCLE/report.md $CYCLE/friction_log.md

# Validate JSON files parse correctly:
python -c "import json; json.load(open('$CYCLE/context_bundle.json'))" && echo "context_bundle OK"
python -c "import json; json.load(open('$CYCLE/results.json'))" && echo "results OK"

# Confirm ClawVault sleep ran (checkpoint timestamp is recent):
cat .ahvs/.clawvault/last-checkpoint.json

# Confirm tool_runs has output for each hypothesis:
ls .ahvs/tool_runs/promptfoo/
```

**On failure:** Identify which check failed. Fix the missing artifact before closing the cycle. Do not start a new cycle until the current one passes all checks.

**On success:** The cycle is complete. Note the cycle ID in the team log or Slack if applicable.

> **Future iteration:** This manual checklist will be replaced by the `ahvs-cycle-verifier` skill, which also pushes the `.ahvs/` directory to GitHub and appends a summary to the global `index.jsonl`. See Section 18 (Future Work).

Output:
- cycle verification complete (all checks passed)
- any failures logged to `friction_log.md`

---

## 10. Keep/Revert Discipline

This is mandatory.

Rules:

1. Every hypothesis starts from the same clean baseline state.
2. A hypothesis may be kept only if the primary metric improves and the regression guard passes.
3. A rejected hypothesis must be fully reverted before the next one begins.
4. A kept hypothesis should be committed on the cycle branch before moving on.
5. No hypothesis may inherit accidental repo changes from a previous one.

If repo state becomes ambiguous, stop and restore a known clean state before continuing.

---

## 11. Result Schema

Each cycle must produce a normalized:

```text
.ahvs/cycles/<cycle_id>/results.json
```

**V1 schema** (deliberately simplified from the umbrella plan — see note below):

```json
{
  "cycle_id": "20260316_103000",
  "primary_metric": "answer_relevance",
  "baseline_value": 0.81,
  "hypotheses": [
    {
      "id": "H1",
      "title": "Add three domain-specific exemplars",
      "backend": "promptfoo",
      "metric_value": 0.85,
      "delta": 0.04,
      "regression_guard_passed": true,
      "decision": "keep",
      "tool_output_ref": ".ahvs/tool_runs/promptfoo/h1_results.json",
      "notes": "Improved metric without failing secondary checks."
    }
  ]
}
```

Each hypothesis entry must record:

- `id`: hypothesis ID
- `title`: short description of what was tested
- `backend`: `promptfoo` or `dspy+promptfoo`
- `metric_value`: absolute value of the primary metric after the hypothesis
- `delta`: difference from baseline (`metric_value - baseline_value`)
- `regression_guard_passed`: `true` or `false`
- `decision`: `keep` or `revert`
- `tool_output_ref`: path to the raw Promptfoo output file in `tool_runs/` — required for traceability
- `notes`: brief human observation about the result

> **V1 simplification note:** This schema is a deliberately simplified subset of the umbrella plan's `results.json` (defined in `AHVS_manual_plan.md` Skill 6). Fields deferred to a future iteration: `significance` (p-value testing), `success_criteria_met`, `cost_actual`, `protocol_violations`, and `promoted_config`. These omissions are intentional for V1 — the goal is to run real cycles with minimal overhead. See Section 18 (Future Work) for when these will be added.

> **On significance testing:** The umbrella plan requires paired t-tests (p < 0.05) across multiple runs. V1 uses single-run comparison against baseline. This is a deliberate trade-off — running 5 repetitions per hypothesis adds significant time and cost to early cycles. The friction log should track whether single-run decisions prove reliable. If a pattern of noisy or unstable results appears, significance testing should be added immediately regardless of the iteration plan.

---

## 12. Reporting Standard

Each cycle report should answer:

1. What question did this cycle test?
2. Which hypotheses were selected?
3. What improved?
4. What failed?
5. What was kept and why?
6. What should be tested next?
7. What friction did the cycle runner experience?

The report should stay short, factual, and comparable across cycles.

---

## 13. Friction Log Standard

Every cycle must include `friction_log.md`.

Minimum format:

```md
## What felt slow
- Writing Promptfoo configs manually

## What felt unclear
- Whether retrieval_k should be isolated from prompt wording in this cycle

## What almost got skipped
- Writing the report after a failed cycle

## What should be automated later
- Normalizing Promptfoo output into results.json
```

The friction log is the main evidence source for later automation work.

---

## 14. Example Scenarios

This plan should support at least these real cycle types:

- Prompt rewrite on a classification or extraction task
- Few-shot addition versus baseline prompt
- Model A versus Model B comparison
- RAG retrieval parameter change measured on a fixed eval set
- DSPy optimization followed by held-out Promptfoo evaluation
- A hypothesis that improves the primary metric but fails the regression guard
- A cycle where no hypothesis is promoted

---

## 15. Success Criteria

This V1 plan is successful if:

- one engineer can run it end-to-end without building new orchestration software
- multiple cycles can be run with consistent artifacts
- local ClawVault memory prevents repeated bad experiments
- the process is light enough to be used regularly
- the friction log makes future automation priorities obvious

---

## 16. Relationship To The Umbrella AHVS Plan

`AHVS_manual_plan.md` (V7) is the broader umbrella design and remains the authoritative source for all definitions, contracts, templates, and protocols. This document is a narrowed, first-executable subdivision of it.

**How to read the two documents together:**

| This LLM plan | Umbrella plan reference |
|---|---|
| Section 5 (Repo Prerequisites) | Sections 3.1, 3.1.1, 3.1.2 — eval script and regression guard detail |
| Section 5.1 (Baseline Metric) | Section 3.5 Step 1 — full baseline recording walkthrough |
| Section 6 (Local Structure) | Section 3.3 — full `.ahvs/` directory spec |
| Section 7 (ClawVault) | Section 3.3, 3.4, 3.5 Step 3 — ClawVault init and session setup |
| Section 9 Step 1 (Cycle Setup) | Section 3.5 Steps 6–7 — regression guard and cycle branch creation |
| Section 9 Step 2 (Context Load) | Skill 1 (`ahvs-context-loader`) full spec |
| Section 9 Step 3 (Hypothesis Gen) | Skill 2 (`ahvs-hypothesis-gen`) full spec |
| Section 9 Step 5 (Validation Plan) | Skill 4 (`ahvs-validation-protocol`) full spec including config file templates |
| Section 9 Step 6 (Execution + Results) | Step 5 execution + Skill 6 (`ahvs-results-capture`) full spec |
| Section 9 Step 7 (Report + Memory) | Skill 7 (`ahvs-report-writer`) + Skill 8 (`ahvs-history-writer`) full spec |
| Section 9 Step 8 (Cycle Verification) | Skill 10 (`ahvs-cycle-verifier`) full spec |
| Section 10 (Keep/Revert Discipline) | Step 5 Keep/Revert Discipline section in umbrella plan |
| Section 11 (Result Schema) | Skill 6 `results.json` full schema in umbrella plan |
| Section 3.6 (Mid-Cycle Recovery) | Not in this document — see `AHVS_manual_plan.md` Section 3.6 |

**What this plan omits from the umbrella plan (deferred to future iterations):**

- MLflow, Optuna, AIDE (out of scope for LLM-only work)
- Global knowledge repo sync (Skill 9, `ahvs-knowledge-organizer`)
- Significance testing (p-values via scipy)
- GitHub push in cycle verifier
- Multi-repo cross-repo knowledge patterns
- Skill 3 (`ahvs-hypothesis-gen` structural mutation path)

**What this plan adds over the umbrella plan:**

- Explicit cycle size cap (1–3 default, 5 hard maximum) — not defined in umbrella
- Local-first ClawVault rule — global knowledge is optional, not required
- Compressed steps 6 and 7 — practical simplification for V1

The ML workflow will be written separately as `AHVS_ML_manual_plan.md` when LLM cycles are running smoothly.

---

## 17. Future Work

The purpose of V1 is to produce real usage evidence — through actual cycles on real repos — that tells us which of the following extensions are worth building and in what order. None of these should be built speculatively. Each should be triggered by evidence from the friction log or observed failure patterns.

### V2 — Significance Testing

**Trigger:** The friction log shows single-run decisions are unreliable — e.g., a hypothesis is kept one cycle but its improvement disappears in the next.

Add multi-run execution (3–5 runs per hypothesis) and p-value computation (scipy paired t-test, threshold p < 0.05) to Step 6. Add `significance` field to `results.json`. This is fully defined in `AHVS_manual_plan.md` Skill 6 — it just needs to be switched on.

### V2 — Automated Cycle Verifier

**Trigger:** The manual Step 8 checklist is consistently skipped or rushed.

Replace the manual checklist in Step 8 with the `ahvs-cycle-verifier` skill built from the spec in `AHVS_manual_plan.md` Skill 10. Add GitHub push of `.ahvs/` on successful verification.

### V2 — Skill Implementations

**Trigger:** Any step in the cycle is consistently slow, error-prone, or requires repeated manual effort.

Build the named skills in priority order from the umbrella plan's TODO list: `ahvs-context-loader` first, then `ahvs-hypothesis-gen`. Each skill built converts a manual step into an invocable skill call. See `TODO_List.md` Phase 2 for the full build sequence.

### V3 — Global Knowledge Promotion

**Trigger:** After ≥6 cycles across ≥2 repos, local ClawVault lessons are consistently useful and patterns emerge that clearly generalise beyond one repo.

Add `ahvs-knowledge-organizer` (Skill 9) to Step 7, producing `global_candidates.md`. Add the cycle runner promotion workflow. Create `blackbird-ahvs-knowledge` global repo. Fully defined in `AHVS_manual_plan.md` Skill 9 and Section 3.2.

### V3 — Batch Mode

**Trigger:** The team wants to run more than 5 hypotheses per cycle, or needs to sweep a large hypothesis space systematically.

Define a batch-oriented workflow variant with relaxed cycle size caps and a higher tolerance for automated execution. This is out of scope until the single-cycle workflow is well-established.

### V4 — ML Plan

**Trigger:** There is a real ML or algorithm repo that needs hypothesis validation with Optuna or AIDE.

Write `AHVS_ML_manual_plan.md` as the second operational subdivision, re-using all contracts from this document and adding MLflow + Optuna backends. `AHVS_manual_plan.md` Section 2 already defines the full routing logic for ML domains.

---

## 18. Document History

| Version | Date | Changes |
|---|---|---|
| V1 | 2026-03-16 | Initial draft. 7-step LLM-focused workflow, Promptfoo + ClawVault + DSPy (optional) tool set, local-first knowledge, regression guard contract, keep/revert discipline, cycle size cap (1–3 default, 5 hard max). Scoped as first executable subdivision of `AHVS_manual_plan.md`. |
| V2 | 2026-03-16 | Consistency and completeness pass against `AHVS_manual_plan.md` V7. Eight changes: (1) Step 8 (Cycle Verification) added — simplified `ahvs-cycle-verifier` with manual checklist covering all required artifact checks and ClawVault checkpoint validation. (2) Skill chain diagram added to Section 9 header — each step now references its umbrella plan skill name and I/O contract. (3) Directory structure fixed — `raw_results/` replaced with `tool_runs/promptfoo/` and `tool_runs/dspy/` consistent with umbrella plan. (4) `baseline_metric.json` schema updated — added required `eval_command` field; named primary metric key used instead of generic `value`. (5) `results.json` schema updated — added `tool_output_ref` field; explicit V1 simplification note documents deferred fields (significance, success_criteria_met, cost_actual, protocol_violations) with rationale; significance testing deferral explained with early-exit trigger condition. (6) Section 16 (Umbrella Relationship) expanded into a full cross-reference table mapping every section of this plan to its umbrella plan counterpart. (7) Section 17 replaced with expanded Future Work — five versioned iterations each with a concrete trigger condition from friction log evidence. (8) Document history section (this section) added. |
