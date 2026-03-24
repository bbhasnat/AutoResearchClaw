# Failure Classification Rules

This reference defines how the observer classifies hypothesis execution outcomes
and the exact procedure for handling each category.

## The Three Categories

### FRAMEWORK_BUG

The AHVS framework code itself is broken — the hypothesis never got a fair evaluation.

**Indicators:**
- `ImportError`, `ModuleNotFoundError` in AutoResearchClaw code
- `FileNotFoundError` / `ENOENT` on framework paths (worktree dirs, eval_cwd)
- Truncated CodeAgent output (partial JSON, cut-off mid-function)
- `eval_command` crash that has nothing to do with hypothesis-generated code
- Missing worktree subdirectory (Bug A pattern)
- AST splice failure on valid code (Bug E pattern)
- `eval_cwd` doesn't exist when `run_eval_command` is called (Bug C pattern)

**Action:** Observer fixes the framework code, runs pytest gate, reports RERUN_NEEDED.

**Key insight:** The hypothesis code might be brilliant — we'll never know unless the
framework lets it run properly. That's why we fix and re-run.

### HYPOTHESIS_MISS

The hypothesis ran correctly from start to finish. The metric was measured. It just
didn't improve (or it regressed).

**Indicators:**
- Exit code 0
- Metric value is present and parseable
- Metric is at or below baseline
- No framework errors in the log

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
- Partial output that could be either a framework truncation or bad hypothesis code
- Error in a dependency that could be either framework or hypothesis
- Metric present but suspiciously identical to baseline (possible eval-only run when
  code changes were expected)

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
{PYTHON} -m pytest tests/ -v \
  --ignore=tests/e2e_docker_sandbox.py \
  --ignore=tests/e2e_real_llm.py \
  2>&1 | tee /tmp/pytest_before_fix.log
```

Record the number of passing and failing tests. This is the baseline.

### After the fix

```bash
cd {ARC_DIR} && \
{PYTHON} -m pytest tests/ -v \
  --ignore=tests/e2e_docker_sandbox.py \
  --ignore=tests/e2e_real_llm.py \
  2>&1 | tee /tmp/pytest_after_fix.log
```

### Gate criteria

| Criterion | Required |
|---|---|
| All previously-passing tests still pass | Yes — zero regressions allowed |
| No new test failures | Yes |
| Relevant bug regression test passes | Yes (TestBugA_*, TestBugC_*, TestBugE_*) |
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
