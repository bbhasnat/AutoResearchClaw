# AutoResearchClaw — Claude Instructions

## AHVS Memory Discipline (CRITICAL)

This repo is built on the principle that **lessons survive sessions**. The entire AHVS loop depends on memory being written in real time — not as a wrap-up step.

### When you find a bug, failure, or lesson — write it NOW:

1. **Claude auto-memory** (`~/.claude/projects/.../memory/`) — write or update a project memory file immediately
2. **AHVS friction log** (`.ahvs/cycles/<cycle_id>/friction_log.md`) — add operator notes under `## Operator Notes`
3. **AHVS lessons** (`.ahvs/evolution/lessons.jsonl`) — append a JSON line for cross-cycle lessons

### What triggers an immediate memory write:
- Any bug found (framework, config, or repo-level)
- Any hypothesis that measured at baseline despite a real code change
- Any eval/measurement failure with a diagnosed root cause
- Any "it works now but here's why it was broken" insight
- Any infrastructure constraint (missing tool, wrong path, model mismatch)

### What NOT to do:
- Do NOT defer memory writes to end of session
- Do NOT rely on conversation output as memory — it disappears
- Do NOT mark a task complete without writing its lessons to memory first

### AHVS bugs status (as of 2026-03-24):
- **Bug A** ✅ FIXED (`495c549`): `apply_files` now writes to `eval_cwd` base, not worktree root
- **Bug B** ✅ FIXED (`5a546d8` target repo): `--reparse` flag re-derives `analyst_yes_no` from `analyst_raw`. NOTE: prompt-rewrite hypotheses still need full re-inference (not eval-only).
- **Bug C** ✅ FIXED (`495c549`): `create()` and `run_eval_command()` check `eval_cwd` existence with clear errors
- **Bug D** ✅ FIXED (`db53793`): `_extract_public_api` preserves function signatures
- **Bug E** ✅ FIXED (`db53793`): AST-based `splice_functions` for partial output merging
- **Bug F** ✅ FIXED (`d362902`): Cross-cycle memory stage-name mismatch (was querying `ahvs_hypothesis_gen`, now `ahvs_execution`)
- **Bug G** ✅ FIXED (`d362902`): Enriched onboarding fields now forwarded into hypothesis-generation prompt
- **Bug H** ✅ FIXED (`d362902`): Structured JSON parsing with markdown/regex fallback
- **Bug I** ✅ FIXED (`d362902`): Skill semantics made consistently advisory (code + docs)
- **Bug J** ✅ FIXED (`d362902`): Eval-mode intelligence warns when prompt_rewrite meets --eval-only
- **Bug K** ✅ FIXED (`d362902`): Worktree subdir handling hardened with clear diagnostics

### Ready to run next AHVS cycle (all blockers resolved, 169 tests passing)

## AHVS Launch Command
```bash
export $(grep -v '^#' /home/ubuntu/vision/rnd_user_cohort/.env | xargs) && \
/home/ubuntu/miniconda3/envs/cohort_work/bin/python -m researchclaw ahvs \
  --repo /home/ubuntu/vision/rnd_user_cohort/autoqa \
  --max-hypotheses 3 --auto-approve \
  --provider openrouter --model anthropic/claude-opus-4-6 \
  --api-key-env OPENROUTER_API_KEY \
  2>&1 | tee /tmp/ahvs_poc_run.log
```
Run from `/home/ubuntu/vision/AutoResearchClaw`. Branch must be `test_avhs_190326`. Working tree must be clean.
