# AutoResearchClaw — Claude Instructions

## AHVS Memory Discipline (CRITICAL)

This repo is built on the principle that **lessons survive sessions**. The entire AHVS loop depends on memory being written in real time — not as a wrap-up step.

### When you find a bug, failure, or lesson — write it NOW:

1. **AHVS memory** (`<target_repo>/.ahvs/memory/`) — write or update a memory file in the target repo immediately
2. **AHVS friction log** (`<target_repo>/.ahvs/cycles/<cycle_id>/friction_log.md`) — add operator notes under `## Operator Notes`
3. **AHVS lessons** (`<target_repo>/.ahvs/evolution/lessons.jsonl`) — append a JSON line for cross-cycle lessons

All AHVS project-specific memory lives in the **target repo**, not in Claude's machine-local memory or the AHVS framework repo. This ensures memory is portable across machines and stays with the project it describes.

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

## AHVS Launch Command
```bash
export $(grep -v '^#' /home/ubuntu/vision/rnd_user_cohort/.env | xargs) && \
/home/ubuntu/miniconda3/envs/cohort_work/bin/python -m researchclaw ahvs \
  --repo /home/ubuntu/vision/rnd_user_cohort/autoqa \
  --max-hypotheses 3 \
  --provider openrouter --model anthropic/claude-opus-4-6 \
  --api-key-env OPENROUTER_API_KEY \
  2>&1 | tee /tmp/ahvs_poc_run.log
```
Run from `/home/ubuntu/vision/AutoResearchClaw`. Branch must be `test_avhs_190326`. Working tree must be clean.
