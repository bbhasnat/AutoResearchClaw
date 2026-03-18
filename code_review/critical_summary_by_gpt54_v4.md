# AHVS Fresh Review (latest)

## Findings

1. Critical: AHVS still fails open when repo-grounded execution is unavailable. Stage 1 only warns when the target is not a git repo in `researchclaw/ahvs/health.py`, while Stage 6 catches any worktree-creation failure and silently falls back to sandbox-only execution in `researchclaw/ahvs/executor.py`. That conflicts with the core repo-grounded contract described in `README_AHVS.md`. In practice, AHVS can still end with a keep recommendation even though no repo-adapted experiment actually ran. This is the biggest remaining integrity weakness.

2. High: the hypothesis-type system is still much richer in presentation than in execution. AHVS advertises distinct tool requirements by type in `researchclaw/ahvs/health.py`, but the README now explicitly notes that all types share the same execution path. In code, the type mostly changes injected skill context and `pkg_hint`. So `prompt_rewrite`, `dspy_optimize`, `architecture_change`, and `multi_llm_judge` are still largely prompt variations around one generic CodeAgent path, not truly different execution engines.

3. High: AHVS still stops short of a closed-loop "validated promotion" workflow. The implementation now keeps the best worktree and patch, but the operator must still manually apply the change and manually update the baseline, as documented in `README_AHVS.md`. That is honest in the docs, but it remains the biggest usability gap after a successful cycle: the system validates, then hands the most failure-prone step back to the user.

4. Medium: auditability around skill usage is still weak. `skill_used` is copied from the plan and persisted, while the README explicitly says it is not a runtime observation. That means reports and future lessons can look more precise than the underlying evidence really is.

## Critical Weakness Summary

The main weakness is now experiment-validity fail-open behavior. AHVS has improved a lot, but it can still produce a confident cycle outcome after silently dropping out of the repo-grounded execution mode that gives the system its core value.

## Improvement Scope

- Make repo-grounded execution fail-closed by default: if the target is not a git repo, or a worktree cannot be created, fail the cycle instead of downgrading to sandbox-only.
- If sandbox-only mode is worth keeping, require an explicit opt-in such as `--allow-sandbox-only`, and stamp the cycle summary as non-comparable to true repo-grounded runs.
- Either implement real type-specific executors or simplify the hypothesis taxonomy so the labels match what actually differs at runtime.
- Add an optional promotion path such as `--apply-best` or `--promote-best`, plus a guided baseline update step, so successful cycles can become closed-loop.
- Rename or restructure `skill_used` so it clearly distinguishes "planned skill" from "observed runtime toolchain."

## Validation

`pytest -q tests/test_ahvs.py` passes locally with `110 passed in 19.78s`. Coverage is clearly improving, but I did not find an end-to-end test for the "non-git repo or worktree failure -> sandbox-only fallback -> cycle still recommends keep" path; the current non-git coverage appears limited to the low-level worktree unit.
