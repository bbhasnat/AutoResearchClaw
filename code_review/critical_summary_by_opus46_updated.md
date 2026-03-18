# AHVS Critical Review — Claude Opus 4.6 (Updated)

**Reviewer:** Claude Opus 4.6
**Date:** 2026-03-18
**Scope:** Full code and design review of AHVS, cross-checked against GPT-5.4's independent review (`critical_summary_by_gpt54.md`).

---

## Preamble: Cross-Review Notes

GPT-5.4 and I converged on the same top-3 critical issues independently, which strengthens confidence in those findings. GPT-5.4's review is accurate on all 6 points; every line reference I verified was correct. Below I note what the cross-check revealed that my initial review missed, and what my initial review found that GPT-5.4's did not cover. The final review below is the merged, deduplicated result.

### What GPT-5.4 caught that I initially missed or under-specified

1. **The precise sandbox artifact pipeline.** I described the *symptom* (AHVS can't find `result.json` in `work_dir`) but didn't trace *why* through the CodeAgent/sandbox internals. GPT-5.4 correctly identified that CodeAgent writes files to `agent_runs/attempt_NNN/` (`code_agent.py:1237`), the sandbox copies them into a `_project/` subdirectory (`sandbox.py:274-290`) and executes there, and any runtime artifacts (like `result.json` written by the hypothesis code) stay in that `_project/` directory — they are never copied back. This is the root cause, not just a "file not found" problem.

2. **`SandboxResult.metrics` exists but is dropped.** On deeper inspection prompted by GPT-5.4's sandbox analysis, I found that the sandbox *does* parse metrics from stdout via `parse_metrics()` (`sandbox.py:366`) and stores them in `SandboxResult.metrics`. CodeAgent stores these in `SolutionNode.metrics` (`code_agent.py:1118`). But `CodeAgentResult` (the return type of `generate()`) does not carry `metrics` — only `files`, `architecture_spec`, and `best_score`. So there is a working metrics pipeline inside CodeAgent that is severed at the return boundary. This makes the fix more targeted: either propagate `SolutionNode.metrics` through `CodeAgentResult`, or copy runtime artifacts back from the sandbox.

3. **The result-capture improvement scope suggestion.** GPT-5.4's recommendation to make sandbox return "copied-back `result.json`, stdout, stderr, exit code, and parsed metrics as first-class outputs" is the right fix shape. My original review suggested a `measurement_status` field — that's necessary too, but it treats the symptom. The root fix is the pipeline wiring GPT-5.4 identified.

### What my initial review found that GPT-5.4 did not cover

1. **EvolutionStore overlay parsing is fragile** — keyword matching on prose lines (`context_loader.py:46-69`) will misclassify lessons as the store grows. Structured tags should be used instead.
2. **Friction log is auto-generated, not operator-written** — the plan intended it as human reflection; the implementation generates it from error strings.
3. **Model default inconsistency** — CLI defaults to `claude-opus-4-6`, Python API defaults to `claude-sonnet-4-6`.
4. **Skills are informational-only** — README claims "AHVS resolves the skill name to actual tool calls at runtime," but skills are just markdown text injected into CodeAgent context.
5. **All 8 hypothesis types use identical execution paths** — despite documentation implying distinct tool/strategy routing per type.
6. **The `--auto-approve` + tool pre-flight interaction** — specifically, the `input()` call happens *before* `auto_approve` is checked (line 528 vs 531), which works by accident of boolean short-circuit but is fragile and prompts unnecessarily in CI.

---

## Executive Summary

AHVS is architecturally sound — its 8-stage cycle, separation from ARC's pipeline, cross-cycle memory via EvolutionStore, and skill-library abstraction are well-designed. The code is clean, well-structured, and the module boundaries are appropriate. However, the system has a fundamental credibility gap: **it cannot currently produce trustworthy evidence that a hypothesis actually improved the target system.** The outer loop is solid; the inner loop (execute, measure, decide) is not yet reliable enough to support the autonomous validation claims in the documentation.

Both reviewers (Opus 4.6 and GPT-5.4) independently converged on this same core diagnosis.

---

## 1. Critical Findings

### 1.1 The Metric Capture Pipeline Is Broken — Sandbox Metrics Never Reach AHVS

**Severity: CRITICAL**
**Confirmed by: Both reviewers**
**Root cause location:** `code_agent.py:264-270` (CodeAgentResult drops metrics), `sandbox.py:274-330` (sandbox runs in `_project/`, no artifact copy-back), `executor.py:783-843` (AHVS fallback chain)

The full failure chain:

1. AHVS calls `CodeAgent.generate()`, which runs hypothesis code in a sandbox
2. The sandbox copies files into `workdir/_project/` (`sandbox.py:274`) and executes there (`sandbox.py:314`)
3. If the hypothesis code writes `result.json`, it lands in `_project/` — **never copied back** to the CodeAgent's work directory
4. The sandbox *does* parse metrics from stdout via `parse_metrics()` (`sandbox.py:366`) and stores them in `SandboxResult.metrics`
5. CodeAgent stores these in `SolutionNode.metrics` (`code_agent.py:1118`)
6. **But** `CodeAgentResult` does not carry `.metrics` — only `.files`, `.architecture_spec`, `.best_score` (`code_agent.py:103-111`)
7. Back in AHVS, `executor.py:824` looks for `work_dir/result.json` — it doesn't exist (it's in `_project/`)
8. Fallback at `executor.py:839` parses `architecture_spec` — which is the LLM's *planning text*, not runtime output
9. If both fail, `metric_value` silently remains `baseline_value` (set at line 783)

**Impact:** A hypothesis that failed to produce *any* measurement looks identical to one that ran and found no improvement. `HypothesisResult` will have `error=None`, `delta=0.0`, `regression_guard_passed=True`. The cycle report says "no improvement" when it should say "measurement failed."

**Fix (two-part):**
- **Pipeline wiring:** Either (a) propagate `SolutionNode.metrics` and sandbox stdout through `CodeAgentResult`, or (b) copy runtime artifacts from `_project/` back to the CodeAgent work directory after execution
- **Explicit failure tracking:** Add a `measurement_status` field to `HypothesisResult` (`measured`, `extraction_failed`, `sandbox_error`). If metric extraction fails, do not record a delta. Report and cycle_summary stages must distinguish "measured but not improved" from "could not measure"

### 1.2 Hypotheses Are Not Executed Against the Target Repository

**Severity: CRITICAL**
**Confirmed by: Both reviewers**
**Location:** `executor.py:746-822`

The problem statement includes the repo path as text (`executor.py:760-761`), but CodeAgent generates files into `tool_runs/H*/` (`executor.py:818-822`), not into the target repo. The sandbox executes CodeAgent's generated code in its own workspace. This means:

- A `prompt_rewrite` hypothesis generates a new prompt file *adjacent to* the repo, not applied to it
- A `code_change` hypothesis writes new code that is never integrated into the target codebase
- The `eval_command` declared in the baseline is never invoked — CodeAgent decides what to run
- The regression guard receives a `result.json` path that may not exist (`executor.py:851`)

AHVS does not validate hypotheses *against the repo*; it validates CodeAgent's *interpretation* of the hypothesis in a disconnected sandbox.

**Fix:** Stage 6 should: (a) create a temporary branch or worktree of the target repo, (b) apply the hypothesis change there, (c) run the repo's declared `eval_command`, (d) capture the result into the cycle directory, (e) restore to clean state. The sandbox should wrap the target repo, not replace it.

### 1.3 No Keep/Revert Mechanics — Only a Recommendation String

**Severity: CRITICAL (elevated from High after cross-review)**
**Confirmed by: Both reviewers**
**Location:** `executor.py:1070-1075`

The plan (Section 10) states: "A kept hypothesis should be committed on the cycle branch before moving on" and "A rejected hypothesis must be fully reverted before the next one begins." In practice, Stage 8 writes a plain-text recommendation like `"KEEP H1: answer_relevance improved by +0.0400 (+5.4%)"` and prints it. There is no branch creation, no commit, no revert, no patch. The README (`README_AHVS.md:533-544`) explicitly instructs manual application.

When running multiple hypotheses in a single cycle, the second hypothesis could inherit side effects from the first (once 1.2 is fixed to operate on the real repo). Without keep/revert enforcement, the cycle's central discipline guarantee is absent.

**Why elevated to Critical:** After cross-review, this is not just a missing convenience feature — it's a precondition for fix 1.2 (repo-grounded execution) to work correctly. You cannot execute multiple hypotheses against the same repo without a state-restoration mechanism. This must be built concurrently with 1.2, not after.

**Fix:** Checkpoint the repo state (branch or stash) before each hypothesis. Restore after. On keep, commit to a feature branch. On revert, reset. `cycle_summary.json` should include a diff/patch reference, not just text.

---

## 2. High-Severity Issues

### 2.1 Regression Guard Is Fail-Open When Explicitly Configured

**Confirmed by: Both reviewers**
**Location:** `executor.py:197-221`

Three paths silently return `True`:
- Guard path is `None` (line 199-200) — reasonable default
- Guard script doesn't exist at runtime despite being configured (line 201-203) — **should fail**
- Guard throws `TimeoutExpired` or `OSError` (line 219-221) — **should fail**

The plan (Section 5.2) states: "If the primary metric improves but the regression guard fails, the hypothesis is rejected." An errored or missing guard (when configured) should not be treated as passing.

**Fix:** If `regression_guard_path` is explicitly configured, treat missing-file and execution errors as guard failures. Only return `True` silently when the guard is not configured.

### 2.2 Pre-flight Skips LLM Connectivity Check

**Confirmed by: Both reviewers**
**Location:** `health.py:1-7` (docstring claims it), `health.py:214-234` (implementation omits it)

The module docstring says: "At AHVS_SETUP — minimal: baseline file + LLM connectivity." The implementation checks baseline and git cleanliness only. The first LLM call is at Stage 3 — a bad API key wastes cycle setup time and operator attention.

**Fix:** Add a lightweight LLM ping (e.g., 10-token completion, short timeout) to `run_ahvs_preflight()`.

### 2.3 `commit` Not Required in Baseline Validation

**Confirmed by: Both reviewers**
**Location:** `context_loader.py:14`, `health.py:106`

`BASELINE_REQUIRED_FIELDS` is `("primary_metric", "recorded_at", "eval_command")`. The plan (Section 5.1) treats `commit` as essential: "the exact git commit hash the baseline was measured on — enables reproduction of the baseline at any future point." Without it, you cannot verify the baseline is still valid when the repo has moved forward.

**Fix:** Add `commit` to `BASELINE_REQUIRED_FIELDS`, or at minimum emit a pre-flight warning when absent.

### 2.4 No Test Coverage for AHVS

**Confirmed by: Both reviewers**
**Location:** `tests/` — no AHVS test files exist

For a module of this complexity (1136 lines in `executor.py` alone, plus 7 supporting modules), the absence of tests means regressions are invisible. GPT-5.4 confirmed existing ARC tests pass but don't exercise AHVS paths.

**Priority test cases:**
1. Baseline validation (valid, missing fields, missing file)
2. Hypothesis parsing (well-formed, malformed, edge cases)
3. Metric extraction (`_extract_metric_from_output` — JSON, key:value, missing, ambiguous)
4. Regression guard behavior (pass, fail, missing-when-configured, timeout)
5. Checkpoint write/read/resume round-trip
6. Stage dispatcher routing (all 8 stages have handlers)
7. One end-to-end cycle with mocked LLM and sandbox

---

## 3. Medium-Severity Issues

### 3.1 `--auto-approve` Still Prompts on Failed Tool Pre-flight

**Confirmed by: Both reviewers (GPT-5.4 noted the CI awkwardness; I traced the exact logic)**
**Location:** `executor.py:523-537`

When tool pre-flight fails, AHVS calls `input()` at line 528 *before* checking `auto_approve` at line 531. In CI with piped stdin, `input()` throws `EOFError`, setting `confirm = "n"`. The condition `confirm not in ("y", "yes") and not auto_approve` evaluates to `True AND False = False`, so execution continues — but only by accident. If someone inverts the condition or adds an `or`, CI breaks silently. The `input()` call also prints the prompt unnecessarily in auto mode.

**Fix:** Check `auto_approve` first. If true, log the warning and continue without calling `input()`.

### 3.2 `--resume` Without `--run-dir` Is a Silent No-Op

**Confirmed by: Both reviewers**
**Location:** `config.py:12-14` (creates fresh timestamped dir), `cli.py:332-333` (checkpoint lookup in new empty dir)

If the operator passes `--resume` without `--run-dir`, `AHVSConfig.__post_init__` creates a new timestamped directory. Checkpoint lookup happens there, finds nothing, and the cycle starts from Stage 1 — indistinguishable from a fresh run.

**Fix:** When `--resume` is passed without `--run-dir`, either auto-detect the most recent cycle directory under `<repo>/.ahvs/cycles/`, or fail with an explicit error message.

### 3.3 Default Model Inconsistency Between CLI and Python API

**Location:** `cli.py:316` (`claude-opus-4-6`), `config.py:41` (`claude-sonnet-4-6`)

A CLI user gets Opus by default; a Python API user gets Sonnet. This produces different costs and quality for the same operation depending on entry point.

**Fix:** Align the defaults. Pick one and apply to both.

### 3.4 EvolutionStore Overlay Parsing Is Fragile

**Location:** `context_loader.py:46-69`

`_extract_rejected_approaches()` uses keyword matching (`"reject"`, `"failed"`, `"revert"`, `"rolled back"`) on prose text. `_extract_prior_lessons()` takes all lines over 20 characters. These heuristics will misclassify as the store grows — e.g., a lesson mentioning "We rejected using GPT-4 for cost reasons" would be classified as a rejected hypothesis approach.

**Fix:** Use structured tags in EvolutionStore entries (the `LessonEntry` at Stage 7 already has `category` and `severity`) instead of keyword matching on prose.

### 3.5 Friction Log Is Auto-Generated, Not Operator-Written

**Location:** `executor.py:944-954`

The plan (Section 13) defines the friction log as operator reflection with four sections: "What felt slow," "What felt unclear," "What almost got skipped," "What should be automated later." The implementation generates it from `HypothesisResult.error` fields. This captures tool errors but not the human observations the plan considers "the main evidence source for later automation work."

**Fix:** Either add an interactive prompt for operator notes at Stage 7 (skip if `--auto-approve`), or rename to `execution_errors.md` and document that operators should supplement manually.

### 3.6 Skills Are Informational, Not Executable — README Claims Otherwise

**Location:** `skills.py` (entire module), `README_AHVS.md:281`

README states: "Skills are pre-built invocation templates... AHVS resolves the skill name to actual tool calls at runtime." In practice, skills are markdown text injected into CodeAgent's prompt context. No skill resolution or enforcement occurs. The `skill_used` field in `HypothesisResult` is copied from the validation plan text, not observed at runtime. A hypothesis can claim `promptfoo_eval` while CodeAgent does something entirely different.

**Fix for now:** Correct the README to describe skills as guidance for CodeAgent, not executable templates. Long-term: implement actual skill dispatch.

### 3.7 All 8 Hypothesis Types Use Identical Execution Paths

**Location:** `executor.py:772-815`

The type mapping table (`README_AHVS.md:262-273`) suggests distinct execution strategies per type. In practice, `_run_single_hypothesis` treats all types identically: build a text problem statement, call CodeAgent, parse `result.json`. The only type-specific behaviors are `pkg_hint` (line 772-780), skill filtering (line 743), and tool pre-flight (line 516-521) — all informational.

This is acceptable for V1 but should be documented honestly. When execution is repo-grounded (fix 1.2), type-specific paths may become necessary (e.g., `prompt_rewrite` modifies a prompt file, `code_change` patches source code).

---

## 4. Deviation From the Original Plan

| Plan Requirement | Implementation Status | Severity |
|---|---|---|
| Promptfoo as primary eval engine | Not invoked — delegated to CodeAgent | High (contributes to 1.2) |
| ClawVault for local memory | Replaced by EvolutionStore | OK (reasonable simplification) |
| `regression_guard.sh` required | Optional and fail-open | High (2.1) |
| `commit` in baseline metric | Not required | High (2.3) |
| DSPy compile → Promptfoo held-out eval | No distinct path — uniform CodeAgent | Medium (3.7) |
| Keep/revert on git branches | Not implemented — string only | Critical (1.3) |
| Friction log as operator reflection | Auto-generated from errors | Medium (3.5) |
| Significance testing (deferred V2) | Not mentioned | OK (plan defers explicitly) |
| Cycle verification checks ClawVault | EvolutionStore; file-based checkpoint | OK |
| Sandbox returns artifacts + metrics | Metrics parsed but dropped at CodeAgent boundary | Critical (1.1) |

---

## 5. What Works Well

1. **Module separation.** AHVS lives cleanly inside ARC without polluting the 23-stage research pipeline. `AHVSStage`, `AHVSPromptManager`, and `AHVSStageContract` avoid namespace collisions.

2. **Cross-cycle memory.** EvolutionStore integration at Stage 2 and 7 is well-wired. Lessons flow from outcomes to future hypothesis generation. The 12-lesson cap prevents context bloat.

3. **Checkpoint/resume.** `_write_checkpoint` after every stage with `read_ahvs_checkpoint` for resume is simple and effective. Gate rollback hints are good UX.

4. **Prompt overrides.** YAML-based override system in `AHVSPromptManager` lets operators customize without touching Python.

5. **Two-pass pre-flight.** Minimal at setup, full after selection — avoids checking Docker until a `code_change` hypothesis is actually selected.

6. **Artifact discipline.** Every stage writes named artifacts to a structured directory. The complete audit trail makes cycles inspectable and comparable.

7. **Clean code quality.** Consistent error handling patterns, clear function signatures, good use of dataclasses. The codebase is readable and navigable.

---

## 6. Recommended Fix Priority

This section is ordered for the next improvement cycle. Dependencies between fixes are noted.

| Priority | Fix | Blocks | Estimated Scope |
|---|---|---|---|
| **P0-a** | Propagate sandbox metrics through `CodeAgentResult` (add `.metrics` and `.stdout` fields) | P0-c | Small — modify `CodeAgentResult` dataclass + `generate()` return |
| **P0-b** | Copy sandbox runtime artifacts (`result.json`, etc.) back from `_project/` to work dir | P0-c | Small — add copy-back step in `_run_in_sandbox` or `run_project` |
| **P0-c** | Add `measurement_status` to `HypothesisResult`; fail explicitly when metric extraction fails | — | Small — dataclass change + executor logic |
| **P0-d** | Execute hypotheses against the real target repo (worktree/branch + `eval_command`) | P1-a | Medium — new execution path in Stage 6 |
| **P1-a** | Implement keep/revert: branch per hypothesis, restore between runs | — | Medium — git operations in executor |
| **P1-b** | Make regression guard fail-closed when explicitly configured | — | Small — conditional in `_run_regression_guard` |
| **P1-c** | Add AHVS test suite (metric extraction, guard, checkpoint, one mock cycle) | — | Medium — new test file(s) |
| **P2-a** | Add LLM connectivity check to pre-flight | — | Small |
| **P2-b** | Fix `--resume` without `--run-dir` (auto-detect latest cycle) | — | Small |
| **P2-c** | Align model defaults between CLI and Python API | — | Trivial |
| **P2-d** | Fix `--auto-approve` to skip `input()` entirely on tool pre-flight | — | Small |
| **P3-a** | Structured tags in EvolutionStore for reliable lesson extraction | — | Small-Medium |
| **P3-b** | Correct README claims (skills, hypothesis type routing) | — | Small (docs only) |
| **P3-c** | Add operator friction log prompt (interactive mode only) | — | Small |

### Dependency Graph

```
P0-a ──┐
       ├──→ P0-c (measurement_status needs reliable metrics to be meaningful)
P0-b ──┘
P0-d ──────→ P1-a (repo-grounded execution requires state restoration)
```

P0-a and P0-b can be done in parallel. P0-c depends on both. P0-d is independent but P1-a must accompany or immediately follow it.

---

## 7. Bottom Line

Both reviews agree: AHVS has the right architecture and the right ambition. The 8-stage cycle, cross-cycle memory, skill library, and checkpoint system are well-designed and cleanly implemented.

The critical gap is a broken evidence path. The sandbox parses metrics but CodeAgent drops them. Runtime artifacts stay in the sandbox's `_project/` directory. Hypotheses run in isolation from the target repo. The keep/revert discipline exists only as text. These are not design flaws — they are wiring gaps in an otherwise well-structured system.

**The minimum viable fix for the next cycle is P0-a + P0-b + P0-c**: make metrics and artifacts flow from the sandbox through CodeAgent to AHVS, and make failed measurements visible. This unblocks everything downstream and is achievable with small, targeted changes to three files (`sandbox.py`, `code_agent.py`, `executor.py`).

**The second cycle should deliver P0-d + P1-a + P1-b + P1-c**: repo-grounded execution with keep/revert and tests. This transforms AHVS from a hypothesis recommender into the hypothesis validator it's designed to be.
