"""AHVSConfig — configuration for a single AHVS hypothesis-validation cycle."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _default_run_dir(repo_path: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return repo_path / ".ahvs" / "cycles" / ts


@dataclass
class AHVSConfig:
    """Full configuration for one AHVS cycle."""

    # ── Target ────────────────────────────────────────────────────────────
    repo_path: Path
    question: str

    # ── Cycle settings ────────────────────────────────────────────────────
    run_dir: Path = field(default=None)  # type: ignore[assignment]
    max_hypotheses: int = 3  # soft default; hard max enforced at 5

    # ── Guards ────────────────────────────────────────────────────────────
    regression_guard_path: Path | None = None

    # ── Skill system ──────────────────────────────────────────────────────
    skill_registry_path: Path | None = None  # custom skills YAML

    # ── Prompts ───────────────────────────────────────────────────────────
    prompts_override_path: Path | None = None  # override default AHVS prompts

    # ── LLM settings ─────────────────────────────────────────────────────
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "claude-opus-4-6"
    llm_api_key_env: str = "ANTHROPIC_API_KEY"

    def __post_init__(self) -> None:
        self.repo_path = Path(self.repo_path).resolve()
        if self.run_dir is None:
            self.run_dir = _default_run_dir(self.repo_path)
        else:
            self.run_dir = Path(self.run_dir).resolve()
        if not self.llm_api_key:
            self.llm_api_key = os.environ.get(self.llm_api_key_env, "")
        if self.max_hypotheses > 5:
            raise ValueError("max_hypotheses cannot exceed 5 (AHVS hard cap)")
        if self.max_hypotheses < 1:
            raise ValueError("max_hypotheses must be at least 1")

    # ── Derived paths ─────────────────────────────────────────────────────

    @property
    def baseline_path(self) -> Path:
        return self.repo_path / ".ahvs" / "baseline_metric.json"

    @property
    def evolution_dir(self) -> Path:
        return self.repo_path / ".ahvs" / "evolution"

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "AHVSConfig":
        return cls(
            repo_path=Path(args.repo),
            question=args.question,
            run_dir=Path(args.run_dir) if getattr(args, "run_dir", None) else None,
            max_hypotheses=getattr(args, "max_hypotheses", 3),
            regression_guard_path=(
                Path(args.regression_guard)
                if getattr(args, "regression_guard", None)
                else None
            ),
            skill_registry_path=(
                Path(args.skill_registry)
                if getattr(args, "skill_registry", None)
                else None
            ),
            prompts_override_path=(
                Path(args.prompts)
                if getattr(args, "prompts", None)
                else None
            ),
            llm_model=getattr(args, "llm_model", "claude-sonnet-4-6"),
            llm_api_key_env=getattr(args, "llm_api_key_env", "ANTHROPIC_API_KEY"),
        )
