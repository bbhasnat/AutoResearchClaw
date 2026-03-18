# AVHS Critical Weakness And Improvement Scope Review V2

## Findings

1. Critical: generated file paths are not constrained to the worktree, so a bad or hallucinated filename can write outside the target repo. [researchclaw/ahvs/worktree.py#L55](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/worktree.py#L55) does `self.worktree_path / relpath` and writes it directly, with no normalization or containment check. In Python, `Path("/wt") / "../x"` escapes and `Path("/wt") / "/tmp/x"` becomes absolute. Because these paths come from CodeAgent output applied at [researchclaw/ahvs/executor.py#L901](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L901), this is the most serious remaining weakness.

2. High: the new Tier 0 worktree measurement and the regression guard are still miswired. Metrics can now come from `eval_command` stdout in the worktree at [researchclaw/ahvs/executor.py#L907](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L907), but the guard is always run against `tool_runs/<H>/result.json` at [researchclaw/ahvs/executor.py#L978](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L978). If a repo relies on Tier 0 and does not also emit that file, a configured fail-closed guard can reject otherwise valid hypotheses, or inspect stale/nonexistent data.

3. High: measurement failure is still treated as a successful cycle outcome instead of an invalid experiment. When extraction fails, AVHS keeps the baseline metric and marks `measurement_status="extraction_failed"` at [researchclaw/ahvs/executor.py#L961](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L961). Stage 8 then still completes and only reports a counter in `cycle_summary.json` at [researchclaw/ahvs/executor.py#L1226](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L1226). That can turn a broken evaluation loop into what looks like a legitimate "no improvement" cycle.

4. High: setup still does not reliably fail fast on missing LLM credentials. `check_llm_connectivity()` correctly fails on empty API keys at [researchclaw/ahvs/health.py#L229](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py#L229), but `run_ahvs_preflight()` only adds that check when `llm_api_key` is truthy at [researchclaw/ahvs/health.py#L313](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py#L313). So Stage 1 can pass with no key and the run fails later at hypothesis generation instead of at setup.

5. Medium: the declared tool requirements and actual runtime are still inconsistent. Preflight says `code_change`, `architecture_change`, and `multi_llm_judge` require `docker` at [researchclaw/ahvs/health.py#L27](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py#L27), but `_make_sandbox_factory()` always builds a local `ExperimentSandbox` with `python3` at [researchclaw/ahvs/executor.py#L214](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L214). That creates false environment failures and makes the skill/runtime story harder to trust.

## Critical Weakness Summary

The biggest remaining issue is not the outer-loop design anymore; it is execution integrity. AVHS is much more real than v1, but it still trusts model-produced file paths and soft-fails invalid measurements in ways that can corrupt the repo boundary or blur the difference between "measured no improvement" and "never actually measured."

## Improvement Scope

- Add strict path validation before applying generated files: reject absolute paths, `..`, symlinks escaping the root, and non-repo-relative writes.
- Synthesize a canonical measured artifact after Tier 0, then run the regression guard against that normalized result instead of `work_dir/result.json`.
- Treat `extraction_failed` as a failed hypothesis, and optionally fail the whole cycle when all selected hypotheses are unmeasured.
- Always run LLM preflight, even when the key is empty, so setup fails early and clearly.
- Align tool checks with actual runtime: either really use Docker/remote backends or stop requiring those tools for paths that only use the local sandbox.

## Validation Note

`pytest -q tests/test_ahvs.py` passed locally with `58 passed in 1.37s`. The new tests are a good improvement, but they do not appear to cover the path-escape case, the Tier 0/guard mismatch, or the "all measurements failed but cycle still succeeds" path.
