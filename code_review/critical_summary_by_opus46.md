# AHVS Critical Review — Claude Opus 4.6

**Reviewer:** Claude Opus 4.6
**Date:** 2026-03-18
**Scope:** Full code and design review of AHVS (Adaptive Hypothesis Validation System) as implemented in `researchclaw/ahvs/`, the original plan in `avhs_idea/AHVS_LLM_manual_plan.md`, and the public-facing `README_AHVS.md`.

---

## Executive Summary

AHVS is architecturally sound — its 8-stage cycle, separation from ARC's pipeline, cross-cycle memory via EvolutionStore, and skill-library abstraction are well-designed. The code is clean, well-structured, and the module boundaries are appropriate. However, the system has a fundamental credibility gap: it cannot currently produce trustworthy evidence that a hypothesis actually improved the target system. The outer loop is solid; the inner loop (execute → measure → decide) is not yet reliable enough to support the autonomous validation claims in the documentation.

---

## 1. Critical Findings

### 1.1 The Metric Capture Path Is Unreliable — Stage 6 Can "Succeed" Without a Real Measurement

**Severity: Critical**
**Location:** `executor.py:783-843`

When CodeAgent finishes, AHVS looks for `result.json` in the work directory (`executor.py:824-836`). If that file doesn't exist, it falls back to parsing `agent_result.architecture_spec` (`executor.py:839`), which is CodeAgent's *planning output*, not necessarily runtime output. If neither extraction succeeds, `metric_value` silently remains equal to `baseline_value` (set at line 783), meaning the hypothesis reports zero delta — no error, no warning in the result object, just a quiet "no improvement."

This is the most dangerous failure mode in the system: a hypothesis that failed to produce *any* measurement looks identical in the output to one that ran correctly and found no improvement. The `HypothesisResult` will have `error=None`, `delta=0.0`, and `regression_guard_passed=True` (since the guard gets a nonexistent `result.json`). The cycle report will say "no improvement" when it should say "measurement failed."

**Fix:** Introduce an explicit `measurement_status` field in `HypothesisResult` (e.g., `measured`, `extraction_failed`, `sandbox_error`). If metric extraction fails, mark it as such and *do not* record a delta. The report and cycle_summary stages should distinguish "measured but not improved" from "could not measure."

### 1.2 CodeAgent Runs in Isolation From the Target Repository

**Severity: Critical**
**Location:** `executor.py:746-822`

The problem statement passed to CodeAgent includes the repo path as a text string (`executor.py:760-761`), but CodeAgent generates files into `tool_runs/H*/` (`executor.py:818-822`), not into the target repo. The sandbox executes CodeAgent's generated code in its own workspace. This means:

- A `prompt_rewrite` hypothesis generates a new prompt file *adjacent to* the repo, not applied to it
- A `code_change` hypothesis writes new code that is never integrated into the target codebase
- The `eval_command` declared in the baseline is never invoked — instead, CodeAgent decides what to run

The result is that AHVS does not validate hypotheses *against the repo*; it validates CodeAgent's *interpretation* of the hypothesis in a disconnected sandbox. This is a category error for a system whose value proposition is "disciplined hypothesis validation on a target repository."

**Fix:** Stage 6 should: (a) create a temporary branch or worktree of the target repo, (b) apply the hypothesis change *there*, (c) run the repo's declared `eval_command`, (d) capture the result, (e) clean up. The sandbox should wrap the target repo, not replace it.

### 1.3 No Keep/Revert Mechanics — Only a Recommendation String

**Severity: High**
**Location:** `executor.py:1070-1075`

The README and original plan both emphasize keep/revert discipline as a core principle. The plan (Section 10) states: "A kept hypothesis should be committed on the cycle branch before moving on" and "A rejected hypothesis must be fully reverted before the next one begins." In practice, Stage 8 writes a plain-text recommendation string like `"KEEP H1: answer_relevance improved by +0.0400 (+5.4%)"` to `cycle_summary.json` and prints it. There is no branch creation, no commit, no revert, no patch. The "Keeping a successful hypothesis" section of the README (`README_AHVS.md:533-544`) explicitly instructs the user to apply changes manually.

This means AHVS is a recommendation generator, not a closed-loop validation system. The cycle does not enforce that hypotheses start from a clean state, and it cannot guarantee that a "kept" change is actually applied or that a "reverted" change is actually undone. When running multiple hypotheses in a single cycle, the second hypothesis could inherit side effects from the first.

**Fix:** At minimum, checkpoint the repo state (branch or stash) before each hypothesis and restore it after. For full discipline, create a feature branch per hypothesis, commit on success, and reset on failure. The `cycle_summary.json` should include a diff or patch, not just a text recommendation.

---

## 2. High-Severity Issues

### 2.1 Regression Guard Is Fail-Open

**Location:** `executor.py:197-221`

Three paths silently return `True` (passed):
- Guard path is `None` (line 199-200) — reasonable default
- Guard script doesn't exist at runtime (line 201-203) — should fail if explicitly configured
- Guard throws `TimeoutExpired` or `OSError` (line 219-221) — treated as passed

The last two are fail-open behaviors for a safety mechanism. If the operator explicitly passes `--regression-guard ./guard.sh` and that script is missing or crashes, AHVS should surface this as a failed check, not silently proceed. The plan (Section 5.2) states: "If the primary metric improves but the regression guard fails, the hypothesis is rejected." An errored guard should not be treated as a passing guard.

**Fix:** If `regression_guard_path` is explicitly configured, treat missing file and execution errors as guard failures. Only return `True` silently when the guard is not configured at all.

### 2.2 Pre-flight Skips LLM Connectivity Check

**Location:** `health.py:1-7, 214-234`

The module docstring says: "1. At AHVS_SETUP — minimal: baseline file + LLM connectivity." In practice, `run_ahvs_preflight()` checks baseline file and git cleanliness — no LLM connectivity test. The first LLM call happens at Stage 3 (hypothesis generation). If the API key is wrong or the model is unreachable, the cycle fails after the operator has already committed to a cycle directory and loaded context. For a system that makes 3+ LLM calls per cycle, testing connectivity at pre-flight is basic hygiene.

**Fix:** Add a lightweight LLM ping (e.g., a 10-token completion with a short timeout) to `run_ahvs_preflight()`.

### 2.3 `commit` Not Required in Baseline Validation

**Location:** `context_loader.py:14`, `health.py:106`

`BASELINE_REQUIRED_FIELDS` is `("primary_metric", "recorded_at", "eval_command")` — `commit` is absent. The plan (Section 5.1) treats `commit` as essential for reproducibility: "the exact git commit hash the baseline was measured on — enables reproduction of the baseline at any future point." Without it, you cannot verify that the baseline is still valid when the repo has moved forward. The README lists it as optional, but the plan lists it as required. The implementation follows the README, which weakens the reproducibility guarantee.

**Fix:** Add `commit` to `BASELINE_REQUIRED_FIELDS`, or at minimum emit a pre-flight warning if it's absent.

### 2.4 Multiple Hypotheses Run Against the Same (Potentially Dirty) State

**Location:** `executor.py:882-960` (Stage 6 loop)

The plan (Section 10, Rule 5) states: "No hypothesis may inherit accidental repo changes from a previous one." The implementation runs hypotheses in sequence, each writing to its own `tool_runs/H*/` subdirectory, but since CodeAgent executes in isolation (see 1.2 above), the risk is currently masked. However, if the execution is later fixed to operate on the actual target repo (as it should be), the lack of state restoration between hypotheses will become a live bug.

Even in the current isolated mode, CodeAgent instances share the same LLM client configuration and sandbox factory. If a hypothesis modifies any shared state (unlikely but not prevented), subsequent hypotheses are affected.

**Fix:** Before each hypothesis execution, verify (or enforce) that the target repo matches its expected state. After execution, restore.

---

## 3. Medium-Severity Issues

### 3.1 `--auto-approve` Still Prompts on Tool Pre-flight Failure

**Location:** `executor.py:523-537`

In Stage 4, when selected hypothesis types fail tool pre-flight, AHVS prints a warning and asks `Continue anyway? (y/N)`. The `auto_approve` flag is checked *after* the user's input response (line 531: `if confirm not in ("y", "yes") and not auto_approve`), meaning in non-interactive mode (piped stdin, CI), `input()` will raise `EOFError`, `confirm` becomes `"n"`, and because the condition checks `confirm` first, `auto_approve` saves it — but only by accident of operator precedence. The logic is confusing and fragile. If someone changes the condition order, CI breaks silently.

**Fix:** Check `auto_approve` first. If true, log the warning and continue without prompting.

### 3.2 Default Model Inconsistency

**Location:** `cli.py:316` vs `config.py:41`

The CLI defaults to `claude-opus-4-6` (`args.model or "claude-opus-4-6"`), while `AHVSConfig` defaults to `claude-sonnet-4-6`. The Python API user gets a different model than the CLI user for the same operation. This is a minor discrepancy but will produce different costs and quality depending on entry point.

**Fix:** Align the defaults. Pick one.

### 3.3 Friction Log Is Auto-Generated, Not Operator-Written

**Location:** `executor.py:944-954`

The plan (Section 13) defines the friction log as an operator-written reflection with four sections: "What felt slow," "What felt unclear," "What almost got skipped," "What should be automated later." The implementation auto-generates the friction log from `HypothesisResult.error` fields. This captures tool errors but not the human observations that the plan considers the "main evidence source for later automation work."

This isn't a bug — it's a design decision that weakens the feedback signal. The auto-generated log is better than nothing, but it misses the plan's intent.

**Fix:** Either add an interactive prompt for operator notes at Stage 7 (skip if `--auto-approve`), or rename the generated file to `execution_errors.md` and note in docs that the operator should supplement it manually.

### 3.4 EvolutionStore Overlay Parsing Is Fragile

**Location:** `context_loader.py:46-69`

`_extract_rejected_approaches()` relies on keyword matching (`"reject"`, `"failed"`, `"revert"`, `"rolled back"`) in the overlay text. `_extract_prior_lessons()` takes all lines over 20 characters. These heuristics will misclassify lessons as the EvolutionStore grows — a lesson like "We rejected the idea of using GPT-4 for classification" would be extracted as a "rejected approach" even if it was a context note, not a failed experiment. The minimum character length filters (15 and 20) are arbitrary magic numbers.

**Fix:** Use structured tags in EvolutionStore entries (e.g., `outcome: rejected` or `outcome: improved`) rather than parsing prose. The `LessonEntry` in Stage 7 (`executor.py:960-980`) already has `category` and `severity` — use those for extraction rather than keyword matching.

### 3.5 `--resume` Without `--run-dir` Is Effectively a No-Op

**Location:** `config.py:12`, `cli.py:332`

`AHVSConfig.__post_init__` creates a fresh timestamped directory if `run_dir` is not set. If the operator passes `--resume` without `--run-dir`, the cycle starts in a new empty directory, finds no checkpoint, and runs from Stage 1. There's no error — just a full fresh cycle despite the `--resume` flag.

**Fix:** When `--resume` is passed without `--run-dir`, either find the most recent cycle directory under `<repo>/.ahvs/cycles/`, or fail with an explicit error.

---

## 4. Structural Concerns

### 4.1 No Test Coverage

There are no test files for AHVS under `tests/`. The existing ARC tests (`test_code_agent.py`, `test_rc_cli.py`, `test_rc_health.py`, `test_rc_runner.py`) pass but do not exercise AHVS code paths. For a module of this complexity (1136 lines in executor.py alone, plus 7 supporting modules), the absence of tests means regressions are invisible.

**Priority tests needed:**
1. Baseline validation (valid, missing fields, missing file)
2. Hypothesis parsing (well-formed, malformed, edge cases)
3. Metric extraction (JSON, key:value, missing, ambiguous)
4. Regression guard behavior (pass, fail, missing, timeout)
5. Checkpoint write/read/resume round-trip
6. Stage dispatcher routing
7. One end-to-end cycle with mocked LLM and sandbox

### 4.2 Skills Are Informational, Not Executable

The skill library (`skills.py`) provides descriptions and invocation templates that are injected into CodeAgent's context as markdown text. CodeAgent reads these descriptions and may reference them, but AHVS never resolves a skill to an actual tool invocation. The `skill_used` field in `HypothesisResult` is set from the validation plan's text, not from runtime observation. This means:

- A hypothesis can claim to use `promptfoo_eval` but CodeAgent may do something entirely different
- The `applicable_types` filtering has no enforcement — it only affects what CodeAgent *sees*
- `required_tools` in `SkillSpec` is checked at pre-flight but not enforced at execution time

This is acceptable for V1 (CodeAgent needs autonomy), but the README presents skills as a concrete execution mechanism ("Skills are pre-built invocation templates... AHVS resolves the skill name to actual tool calls at runtime" — `README_AHVS.md:281`). That claim is false.

### 4.3 The 8 Hypothesis Types Are Not Differentiated at Execution Time

The hypothesis type mapping table in `README_AHVS.md:262-273` suggests that different types use different tools and execution strategies. In practice, `_run_single_hypothesis` treats all types identically: build a problem statement, call CodeAgent, try to read `result.json`. The only type-specific behavior is:

- `pkg_hint` for CodeAgent (line 772-780) — a package name suggestion
- Skill filtering by type (line 743) — what skills CodeAgent sees
- Tool pre-flight per type (line 516-521) — what tools are checked

CodeAgent must infer from the problem text how to implement a `prompt_rewrite` differently from an `architecture_change`. There's no type-specific execution path, validation logic, or output parsing. This is fine for a prototype, but the documentation implies more structure than exists.

---

## 5. Deviation From the Original Plan

| Plan Requirement | Implementation Status |
|---|---|
| Promptfoo as primary eval engine | Not invoked directly — delegated to CodeAgent |
| ClawVault for local memory | Replaced by EvolutionStore (reasonable simplification) |
| `regression_guard.sh` required | Optional and fail-open |
| `commit` in baseline metric | Not required |
| DSPy compile → Promptfoo held-out eval path | No distinct path — CodeAgent handles uniformly |
| Keep/revert on git branches | Not implemented — recommendation string only |
| Friction log as operator reflection | Auto-generated from errors |
| Significance testing (deferred V2) | Not mentioned in implementation |
| Cycle verification checks ClawVault state | EvolutionStore replaces ClawVault; checkpoint is file-based |

Some deviations are reasonable simplifications (ClawVault → EvolutionStore). Others (fail-open guard, no keep/revert mechanics, no direct eval_command invocation) weaken the system's core validation guarantee.

---

## 6. What Works Well

1. **Module separation.** AHVS lives cleanly inside ARC without polluting the 23-stage research pipeline. The `AHVSStage` enum, `AHVSPromptManager`, and `AHVSStageContract` avoid namespace collisions.

2. **Cross-cycle memory.** The EvolutionStore integration at Stage 2 and Stage 7 is well-wired. Lessons flow from cycle outcomes to future hypothesis generation prompts. The 12-lesson cap prevents context bloat.

3. **Checkpoint/resume system.** `_write_checkpoint` after every stage, with `read_ahvs_checkpoint` for resume, is a simple and effective persistence pattern. Gate rollback hints are a nice UX touch.

4. **Prompt overrides.** The YAML-based prompt override system in `AHVSPromptManager` lets operators customize hypothesis generation, validation planning, and reporting without touching Python.

5. **Pre-flight health checks.** The two-pass pre-flight (minimal at setup, full after selection) is the right pattern — you don't want to check Docker availability until a `code_change` hypothesis is actually selected.

6. **Cycle artifact discipline.** Every stage writes named artifacts to a structured directory. The complete audit trail (manifest, context bundle, hypotheses, selection, plan, results, report, summary) makes cycles inspectable and comparable.

---

## 7. Recommended Priority Order for Fixes

| Priority | Fix | Impact |
|---|---|---|
| P0 | Make metric extraction failures explicit (not silent zero-delta) | Prevents false "no improvement" reports |
| P0 | Execute hypotheses against the actual target repo (branch/worktree + eval_command) | Makes AHVS actually validate hypotheses |
| P1 | Make regression guard fail-closed when explicitly configured | Prevents silent safety bypass |
| P1 | Add test coverage (at minimum: metric extraction, guard, checkpoint, one mock cycle) | Prevents regressions |
| P1 | Implement basic keep/revert: branch per hypothesis, restore between runs | Matches the plan's core discipline |
| P2 | Add LLM connectivity check to pre-flight | Better UX, faster failure on bad credentials |
| P2 | Fix `--resume` without `--run-dir` to find the latest cycle | Prevents confusing no-op resumes |
| P2 | Align model defaults between CLI and Python API | Prevents unexpected cost/quality differences |
| P3 | Add structured tags to EvolutionStore for reliable lesson extraction | Reduces misclassification as store grows |
| P3 | Fix `--auto-approve` + tool pre-flight prompt logic | Clean CI behavior |

---

## 8. Bottom Line

AHVS has the right architecture and the right ambition. The 8-stage cycle, cross-cycle memory, skill library, and checkpoint system are all well-designed and cleanly implemented. The critical gap is in the evidence path: Stage 6 does not execute hypotheses against the real target repo, metric capture can silently fail, and the keep/revert discipline exists only as text. Fixing P0 items (metric reliability + repo-grounded execution) would transform AHVS from a hypothesis *recommender* to a hypothesis *validator* — which is the system it's designed to be.
