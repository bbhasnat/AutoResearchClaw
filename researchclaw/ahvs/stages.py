"""AHVS 8-stage cycle state machine.

Defines the stage sequence, gate stages, and rollback rules for the
AHVS hypothesis-validation cycle.

Reuses StageStatus, TransitionEvent, TransitionOutcome, and advance()
from researchclaw.pipeline.stages — they are stage-type-agnostic.
"""

from __future__ import annotations

from enum import IntEnum

# Re-export ARC's transition primitives for AHVS consumers —
# they are agnostic of the Stage type (operate on enum int values).
from researchclaw.pipeline.stages import (  # noqa: F401
    StageStatus,
    TransitionEvent,
    TransitionOutcome,
    advance,
)


class AHVSStage(IntEnum):
    """8-stage AHVS hypothesis-validation cycle."""

    AHVS_SETUP           = 1  # Pre-flight, baseline validation, cycle dir
    AHVS_CONTEXT_LOAD    = 2  # EvolutionStore overlay + baseline → context_bundle.json
    AHVS_HYPOTHESIS_GEN  = 3  # Typed hypothesis generation (1–5)
    AHVS_HUMAN_SELECTION = 4  # GATE: human selects hypotheses to run
    AHVS_VALIDATION_PLAN = 5  # Per-hypothesis implementation spec + eval method
    AHVS_EXECUTION       = 6  # CodeAgent executes each selected hypothesis
    AHVS_REPORT_MEMORY   = 7  # LLM report + EvolutionStore lesson archival
    AHVS_CYCLE_VERIFY    = 8  # Contract validation of all artifacts


AHVS_STAGE_SEQUENCE: tuple[AHVSStage, ...] = tuple(AHVSStage)

AHVS_NEXT_STAGE: dict[AHVSStage, AHVSStage | None] = {
    stage: AHVS_STAGE_SEQUENCE[idx + 1] if idx + 1 < len(AHVS_STAGE_SEQUENCE) else None
    for idx, stage in enumerate(AHVS_STAGE_SEQUENCE)
}

AHVS_GATE_STAGES: frozenset[AHVSStage] = frozenset({AHVSStage.AHVS_HUMAN_SELECTION})

AHVS_GATE_ROLLBACK: dict[AHVSStage, AHVSStage] = {
    AHVSStage.AHVS_HUMAN_SELECTION: AHVSStage.AHVS_HYPOTHESIS_GEN,
}


def ahvs_gate_required(stage: AHVSStage) -> bool:
    """Return True if this stage requires human approval."""
    return stage in AHVS_GATE_STAGES


def ahvs_default_rollback(stage: AHVSStage) -> AHVSStage:
    """Return the rollback target for a rejected gate, or the stage itself."""
    return AHVS_GATE_ROLLBACK.get(stage, stage)
