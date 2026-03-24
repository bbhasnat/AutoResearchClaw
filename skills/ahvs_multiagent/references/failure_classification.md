# Failure Classification Rules

This reference defines how the observer classifies hypothesis execution outcomes
and the exact procedure for handling each category.

## Framework Protections (know these before classifying)

The AHVS framework has several built-in protections that fire automatically
during hypothesis execution. These are **features, not bugs** — do not try
to "fix" them or classify them as FRAMEWORK_BUG.

### Forbidden file filter

The framework blocks CodeAgent from modifying eval-harness entry points.
When you see `[AHVS] blocked N forbidden file(s)` in the logs, this is
intentional protection working correctly.

| File | Policy | Why |
|---|---|---|
| `run_eval.py` | Hard-blocked | Eval entry point — modifying it breaks the pipeline |
| `evaluation.py` | Hard-blocked | Eval infrastructure |
| `test_*.py`, `*_test.py` | Hard-blocked | Test files — never part of eval |
| `__init__.py` | Warn-only (applied) | May be legitimate, logged for review |
| `main.py` | Warn-only (applied) | May be legitimate, logged for review |

If CodeAgent's only meaningful change was in a blocked file, the hypothesis
will produce zero valid files and score `extraction_failed`. This is a
**HYPOTHESIS_MISS** — the hypothesis strategy was incompatible with the
framework's safety constraints.

### Pre-eval import sanity check

After applying CodeAgent's files to the worktree, the framework verifies
the eval module can still import. When you see `pre-eval import check FAILED`
in the logs, it means CodeAgent broke the module structure (circular imports,
missing dependencies, syntax errors in spliced code).

This is a **HYPOTHESIS_MISS** — CodeAgent produced code that broke the
target repo's import chain. Do not classify as FRAMEWORK_BUG.

### Authoritative eval policy

When `eval_command` is configured, it is the **only trusted measurement
source**. Sandbox self-reports (result.json written by CodeAgent, best_metrics,
best_stdout) are unconditionally skipped. This prevents fabricated metrics.

When you see `extraction_failed` with a configured `eval_command`, it means
the real eval didn't produce a parseable metric. Do not look for the metric
in sandbox artifacts — they were intentionally skipped.

### Stale worktree cleanup

The framework automatically removes stale worktrees from previous runs
before creating new ones. This is no longer a failure mode.

---

## The Three Categories

### FRAMEWORK_BUG

A genuine bug in the AHVS framework code that prevented the hypothesis
from getting a fair evaluation.

**Indicators — these are real framework issues:**
- `ImportError` or `ModuleNotFoundError` in `researchclaw/` code (not target repo code)
- Worktree creation itself fails (not just the import check after file apply)
- `EvolutionStore` or `ContextLoader` crashes during Stage 2 or 7
- LLM client connection failure (network error, API timeout) in AHVS orchestration
- Checkpoint write/read corruption preventing stage resume
- AST splice produces invalid Python on valid input (the splicing logic itself is buggy)

**NOT a FRAMEWORK_BUG (common misclassifications):**
- `ImportError` in the target repo after CodeAgent changes → HYPOTHESIS_MISS
- Files blocked by forbidden file filter → HYPOTHESIS_MISS (intentional protection)
- Pre-eval import check failure → HYPOTHESIS_MISS (CodeAgent broke imports)
- `extraction_failed` when eval_command is configured → HYPOTHESIS_MISS (eval didn't produce metric)
- eval_command crashes after CodeAgent rewrote a core module → HYPOTHESIS_MISS

**Action:** Observer fixes the framework code, runs pytest gate, reports RERUN_NEEDED.

**Key insight:** Only classify as FRAMEWORK_BUG when the issue is in `researchclaw/`
code, not in the hypothesis-generated code or the target repository.

### HYPOTHESIS_MISS

The hypothesis was given a fair chance but didn't improve the metric. This
includes cases where CodeAgent's code was incompatible with the eval pipeline.

**Indicators:**
- Metric measured but at or below baseline
- Metric regressed (negative delta)
- `extraction_failed` because CodeAgent broke imports (pre-eval check failed)
- `extraction_failed` because eval_command crashed on hypothesis-generated code
- All CodeAgent files were blocked by forbidden file filter (bad hypothesis strategy)
- `prompt_rewrite` hypothesis with `--eval-only` eval_command (structurally unmeasurable)

**Action:** Record the lesson. Report PASS. Move on.

**Key insight:** This is expected and valuable. Failed hypotheses teach the next cycle
what NOT to try. The observer must NOT:
- Lower the baseline to make the hypothesis look successful
- Modify eval thresholds
- Reclassify it as FRAMEWORK_BUG to trigger a re-run
- Edit the hypothesis code to force a pass

### AMBIGUOUS

The logs don't make it clear whether the issue is framework or hypothesis.

**Indicators:**
- Error in a shared dependency that could be either framework or hypothesis
- Worktree exists but eval produces unexpected output format (parsing issue?)
- Metric present but suspiciously identical to baseline with code_change hypothesis

**Action:** Escalate to the team lead with:
1. The specific log lines that are ambiguous
2. Your best guess (FRAMEWORK_BUG or HYPOTHESIS_MISS)
3. What additional information would resolve the ambiguity

The lead makes the final call.

## Pytest Gate Procedure

Every framework fix by the observer must pass through this gate. No exceptions.

### Before the fix

```bash
cd {ARC_DIR} && \
{PYTHON} -m pytest tests/test_ahvs.py -v \
  2>&1 | tee /tmp/pytest_before_fix.log
```

Record the number of passing tests (currently 209). This is the baseline.

### After the fix

```bash
cd {ARC_DIR} && \
{PYTHON} -m pytest tests/test_ahvs.py -v \
  2>&1 | tee /tmp/pytest_after_fix.log
```

### Gate criteria

| Criterion | Required |
|---|---|
| All previously-passing tests still pass | Yes — zero regressions allowed |
| No new test failures | Yes |
| Full AHVS test suite passes (209 tests) | Yes |
| New test added for the specific fix | Recommended but not blocking |

### If the gate fails

1. **Revert** the fix immediately
2. **Save** both log files
3. **Escalate** to the team lead with both logs and an explanation of what went wrong
4. **Do NOT** retry the fix without lead approval

## Memory Write Requirements

Every bug fix and every lesson must be written to memory **immediately** — not at
end of session, not in batch, not "later."

### For FRAMEWORK_BUG fixes, write all three:

1. **Friction log**: `.ahvs/cycles/<cycle_id>/friction_log.md`
   ```markdown
   ## Operator Notes

   ### {timestamp} — {bug description}
   - Classification: FRAMEWORK_BUG
   - Root cause: {explanation}
   - Fix: {what was changed}
   - Tests: {pass count before} → {pass count after}
   - Hypothesis affected: {H_ID}
   ```

2. **Lessons JSONL**: `.ahvs/evolution/lessons.jsonl`
   ```json
   {"type": "framework_bug", "description": "...", "fix": "...", "file": "...", "timestamp": "..."}
   ```

3. **Claude memory**: `~/.claude/projects/-home-ubuntu-vision-AutoResearchClaw/memory/`
   Write a new memory file with frontmatter and update MEMORY.md index.

### For HYPOTHESIS_MISS, write:

1. **Lessons JSONL** only:
   ```json
   {"type": "hypothesis_miss", "hypothesis_id": "H1", "metric": 0.74, "baseline": 0.75, "description": "...", "timestamp": "..."}
   ```

This data feeds the next cycle's context loader (Stage 2), preventing repeated dead ends.
