# AHVS Remaining Issues Review (v5)

## Findings

1. High: hypothesis types are still mostly presentation-level distinctions, not truly different execution engines. AHVS now injects stronger type-specific guidance in `researchclaw/ahvs/executor.py`, and the prompts/tests push for more diversity, but runtime execution still flows through one generic `CodeAgent.generate(...)` path. The README is still accurate on this point: type mainly changes prompt context, package hints, and pre-flight tool checks, not the underlying executor.

2. Medium: auditability of skill usage is clearer in naming but still not evidence-backed. Renaming `skill_used` to `skill_planned` in `researchclaw/ahvs/result.py` is a good clarification, but the system still records only the plan’s declared skill, not what actually ran. That means reports and future lessons still cannot reliably distinguish intended toolchain from observed runtime behavior.

3. Medium: AHVS documentation is internally inconsistent about repo-grounded fail-closed behavior. The implementation now fails hypotheses by default when worktree creation fails unless `--allow-sandbox-only` is set, and later README sections document that correctly. But earlier README text still says non-git targets fall back to sandbox-only with a warning, which contradicts the current code and later docs.

4. Medium: the new automatic promotion path lacks strong end-to-end proof. `--apply-best` now exists and updates the baseline after applying the patch, which closes most of the prior usability gap. But the current test coverage appears focused on config wiring and failure cases; I did not find a success-path integration test that verifies patch application plus baseline update against a real git repo.

## Critical Weakness Summary

The biggest remaining product gap is still semantic over-claiming around hypothesis types. AHVS presents a fairly rich taxonomy, but in execution it remains one CodeAgent-driven path with stronger prompting rather than genuinely separate evaluators or executors.

## Improvement Scope

- Either implement real type-specific executors or simplify the hypothesis taxonomy so labels only describe behavior that actually differs at runtime.
- Add runtime-observed toolchain capture if skill provenance matters, or keep the field explicitly plan-scoped everywhere in code and docs.
- Reconcile the README so every section matches the current fail-closed default and the `--allow-sandbox-only` opt-in behavior.
- Add an end-to-end `--apply-best` success test covering `git apply`, baseline update, and the expected cycle summary inputs.

## Validation

`pytest -q tests/test_ahvs.py` passes locally with `134 passed in 20.12s`.
