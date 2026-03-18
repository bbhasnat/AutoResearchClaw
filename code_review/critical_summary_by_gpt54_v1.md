# AVHS Critical Weakness And Improvement Scope Review

## Critical Findings

1. Critical: AVHS currently does not have a trustworthy metric-capture path, so Stage 6 can complete without a real measurement. In [researchclaw/ahvs/executor.py#L824](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L824) it expects `work_dir/result.json`, but CodeAgent runs files in a separate sandbox attempt directory via [researchclaw/pipeline/code_agent.py#L1236](/home/ubuntu/vision/AutoResearchClaw/researchclaw/pipeline/code_agent.py#L1236), and the sandbox only returns stdout/stderr without copying runtime artifacts back via [researchclaw/experiment/sandbox.py#L282](/home/ubuntu/vision/AutoResearchClaw/researchclaw/experiment/sandbox.py#L282). The fallback then parses `architecture_spec` as if it might contain runtime output at [researchclaw/ahvs/executor.py#L837](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L837), which is not a reliable source of measured metrics. This breaks the core promise described in [README_AHVS.md#L79](/home/ubuntu/vision/AutoResearchClaw/README_AHVS.md#L79) and [README_AHVS.md#L185](/home/ubuntu/vision/AutoResearchClaw/README_AHVS.md#L185).

2. Critical: the implementation does not enforce the keep/revert protocol it claims to provide. The docs frame AVHS as producing a "clear keep/revert recommendation" and as a disciplined hypothesis-validation loop in [README_AHVS.md#L35](/home/ubuntu/vision/AutoResearchClaw/README_AHVS.md#L35) and [README_AHVS.md#L37](/home/ubuntu/vision/AutoResearchClaw/README_AHVS.md#L37), but the code only writes a summary string in [researchclaw/ahvs/executor.py#L1070](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L1070). There is no branch creation, patch application to the target repo, revert, or final promotion step. So AVHS is currently a recommendation generator, not a closed-loop validation system.

3. High: execution is not really "repo adaptation"; it is mostly isolated code generation adjacent to the repo. The hypothesis prompt includes the repo path in [researchclaw/ahvs/executor.py#L760](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L760), but the produced files are written into `tool_runs/H*` at [researchclaw/ahvs/executor.py#L818](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L818), not applied to the target codebase. That means prompt/config/code-change hypotheses are not guaranteed to be tested against the actual repository state, which makes improvement claims easy to drift away from reality.

4. High: the safety and reproducibility checks are materially weaker than the plan and README suggest. `run_ahvs_preflight()` never checks LLM reachability despite claiming to in [researchclaw/ahvs/health.py#L4](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py#L4) and only validates baseline + git cleanliness + optional tools at [researchclaw/ahvs/health.py#L214](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py#L214). The baseline contract also omits `commit` as a required field in both [researchclaw/ahvs/health.py#L106](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py#L106) and [researchclaw/ahvs/context_loader.py#L14](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/context_loader.py#L14), even though the original plan treats it as important for reproducibility.

5. High: the regression guard is fail-open in important cases. Missing guard paths and guard execution errors are treated as pass in [researchclaw/ahvs/executor.py#L201](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L201) and [researchclaw/ahvs/executor.py#L219](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L219). For a system whose value proposition is disciplined validation, this is too permissive.

6. Medium: non-interactive usability is weaker than advertised. `--auto-approve` still prompts on failed tool preflight in [researchclaw/ahvs/executor.py#L523](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py#L523), which is awkward for CI. Also, `--resume` is misleading unless `--run-dir` is supplied, because a fresh timestamped run dir is created by default in [researchclaw/ahvs/config.py#L12](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/config.py#L12) and then checkpoint lookup happens only there in [researchclaw/cli.py#L332](/home/ubuntu/vision/AutoResearchClaw/researchclaw/cli.py#L332).

## Core Weakness

The central weakness is that AVHS does not yet reliably validate hypotheses against the real target repo and real measured outputs. The outer-loop design is good, but the inner-loop evidence path is not yet dependable enough to support the claims in the docs.

## Improvement Scope

- Make Stage 6 repo-grounded: copy or branch the target repo, apply the hypothesis there, run the repo's declared `eval_command`, and persist runtime artifacts back into the cycle dir.
- Make result capture explicit: sandbox should return copied-back `result.json`, stdout, stderr, exit code, and parsed metrics as first-class outputs.
- Implement actual keep/revert mechanics: branch per hypothesis, diff artifact, revert on fail, optional promote-on-keep.
- Make guards fail-closed for configured validations.
- Add real AVHS tests: baseline validation, resume flow, auto-approve CI flow, sandbox result capture, regression guard behavior, and one end-to-end mocked cycle.

## Validation Note

I ran `pytest -q tests/test_code_agent.py tests/test_rc_cli.py tests/test_rc_health.py tests/test_rc_runner.py` and those passed, but I did not find dedicated AVHS tests under `tests/`, so the new package looks largely unprotected by automated coverage right now.
