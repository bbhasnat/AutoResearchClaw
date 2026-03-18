# AVHS Critical Weakness And Improvement Scope Review V3

## Findings

1. Critical: AHVS still has a path-safety hole before and during repo application. It writes CodeAgent files into `tool_runs/<H>/` with no path validation at [researchclaw/ahvs/executor.py#L894](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L894), so `../x.py` or `/tmp/x.py` can escape immediately. The newer worktree validator is also still flawed because it uses string-prefix containment at [researchclaw/ahvs/worktree.py#L93](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/worktree.py#L93): `/tmp/wt2/file` incorrectly passes as being inside `/tmp/wt`. I verified that prefix behavior directly. This remains the most serious integrity issue.

2. High: the "always run LLM preflight" fix introduced a Stage 4 regression. `_execute_human_selection()` calls `run_ahvs_preflight()` without passing LLM credentials at [researchclaw/ahvs/executor.py#L523](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L523), while `run_ahvs_preflight()` now always appends `check_llm_connectivity(...)` at [researchclaw/ahvs/health.py#L321](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py#L321). That means secondary preflight manufactures an LLM failure every time hypothesis selection runs, even after setup already proved connectivity. In practice this creates misleading warnings and can block interactive runs.

3. High: dirty target repos are still only warned on, even though AHVS evaluates a detached worktree created at committed `HEAD`. [researchclaw/ahvs/health.py#L192](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py#L192) only warns when the repo has uncommitted changes, but [researchclaw/ahvs/worktree.py#L42](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/worktree.py#L42) creates the hypothesis worktree from `HEAD`, not from the user's dirty working tree. So AHVS can silently measure against an older committed snapshot while the operator thinks it is validating the current repo state. That is a real reproducibility and usability problem.

4. High: invalid measurements are still poisoning long-term memory as if they were genuine rejected approaches. Reporting correctly tags `measurement_status="extraction_failed"` at [researchclaw/ahvs/executor.py#L1046](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L1046), but lesson archival still sends every non-improved, non-error result into EvolutionStore as "Rejected approach" at [researchclaw/ahvs/executor.py#L1153](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L1153). So infrastructure failures can teach AHVS to avoid ideas that were never actually tested successfully.

## Critical Weakness Summary

The main weakness now is operational integrity around execution artifacts and experiment validity. AHVS is substantially stronger than earlier versions, but it still mixes "LLM-produced file paths," "repo snapshot correctness," and "measurement validity" in ways that can corrupt outputs or teach the system the wrong lessons.

## Improvement Scope

- Add one shared safe-path utility for both `tool_runs` and worktree writes, and validate via path ancestry (`dest.is_relative_to(root)` or `root in dest.parents`), not string prefix.
- Split preflight into `setup_preflight` and `tool_only_preflight`, or pass the already-known LLM params into the Stage 4 call so selection does not invent a connectivity failure.
- Upgrade dirty-repo handling from warning to hard fail by default, or explicitly snapshot the dirty tree so baseline and execution use the same code state.
- Treat `extraction_failed` as an infrastructure lesson, not a rejected hypothesis, when writing EvolutionStore entries.

## Validation Note

`pytest -q tests/test_ahvs.py` passes with `72 passed in 19.60s`. The test coverage is clearly improving, but it still does not appear to cover the unsanitized `tool_runs` write path, the string-prefix containment bug, or the Stage 4 secondary-preflight regression.
