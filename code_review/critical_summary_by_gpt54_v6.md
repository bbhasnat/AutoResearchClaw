# AHVS Remaining Issues Review (v6)

## Findings

1. High: the hypothesis taxonomy still overstates runtime differentiation. AHVS now documents this more honestly, and type-specific execution strategies do shape CodeAgent's instructions. But all hypothesis types still execute through the same `CodeAgent.generate(...)` path in `researchclaw/ahvs/executor.py`. So the taxonomy remains primarily an instruction-layer distinction, not a true executor-layer distinction.

2. Medium: skill provenance is still plan-scoped rather than runtime-observed. Renaming the field to `skill_planned` improved clarity, and the README now matches that naming. But AHVS still does not record what skill or toolchain was actually exercised at runtime, so reports and lessons cannot distinguish declared intent from observed execution behaviour.

## Critical Weakness Summary

The main remaining weakness is semantic precision. AHVS is now better documented, but it still presents richer execution semantics than it actually enforces at runtime, both for hypothesis types and for skill provenance.

## Improvement Scope

- Either implement genuinely distinct type-specific executors, or simplify the type system so each label corresponds only to behavior that is actually enforced by code.
- Add runtime-observed provenance fields if skill/toolchain traceability matters, or keep plan-scoped metadata clearly isolated from any downstream interpretation that implies observation.
- Add tests for any new executor split or runtime provenance capture so future changes do not regress back to prompt-only distinctions.

## Validation

`pytest -q tests/test_ahvs.py` passes locally with `135 passed in 19.89s`.
