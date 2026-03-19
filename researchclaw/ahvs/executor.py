"""AHVS stage executor — 8 handler functions, one per AHVS stage.

Each handler receives (cycle_dir, config, skill_library, auto_approve)
and returns an AHVSStageResult.

Stage dispatch is performed by execute_ahvs_stage().
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from researchclaw.ahvs.config import AHVSConfig
from researchclaw.ahvs.contracts import AHVS_CONTRACTS
from researchclaw.ahvs.context_loader import load_context_bundle
from researchclaw.ahvs.health import run_ahvs_preflight
from researchclaw.ahvs.prompts import AHVSPromptManager
from researchclaw.ahvs.result import HypothesisResult, save_results
from researchclaw.ahvs.skills import SkillLibrary
from researchclaw.ahvs.stages import AHVSStage, StageStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AHVSStageResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AHVSStageResult:
    """Outcome of executing a single AHVS stage."""

    stage: AHVSStage
    status: StageStatus
    artifacts: tuple[str, ...]
    error: str | None = None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# LLM client factory
# ---------------------------------------------------------------------------


def _make_llm_client(config: AHVSConfig) -> Any:
    """Build an LLM client from AHVSConfig via the shared ARC factory.

    Routes through ``researchclaw.llm.create_llm_client()`` so that
    provider selection (Anthropic, OpenAI, ACP, etc.) is handled in one
    place.  A lightweight shim object bridges AHVSConfig fields to the
    ``RCConfig.llm`` / ``RCConfig.metaclaw_bridge`` shape expected by
    the factory.
    """
    from researchclaw.llm import create_llm_client

    shim = _ahvs_config_to_rc_shim(config)
    return create_llm_client(shim)


class _AcpShim:
    """Mimics ``AcpConfig`` for the shared LLM factory."""

    __slots__ = ("agent", "cwd", "acpx_command", "session_name", "timeout_sec")

    def __init__(self, config: AHVSConfig) -> None:
        self.agent = config.acp_agent
        self.cwd = config.acp_cwd
        self.acpx_command = config.acpx_command
        self.session_name = config.acp_session_name
        self.timeout_sec = config.acp_timeout_sec


class _LlmShim:
    """Mimics ``LlmConfig`` for the shared LLM factory."""

    __slots__ = (
        "provider", "base_url", "api_key", "api_key_env",
        "primary_model", "fallback_models", "acp",
    )

    def __init__(self, config: AHVSConfig) -> None:
        self.provider = config.llm_provider
        self.base_url = config.llm_base_url
        self.api_key = config.llm_api_key
        self.api_key_env = config.llm_api_key_env
        self.primary_model = config.llm_model
        self.fallback_models: tuple[str, ...] = ()
        self.acp = _AcpShim(config)


class _RCConfigShim:
    """Minimal shim bridging AHVSConfig to the shape ``create_llm_client`` expects."""

    __slots__ = ("llm", "metaclaw_bridge")

    def __init__(self, config: AHVSConfig) -> None:
        self.llm = _LlmShim(config)
        self.metaclaw_bridge = None  # AHVS does not use the MetaClaw proxy


def _ahvs_config_to_rc_shim(config: AHVSConfig) -> _RCConfigShim:
    """Convert an AHVSConfig into a shim compatible with ``create_llm_client``."""
    return _RCConfigShim(config)


# ---------------------------------------------------------------------------
# Type-specific execution strategies (Finding 2, v4)
# ---------------------------------------------------------------------------

_TYPE_EXECUTION_STRATEGIES: dict[str, dict[str, str]] = {
    "prompt_rewrite": {
        "system_addition": (
            "You are implementing a PROMPT REWRITE hypothesis. Focus EXCLUSIVELY on:\n"
            "- System prompt improvements (clarity, specificity, role definition)\n"
            "- Few-shot example selection and formatting\n"
            "- Instruction structure and ordering\n"
            "- Output format specifications\n"
            "DO NOT modify any code logic, algorithms, or configuration parameters.\n"
            "Only modify prompt template files, YAML prompt configs, or string literals "
            "containing prompts."
        ),
        "constraints": "Scope: prompt template files only. No algorithm or config changes.",
        "success_guidance": "Measure output quality improvement from prompt changes alone.",
    },
    "model_comparison": {
        "system_addition": (
            "You are implementing a MODEL COMPARISON hypothesis. Focus on:\n"
            "- Swapping model identifiers (e.g. gpt-4o → claude-sonnet-4-6)\n"
            "- Adjusting API call parameters for the new model\n"
            "- Ensuring output parsing is compatible with the new model's format\n"
            "Minimal code changes — primarily config/model ID swaps."
        ),
        "constraints": "Scope: model IDs and API parameters only. No algorithm redesign.",
        "success_guidance": "Compare output quality and cost across models.",
    },
    "config_change": {
        "system_addition": (
            "You are implementing a CONFIG CHANGE hypothesis. Focus on:\n"
            "- Hyperparameter tuning: temperature, top_p, top_k, max_tokens\n"
            "- Retrieval parameters: chunk_size, chunk_overlap, top_k results\n"
            "- Embedding dimensions, batch sizes, similarity thresholds\n"
            "Only modify configuration files or parameter values. No new algorithms."
        ),
        "constraints": "Scope: config files and numeric parameters only.",
        "success_guidance": "Measure metric sensitivity to parameter changes.",
    },
    "dspy_optimize": {
        "system_addition": (
            "You are implementing a DSPy OPTIMIZATION hypothesis. Focus on:\n"
            "- Creating DSPy modules (Signatures, ChainOfThought, ReAct)\n"
            "- Defining DSPy metrics for optimization\n"
            "- Using DSPy optimizers (BootstrapFewShot, MIPRO, BayesianSignatureOptimizer)\n"
            "- Compiling and evaluating optimized prompts programmatically\n"
            "This requires creating DSPy module code, not just editing prompts."
        ),
        "constraints": "Must use DSPy framework. Create proper DSPy modules.",
        "success_guidance": "Use DSPy's built-in evaluation to measure improvement.",
    },
    "code_change": {
        "system_addition": (
            "You are implementing a CODE CHANGE hypothesis. Focus on REAL algorithmic changes:\n"
            "- New or modified data processing pipelines\n"
            "- Improved retrieval strategies (BM25, hybrid search, query expansion)\n"
            "- Better ranking/reranking functions\n"
            "- Enhanced text chunking or preprocessing algorithms\n"
            "- New post-processing or answer synthesis logic\n"
            "DO NOT just change prompts or config values. Write actual code that implements "
            "a different algorithm or data flow."
        ),
        "constraints": "Must modify actual code logic, not just prompts or configs.",
        "success_guidance": "Demonstrate algorithmic improvement via metric change.",
    },
    "architecture_change": {
        "system_addition": (
            "You are implementing an ARCHITECTURE CHANGE hypothesis. Focus on structural redesign:\n"
            "- New retrieval pipeline components (re-rankers, query routers, caching layers)\n"
            "- Hybrid search architectures (combining vector + keyword retrieval)\n"
            "- Multi-stage processing pipelines\n"
            "- New modules for context compression, document filtering, or answer verification\n"
            "- Agent-based architectures with tool use\n"
            "Create NEW modules/classes, not just modify existing ones. Think about data flow "
            "and component interfaces."
        ),
        "constraints": "Must introduce new modules or restructure component boundaries.",
        "success_guidance": "Demonstrate architectural improvement via metric and design clarity.",
    },
    "multi_llm_judge": {
        "system_addition": (
            "You are implementing a MULTI-LLM JUDGE hypothesis. Focus on:\n"
            "- Multi-model consensus: query N models, aggregate answers\n"
            "- Judge-based evaluation: use one LLM to evaluate another's output\n"
            "- Debate/critique patterns: models critique each other's answers\n"
            "- Confidence-weighted selection across model outputs\n"
            "Write evaluation/judging code that coordinates multiple LLM calls."
        ),
        "constraints": "Must implement multi-model coordination, not single-model changes.",
        "success_guidance": "Measure quality improvement from multi-model approach.",
    },
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_hypotheses(text: str) -> list[dict]:
    """Parse hypotheses.md into a list of hypothesis dicts."""
    hypotheses = []
    # Split on H1, H2, ... headers
    blocks = re.split(r"^##\s+(H\d+)\s*$", text, flags=re.MULTILINE)
    # blocks: ['preamble', 'H1', 'H1 body', 'H2', 'H2 body', ...]
    it = iter(blocks)
    next(it, None)  # skip preamble
    for hyp_id, body in zip(it, it):
        hyp: dict = {"id": hyp_id.strip()}
        for field, pattern in [
            ("type", r"\*\*Type:\*\*\s*(.+)"),
            ("description", r"\*\*Description:\*\*\s*(.+)"),
            ("rationale", r"\*\*Rationale:\*\*\s*(.+)"),
            ("estimated_cost", r"\*\*Estimated Cost:\*\*\s*(.+)"),
            ("required_tools", r"\*\*Required Tools:\*\*\s*(.+)"),
        ]:
            m = re.search(pattern, body, re.IGNORECASE)
            hyp[field] = m.group(1).strip() if m else ""
        hyp["required_tools"] = [
            t.strip() for t in hyp.get("required_tools", "").split(",") if t.strip()
        ]
        hypotheses.append(hyp)
    return hypotheses


def _parse_selection(text: str) -> dict:
    """Parse selection.md → {selected: [H1, H2], rationale: str}."""
    selected: list[str] = re.findall(r"\bH\d+\b", text)
    rationale_m = re.search(r"\*\*Rationale:\*\*\s*(.+)", text, re.IGNORECASE)
    return {
        "selected": list(dict.fromkeys(selected)),  # dedup, preserve order
        "rationale": rationale_m.group(1).strip() if rationale_m else "",
    }


def _parse_validation_plan(text: str) -> list[dict]:
    """Parse validation_plan.md into per-hypothesis plan dicts."""
    plans = []
    blocks = re.split(r"^##\s+(H\d+)\s*$", text, flags=re.MULTILINE)
    it = iter(blocks)
    next(it, None)
    for hyp_id, body in zip(it, it):
        plan: dict = {"id": hyp_id.strip()}
        for field, pattern in [
            ("implementation_approach", r"\*\*Implementation Approach:\*\*\s*(.+)"),
            ("eval_method", r"\*\*Eval Method:\*\*\s*(.+)"),
            ("skill", r"\*\*Skill:\*\*\s*(.+)"),
            ("success_criterion", r"\*\*Success Criterion:\*\*\s*(.+)"),
            ("expected_artifacts", r"\*\*Expected Artifacts:\*\*\s*(.+)"),
        ]:
            m = re.search(pattern, body, re.IGNORECASE)
            plan[field] = m.group(1).strip() if m else ""
        plans.append(plan)
    return plans


def _extract_metric_from_output(raw_output: str, metric_key: str) -> float | None:
    """Try to extract a float metric value from JSON or key:value text output."""
    # Try JSON parse
    for line in reversed(raw_output.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                # Navigate dot-separated key path
                parts = metric_key.split(".")
                val: Any = data
                for p in parts:
                    if isinstance(val, dict):
                        val = val.get(p)
                    elif isinstance(val, list) and p.isdigit():
                        idx = int(p)
                        val = val[idx] if idx < len(val) else None
                    else:
                        val = None
                    if val is None:
                        break
                if isinstance(val, (int, float)):
                    return float(val)
            except (json.JSONDecodeError, IndexError, TypeError):
                pass

    # Try "metric_key: 0.82" pattern
    pattern = re.compile(
        rf"{re.escape(metric_key)}\s*[:\s]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)",
        re.IGNORECASE,
    )
    m = pattern.search(raw_output)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _run_regression_guard(guard_path: Path | None, results_path: Path) -> bool:
    """Run regression guard script. Returns True if passed or not configured."""
    if guard_path is None:
        return True
    if not guard_path.exists():
        logger.error("Regression guard not found: %s", guard_path)
        return False
    try:
        r = subprocess.run(
            [str(guard_path), str(results_path)],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if r.returncode != 0:
            logger.warning(
                "Regression guard FAILED (exit %d): %s",
                r.returncode,
                r.stderr.decode(errors="replace")[:200],
            )
            return False
        return True
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.error("Regression guard failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Sandbox factory helper
# ---------------------------------------------------------------------------


def _make_sandbox_factory(config: AHVSConfig) -> Any:
    """Return a sandbox factory callable for CodeAgent."""
    import sys
    from researchclaw.config import (
        ExperimentConfig,
        SandboxConfig,
        DockerSandboxConfig,
        SshRemoteConfig,
        ColabDriveConfig,
    )
    from researchclaw.experiment.sandbox import ExperimentSandbox

    python_path = sys.executable  # absolute path to current interpreter

    def _factory(exp_config: Any, workdir: Path) -> Any:
        return ExperimentSandbox(
            SandboxConfig(python_path=python_path),
            workdir,
        )

    return _factory


# ---------------------------------------------------------------------------
# Stage handlers
# ---------------------------------------------------------------------------


def _execute_setup(
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
    auto_approve: bool,
) -> AHVSStageResult:
    """Stage 1: Pre-flight validation and cycle directory setup."""
    cycle_dir.mkdir(parents=True, exist_ok=True)
    (cycle_dir / "tool_runs").mkdir(exist_ok=True)
    (cycle_dir / "worktrees").mkdir(exist_ok=True)

    import os as _os

    api_key = config.llm_api_key or _os.environ.get(config.llm_api_key_env, "")
    report = run_ahvs_preflight(
        baseline_path=config.baseline_path,
        repo_path=config.repo_path,
        regression_guard_path=config.regression_guard_path,
        hypothesis_types=None,  # minimal check at setup time
        llm_api_key=api_key,
        llm_model=config.llm_model,
        llm_base_url=config.llm_base_url,
        llm_provider=config.llm_provider,
        ahvs_config=config,
    )

    if report.overall == "fail":
        failures = [c.detail for c in report.checks if c.status == "fail"]
        return AHVSStageResult(
            stage=AHVSStage.AHVS_SETUP,
            status=StageStatus.FAILED,
            artifacts=(),
            error=f"Pre-flight failed: {'; '.join(failures)}",
        )

    # Write cycle manifest
    manifest = {
        "cycle_id": cycle_dir.name,
        "question": config.question,
        "repo_path": str(config.repo_path),
        "started_at": _utcnow_iso(),
        "max_hypotheses": config.max_hypotheses,
        "regression_guard": str(config.regression_guard_path) if config.regression_guard_path else None,
        "preflight_checks": [
            {"name": c.name, "status": c.status, "detail": c.detail}
            for c in report.checks
        ],
    }
    manifest_path = cycle_dir / "cycle_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return AHVSStageResult(
        stage=AHVSStage.AHVS_SETUP,
        status=StageStatus.DONE,
        artifacts=("cycle_manifest.json",),
    )


def _execute_context_load(
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
    auto_approve: bool,
) -> AHVSStageResult:
    """Stage 2: Load baseline + EvolutionStore → context_bundle.json."""
    try:
        bundle = load_context_bundle(
            repo_path=config.repo_path,
            question=config.question,
            evolution_dir=config.evolution_dir,
            baseline_path=config.baseline_path,
        )
    except (FileNotFoundError, ValueError) as exc:
        return AHVSStageResult(
            stage=AHVSStage.AHVS_CONTEXT_LOAD,
            status=StageStatus.FAILED,
            artifacts=(),
            error=str(exc),
        )

    bundle_path = cycle_dir / "context_bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    return AHVSStageResult(
        stage=AHVSStage.AHVS_CONTEXT_LOAD,
        status=StageStatus.DONE,
        artifacts=("context_bundle.json",),
    )


def _execute_hypothesis_gen(
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
    auto_approve: bool,
) -> AHVSStageResult:
    """Stage 3: Generate typed hypotheses via LLM."""
    bundle_path = cycle_dir / "context_bundle.json"
    if not bundle_path.exists():
        return AHVSStageResult(
            stage=AHVSStage.AHVS_HYPOTHESIS_GEN,
            status=StageStatus.FAILED,
            artifacts=(),
            error="context_bundle.json not found — run AHVS_CONTEXT_LOAD first",
        )

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    baseline = bundle["baseline"]

    prior_lessons_text = (
        "\n".join(f"- {l}" for l in bundle.get("prior_lessons", []))
        or "None recorded yet."
    )
    rejected_text = (
        "\n".join(f"- {r}" for r in bundle.get("rejected_approaches", []))
        or "None recorded yet."
    )
    domain_tags_text = ", ".join(bundle.get("domain_tags", ["general"]))

    pm = AHVSPromptManager(config.prompts_override_path)
    prompt = pm.for_stage(
        "ahvs_hypothesis_gen",
        question=config.question,
        metric_name=baseline["primary_metric"],
        baseline_value=str(baseline["value"]),
        eval_command=baseline.get("eval_command", ""),
        domain_tags=domain_tags_text,
        prior_lessons=prior_lessons_text,
        rejected_approaches=rejected_text,
        max_hypotheses=str(config.max_hypotheses),
    )

    try:
        llm = _make_llm_client(config)
        response = llm.chat(
            [{"role": "user", "content": prompt.user}],
            system=prompt.system,
            max_tokens=prompt.max_tokens,
        )
        raw_text = response.content
    except Exception as exc:  # noqa: BLE001
        return AHVSStageResult(
            stage=AHVSStage.AHVS_HYPOTHESIS_GEN,
            status=StageStatus.FAILED,
            artifacts=(),
            error=f"LLM call failed: {exc}",
        )

    # Validate and cap
    hypotheses = _parse_hypotheses(raw_text)
    if not hypotheses:
        return AHVSStageResult(
            stage=AHVSStage.AHVS_HYPOTHESIS_GEN,
            status=StageStatus.FAILED,
            artifacts=(),
            error="LLM did not produce any parseable hypotheses",
        )
    if len(hypotheses) > 5:
        logger.warning(
            "LLM generated %d hypotheses — truncating to 5 (hard cap)",
            len(hypotheses),
        )
        raw_text_lines = raw_text.splitlines()
        # Truncate raw_text to the first 5 H-blocks
        kept_ids = {h["id"] for h in hypotheses[:5]}
        keep = True
        out_lines: list[str] = []
        current_id = None
        for line in raw_text_lines:
            m = re.match(r"^##\s+(H\d+)\s*$", line)
            if m:
                current_id = m.group(1)
                keep = current_id in kept_ids
            if keep:
                out_lines.append(line)
        raw_text = "\n".join(out_lines)
        hypotheses = hypotheses[:5]

    hyp_path = cycle_dir / "hypotheses.md"
    hyp_path.write_text(raw_text, encoding="utf-8")

    logger.info(
        "Generated %d hypotheses: %s",
        len(hypotheses),
        [h["id"] for h in hypotheses],
    )

    return AHVSStageResult(
        stage=AHVSStage.AHVS_HYPOTHESIS_GEN,
        status=StageStatus.DONE,
        artifacts=("hypotheses.md",),
    )


def _execute_human_selection(
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
    auto_approve: bool,
) -> AHVSStageResult:
    """Stage 4 (GATE): Display hypotheses to operator; record selection.

    Supports three selection modes:

    1. **Pre-specified** (``selection.json`` already exists in ``cycle_dir``):
       Used by conversational/agent-driven callers (e.g. Claude Code) that
       collect the user's choice *before* invoking the executor.  The file
       must contain ``{"selected": ["H1", ...], "rationale": "..."}``.
       When this file is found, the gate honours it and skips all prompts.

    2. **Auto-approve** (``auto_approve=True``):
       Selects every hypothesis.  Used for CI / scripted runs.

    3. **Interactive** (default):
       Prompts the operator on stdin.
    """
    hyp_path = cycle_dir / "hypotheses.md"
    if not hyp_path.exists():
        return AHVSStageResult(
            stage=AHVSStage.AHVS_HUMAN_SELECTION,
            status=StageStatus.FAILED,
            artifacts=(),
            error="hypotheses.md not found",
        )

    hypotheses_text = hyp_path.read_text(encoding="utf-8")
    hypotheses = _parse_hypotheses(hypotheses_text)
    all_ids = [h["id"] for h in hypotheses]

    # ── Mode 1: Pre-specified selection.json ──────────────────────────
    pre_sel_path = cycle_dir / "selection.json"
    if pre_sel_path.exists():
        try:
            pre_sel = json.loads(pre_sel_path.read_text(encoding="utf-8"))
            pre_selected = [
                s.upper()
                for s in pre_sel.get("selected", [])
                if s.upper() in all_ids
            ]
        except (json.JSONDecodeError, TypeError):
            pre_selected = []

        if pre_selected:
            rationale = pre_sel.get("rationale", "caller-provided selection")
            approved_by = pre_sel.get("approved_by", "caller")
            selected = pre_selected
            print(
                f"\n[AHVS] Pre-specified selection: {', '.join(selected)} "
                f"(approved_by={approved_by})"
            )
            return _finalize_selection(
                cycle_dir, config, hypotheses, selected, rationale,
                approved_by, auto_approve,
            )

    # ── Mode 2: Auto-approve ──────────────────────────────────────────
    if auto_approve:
        selected = all_ids
        rationale = "auto-approve: all hypotheses selected"
        print(
            f"\n[AHVS] Auto-approve: selecting all {len(selected)} hypothesis/hypotheses: "
            f"{', '.join(selected)}"
        )
        return _finalize_selection(
            cycle_dir, config, hypotheses, selected, rationale,
            "auto", auto_approve,
        )

    # ── Mode 3: Interactive gate ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("AHVS HUMAN SELECTION — Cycle Gate")
    print("=" * 70)
    print(f"\nQuestion: {config.question}\n")
    print(hypotheses_text)
    print("=" * 70)
    print(f"Available hypotheses: {', '.join(all_ids)}")
    print("Enter IDs to run (e.g. 'H1 H2', 'all', or 'none' to abort):")

    try:
        raw = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        raw = "none"

    if raw.lower() == "none" or not raw:
        return AHVSStageResult(
            stage=AHVSStage.AHVS_HUMAN_SELECTION,
            status=StageStatus.FAILED,
            artifacts=(),
            error="Operator aborted cycle at hypothesis selection",
        )
    if raw.lower() == "all":
        selected = all_ids
    else:
        selected = [s.strip() for s in re.findall(r"H\d+", raw, re.IGNORECASE)]
        selected = [s.upper() for s in selected if s.upper() in all_ids]
        if not selected:
            return AHVSStageResult(
                stage=AHVSStage.AHVS_HUMAN_SELECTION,
                status=StageStatus.FAILED,
                artifacts=(),
                error=f"No valid hypothesis IDs found in input: '{raw}'",
            )

    print(f"\nRationale for selection (optional, press Enter to skip):")
    try:
        rationale = input("> ").strip() or "Operator selection"
    except (EOFError, KeyboardInterrupt):
        rationale = "Operator selection"

    print(f"\n[AHVS] Selected: {', '.join(selected)}")

    return _finalize_selection(
        cycle_dir, config, hypotheses, selected, rationale,
        "operator", auto_approve,
    )


def _finalize_selection(
    cycle_dir: Path,
    config: AHVSConfig,
    hypotheses: list[dict],
    selected: list[str],
    rationale: str,
    approved_by: str,
    auto_approve: bool,
) -> AHVSStageResult:
    """Run pre-flight checks, write selection artifacts, return stage result."""
    # Run secondary pre-flight for the selected hypothesis types
    selected_types = [
        h["type"] for h in hypotheses if h["id"] in selected
    ]
    if selected_types:
        tool_report = run_ahvs_preflight(
            baseline_path=config.baseline_path,
            repo_path=config.repo_path,
            regression_guard_path=config.regression_guard_path,
            hypothesis_types=selected_types,
            skip_llm_check=True,  # LLM connectivity already verified at Stage 1
        )
        failed_checks = [c for c in tool_report.checks if c.status == "fail"]
        if failed_checks:
            details = "; ".join(c.detail for c in failed_checks)
            print(f"\n[AHVS] WARNING: Tool pre-flight issues: {details}")
            if auto_approve or approved_by == "caller":
                logger.warning(
                    "%s mode: continuing despite tool pre-flight failures",
                    approved_by,
                )
            else:
                print("[AHVS] Some hypotheses may fail at execution. Continue anyway? (y/N)")
                try:
                    confirm = input("> ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    confirm = "n"
                if confirm not in ("y", "yes"):
                    return AHVSStageResult(
                        stage=AHVSStage.AHVS_HUMAN_SELECTION,
                        status=StageStatus.FAILED,
                        artifacts=(),
                        error=f"Operator aborted: tool pre-flight failed: {details}",
                    )

    selection = {
        "selected": selected,
        "rationale": rationale,
        "approved_by": approved_by,
        "timestamp": _utcnow_iso(),
    }
    sel_path = cycle_dir / "selection.md"
    sel_path.write_text(
        f"# Selected Hypotheses\n\n"
        f"**Selected:** {', '.join(selected)}\n\n"
        f"**Rationale:** {rationale}\n\n"
        f"**Approved By:** {selection['approved_by']}\n\n"
        f"**Timestamp:** {selection['timestamp']}\n",
        encoding="utf-8",
    )
    # Also write JSON for easy machine parsing
    (cycle_dir / "selection.json").write_text(
        json.dumps(selection, indent=2), encoding="utf-8"
    )

    return AHVSStageResult(
        stage=AHVSStage.AHVS_HUMAN_SELECTION,
        status=StageStatus.DONE,
        artifacts=("selection.md",),
    )


def _execute_validation_plan(
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
    auto_approve: bool,
) -> AHVSStageResult:
    """Stage 5: Generate per-hypothesis implementation + eval plan via LLM."""
    for required in ("context_bundle.json", "selection.json", "hypotheses.md"):
        if not (cycle_dir / required).exists():
            return AHVSStageResult(
                stage=AHVSStage.AHVS_VALIDATION_PLAN,
                status=StageStatus.FAILED,
                artifacts=(),
                error=f"Missing required artifact: {required}",
            )

    bundle = json.loads((cycle_dir / "context_bundle.json").read_text(encoding="utf-8"))
    selection = json.loads((cycle_dir / "selection.json").read_text(encoding="utf-8"))
    hypotheses_text = (cycle_dir / "hypotheses.md").read_text(encoding="utf-8")
    hypotheses = _parse_hypotheses(hypotheses_text)

    selected_ids = set(selection["selected"])
    selected_hyps = [h for h in hypotheses if h["id"] in selected_ids]

    # Build selected hypotheses text for prompt
    selected_text = "\n\n".join(
        f"### {h['id']}\n"
        f"**Type:** {h['type']}\n"
        f"**Description:** {h['description']}\n"
        f"**Rationale:** {h['rationale']}"
        for h in selected_hyps
    )

    # Determine available skills for context block
    available_tools = skill_library.detect_available_tools()
    all_applicable_skills: list = []
    for h in selected_hyps:
        skills = skill_library.for_hypothesis_type(h["type"], available_tools)
        for s in skills:
            if s not in all_applicable_skills:
                all_applicable_skills.append(s)
    skills_block = skill_library.to_context_block(all_applicable_skills) or "No skills available."

    baseline = bundle["baseline"]
    pm = AHVSPromptManager(config.prompts_override_path)
    prompt = pm.for_stage(
        "ahvs_validation_plan",
        question=config.question,
        metric_name=baseline["primary_metric"],
        baseline_value=str(baseline["value"]),
        eval_command=baseline.get("eval_command", ""),
        selected_hypotheses_text=selected_text,
        available_skills_block=skills_block,
    )

    try:
        llm = _make_llm_client(config)
        response = llm.chat(
            [{"role": "user", "content": prompt.user}],
            system=prompt.system,
            max_tokens=prompt.max_tokens,
        )
        plan_text = response.content
    except Exception as exc:  # noqa: BLE001
        return AHVSStageResult(
            stage=AHVSStage.AHVS_VALIDATION_PLAN,
            status=StageStatus.FAILED,
            artifacts=(),
            error=f"LLM call failed: {exc}",
        )

    plan_path = cycle_dir / "validation_plan.md"
    plan_path.write_text(plan_text, encoding="utf-8")

    return AHVSStageResult(
        stage=AHVSStage.AHVS_VALIDATION_PLAN,
        status=StageStatus.DONE,
        artifacts=("validation_plan.md",),
    )


def _execute_hypotheses(
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
    auto_approve: bool,
) -> AHVSStageResult:
    """Stage 6: Invoke CodeAgent for each selected hypothesis; collect results."""
    for required in ("validation_plan.md", "selection.json", "context_bundle.json"):
        if not (cycle_dir / required).exists():
            return AHVSStageResult(
                stage=AHVSStage.AHVS_EXECUTION,
                status=StageStatus.FAILED,
                artifacts=(),
                error=f"Missing required artifact: {required}",
            )

    selection = json.loads((cycle_dir / "selection.json").read_text(encoding="utf-8"))
    bundle = json.loads((cycle_dir / "context_bundle.json").read_text(encoding="utf-8"))
    plan_text = (cycle_dir / "validation_plan.md").read_text(encoding="utf-8")
    hypotheses_text = (cycle_dir / "hypotheses.md").read_text(encoding="utf-8")

    plans = _parse_validation_plan(plan_text)
    hypotheses = _parse_hypotheses(hypotheses_text)
    hyp_by_id = {h["id"]: h for h in hypotheses}
    plan_by_id = {p["id"]: p for p in plans}

    baseline = bundle["baseline"]
    available_tools = skill_library.detect_available_tools()

    from researchclaw.ahvs.worktree import HypothesisWorktree

    results_and_worktrees: list[tuple[HypothesisResult, HypothesisWorktree | None]] = []

    for hyp_id in selection["selected"]:
        hyp = hyp_by_id.get(hyp_id)
        plan = plan_by_id.get(hyp_id)

        if not hyp or not plan:
            results_and_worktrees.append((
                HypothesisResult.make_error(
                    hypothesis_id=hyp_id,
                    hypothesis_type="unknown",
                    primary_metric=baseline["primary_metric"],
                    baseline_value=float(baseline["value"]),
                    error=f"No hypothesis or plan found for {hyp_id}",
                ),
                None,
            ))
            continue

        result, worktree = _run_single_hypothesis(
            hyp_id=hyp_id,
            hyp=hyp,
            plan=plan,
            cycle_dir=cycle_dir,
            config=config,
            skill_library=skill_library,
            baseline=baseline,
            available_tools=available_tools,
        )
        results_and_worktrees.append((result, worktree))
        measurement_tag = ""
        if result.measurement_status == "extraction_failed":
            measurement_tag = " [MEASUREMENT FAILED]"
        elif result.measurement_status == "sandbox_error":
            measurement_tag = " [SANDBOX ERROR]"
        print(
            f"[AHVS] {hyp_id}: {baseline['primary_metric']}="
            f"{result.metric_value:.4f} (Δ{result.delta:+.4f}) "
            f"{'✓ improved' if result.improved else '✗ no improvement'}"
            + measurement_tag
            + (f" | ERROR: {result.error}" if result.error else "")
        )

    # ── Keep/revert: save patches, keep best, clean up losers ────────
    results = [r for r, _ in results_and_worktrees]
    improved = [(r, wt) for r, wt in results_and_worktrees if r.improved and wt]
    best_result = (
        max((r for r, _ in improved), key=lambda r: r.delta) if improved else None
    )

    for result, worktree in results_and_worktrees:
        if worktree is None:
            continue
        # Save patch for every hypothesis (audit trail)
        work_dir = cycle_dir / "tool_runs" / result.hypothesis_id
        patch_path = work_dir / f"{result.hypothesis_id}.patch"
        worktree.save_patch(patch_path)
        result.patch_path = str(patch_path.relative_to(cycle_dir))

        if result is best_result:
            result.kept = True
            result.worktree_path = str(worktree.worktree_path)
        else:
            worktree.cleanup()

    save_results(results, cycle_dir / "results.json")

    return AHVSStageResult(
        stage=AHVSStage.AHVS_EXECUTION,
        status=StageStatus.DONE,
        artifacts=("results.json", "tool_runs/"),
    )


def _run_single_hypothesis(
    hyp_id: str,
    hyp: dict,
    plan: dict,
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
    baseline: dict,
    available_tools: set[str],
) -> tuple[HypothesisResult, "HypothesisWorktree | None"]:
    """Execute one hypothesis using CodeAgent and return (result, worktree).

    The worktree object is returned so the caller can manage keep/revert.
    """
    from researchclaw.pipeline.code_agent import CodeAgent, CodeAgentConfig
    from researchclaw.prompts import PromptManager
    from researchclaw.ahvs.worktree import HypothesisWorktree

    work_dir = cycle_dir / "tool_runs" / hyp_id
    work_dir.mkdir(parents=True, exist_ok=True)

    hyp_type = hyp.get("type", "code_change")
    metric_name = baseline["primary_metric"]
    baseline_value = float(baseline["value"])

    # Build skill context for this hypothesis type
    skills = skill_library.for_hypothesis_type(hyp_type, available_tools)
    skill_context = skill_library.to_context_block(skills)

    # Build CodeAgent problem statement
    eval_command = baseline.get("eval_command", "")
    repo_grounding = (
        f"## Repo-Grounded Execution\n"
        f"Your generated files will be applied to a git worktree of the target\n"
        f"repository. Use paths **relative to the repo root**.\n"
        f"Repository root: {config.repo_path}\n\n"
    )
    eval_section = ""
    if eval_command:
        eval_section = (
            f"## Eval Command\n"
            f"After your files are applied, this command will be run in the\n"
            f"worktree to measure the result:\n"
            f"```\n{eval_command}\n```\n"
            f"Make sure your output is compatible with this command.\n\n"
        )
    problem = (
        f"# AHVS Hypothesis Execution\n\n"
        f"## Hypothesis {hyp_id}\n"
        f"**Type:** {hyp_type}\n"
        f"**Description:** {hyp.get('description', '')}\n"
        f"**Rationale:** {hyp.get('rationale', '')}\n\n"
        f"## Implementation Plan\n"
        f"{plan.get('implementation_approach', 'Implement as described in description.')}\n\n"
        f"## Eval Method\n"
        f"Use: {plan.get('eval_method', 'custom_script')}\n"
        f"Skill: {plan.get('skill', 'sandbox_run')}\n\n"
        f"## Success Criterion\n"
        f"{plan.get('success_criterion', f'{metric_name} > {baseline_value}')}\n\n"
        f"## Target Repository\n"
        f"{config.repo_path}\n\n"
        f"{repo_grounding}"
        f"{eval_section}"
        f"## Primary Metric\n"
        f"Name: {metric_name}\n"
        f"Baseline value: {baseline_value}\n\n"
        f"## Output Requirements\n"
        f"Write the metric result as JSON to: result.json\n"
        f"Format: {{'{metric_name}': <float>, 'eval_method': '<method>'}}\n\n"
        f"{skill_context}"
    )

    # Inject type-specific execution strategy
    type_strategy = _TYPE_EXECUTION_STRATEGIES.get(hyp_type, {})
    if type_strategy:
        problem += (
            f"\n## Type-Specific Execution Strategy ({hyp_type})\n"
            f"{type_strategy['system_addition']}\n\n"
            f"**Constraints:** {type_strategy['constraints']}\n"
            f"**Success Guidance:** {type_strategy['success_guidance']}\n\n"
        )

    # Package hint based on hypothesis type
    pkg_hint_map = {
        "prompt_rewrite": "promptfoo",
        "model_comparison": "openai anthropic",
        "dspy_optimize": "dspy-ai",
        "code_change": "pytest",
        "architecture_change": "pytest",
        "multi_llm_judge": "openai anthropic",
    }
    pkg_hint = pkg_hint_map.get(hyp_type, "")

    t0 = time.monotonic()
    metric_value = baseline_value
    measurement_status = "not_executed"
    skill_planned = plan.get("skill") or None
    error: str | None = None
    artifact_paths: list[str] = []
    worktree: HypothesisWorktree | None = None

    # ── Create worktree ──────────────────────────────────────────────
    try:
        wt_path = cycle_dir / "worktrees" / hyp_id
        worktree = HypothesisWorktree(config.repo_path, wt_path)
        worktree.create()
    except Exception as exc:  # noqa: BLE001
        if not config.allow_sandbox_only:
            logger.error(
                "%s: worktree creation failed (%s) — failing hypothesis "
                "(use --allow-sandbox-only to permit sandbox-only fallback)",
                hyp_id, exc,
            )
            return (
                HypothesisResult.make_error(
                    hypothesis_id=hyp_id,
                    hypothesis_type=hyp_type,
                    primary_metric=metric_name,
                    baseline_value=baseline_value,
                    error=f"Worktree creation failed: {exc}",
                ),
                None,
            )
        logger.warning(
            "%s: worktree creation failed (%s) — falling back to sandbox-only "
            "(--allow-sandbox-only is set)",
            hyp_id, exc,
        )
        worktree = None

    try:
        llm = _make_llm_client(config)
        pm = PromptManager()
        agent_cfg = CodeAgentConfig(
            enabled=True,
            architecture_planning=True,
            sequential_generation=True,
            hard_validation=True,
            exec_fix_max_iterations=2,
            tree_search_enabled=False,
            review_max_rounds=1,
        )
        sandbox_factory = _make_sandbox_factory(config)

        agent = CodeAgent(
            llm=llm,
            prompts=pm,
            config=agent_cfg,
            stage_dir=work_dir,
            sandbox_factory=sandbox_factory,
        )

        agent_result = agent.generate(
            topic=f"AHVS hypothesis {hyp_id}: {hyp.get('description', '')}",
            exp_plan=problem,
            metric=metric_name,
            pkg_hint=pkg_hint,
        )

        # Write generated files to work_dir (with path validation)
        from researchclaw.ahvs.worktree import validate_safe_relpath

        for filename, content in agent_result.files.items():
            validate_safe_relpath(filename, work_dir)
            fpath = (work_dir / filename).resolve()
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")
            artifact_paths.append(str(fpath.relative_to(cycle_dir)))

        # Apply generated files to worktree
        if worktree is not None and agent_result.files:
            worktree.apply_files(agent_result.files)

        # ── Five-tier metric extraction ──────────────────────────────

        # Tier 0 (NEW): eval_command in worktree
        if (
            measurement_status != "measured"
            and eval_command
            and worktree is not None
        ):
            logger.info("%s: running eval_command in worktree: %s", hyp_id, eval_command)
            eval_result = worktree.run_eval_command(eval_command)
            if eval_result.returncode == 0:
                extracted = _extract_metric_from_output(eval_result.stdout, metric_name)
                if extracted is not None:
                    metric_value = extracted
                    measurement_status = "measured"
                    logger.info(
                        "%s: Tier 0 (eval_command) extracted %s=%.4f",
                        hyp_id, metric_name, metric_value,
                    )
            else:
                logger.warning(
                    "%s: eval_command exited %d — falling through to sandbox tiers. "
                    "stderr: %s",
                    hyp_id, eval_result.returncode,
                    eval_result.stderr[:300],
                )

        # Tier 1: result.json in work_dir
        result_json_path = work_dir / "result.json"
        if not result_json_path.exists():
            # Tier 1b: result.json in agent_runs subdirectories (sandbox copy-back)
            for candidate in sorted(work_dir.glob("agent_runs/*/result.json")):
                result_json_path = candidate
                break

        if measurement_status != "measured" and result_json_path.exists():
            raw = result_json_path.read_text(encoding="utf-8")
            extracted = _extract_metric_from_output(raw, metric_name)
            if extracted is not None:
                metric_value = extracted
                measurement_status = "measured"

        # Tier 2: Direct from sandbox-parsed metrics
        if measurement_status != "measured" and agent_result.best_metrics:
            val = agent_result.best_metrics.get(metric_name)
            if isinstance(val, (int, float)):
                metric_value = float(val)
                measurement_status = "measured"

        # Tier 3: Parse raw sandbox stdout
        if measurement_status != "measured" and agent_result.best_stdout:
            extracted = _extract_metric_from_output(agent_result.best_stdout, metric_name)
            if extracted is not None:
                metric_value = extracted
                measurement_status = "measured"

        # Tier 4: Extraction failed — log warning, keep baseline
        if measurement_status != "measured":
            measurement_status = "extraction_failed"
            logger.warning(
                "%s: metric extraction failed across all sources — "
                "metric_value remains at baseline (%.4f). "
                "Hypothesis code may not have produced output.",
                hyp_id, baseline_value,
            )

    except Exception as exc:  # noqa: BLE001
        error = f"CodeAgent execution failed: {exc}"
        measurement_status = "sandbox_error"
        logger.exception("CodeAgent failed for %s", hyp_id)

    duration = time.monotonic() - t0

    # Write canonical result.json so the regression guard always has a file
    # to inspect, regardless of which tier produced the metric.
    canonical_result_path = work_dir / "result.json"
    canonical_result = {
        "hypothesis_id": hyp_id,
        "primary_metric": metric_name,
        metric_name: metric_value,
        "baseline_value": baseline_value,
        "measurement_status": measurement_status,
    }
    canonical_result_path.write_text(
        json.dumps(canonical_result, indent=2), encoding="utf-8"
    )

    # Run regression guard against the canonical result
    guard_passed = _run_regression_guard(config.regression_guard_path, canonical_result_path)

    delta = metric_value - baseline_value
    delta_pct = (delta / baseline_value * 100) if baseline_value != 0 else 0.0

    result = HypothesisResult(
        hypothesis_id=hyp_id,
        hypothesis_type=hyp_type,
        primary_metric=metric_name,
        metric_value=metric_value,
        baseline_value=baseline_value,
        delta=delta,
        delta_pct=delta_pct,
        regression_guard_passed=guard_passed,
        eval_method=plan.get("eval_method", "code_agent"),
        artifact_paths=artifact_paths,
        raw_output_path=str(work_dir),
        duration_seconds=round(duration, 2),
        skill_planned=skill_planned,
        error=error,
        measurement_status=measurement_status,
        execution_mode="sandbox_only" if worktree is None else "repo_grounded",
    )
    return result, worktree


def _execute_report_and_memory(
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
    auto_approve: bool,
) -> AHVSStageResult:
    """Stage 7: Write cycle report via LLM; archive lessons to EvolutionStore."""
    for required in ("results.json", "context_bundle.json"):
        if not (cycle_dir / required).exists():
            return AHVSStageResult(
                stage=AHVSStage.AHVS_REPORT_MEMORY,
                status=StageStatus.FAILED,
                artifacts=(),
                error=f"Missing required artifact: {required}",
            )

    from researchclaw.ahvs.result import load_results
    from researchclaw.evolution import EvolutionStore, LessonEntry, LessonCategory

    results = load_results(cycle_dir / "results.json")
    bundle = json.loads((cycle_dir / "context_bundle.json").read_text(encoding="utf-8"))
    baseline = bundle["baseline"]
    metric_name = baseline["primary_metric"]

    # Build results summary for prompt
    summary_lines = []
    best_result: HypothesisResult | None = None
    for r in results:
        status_str = "IMPROVED" if r.improved else ("ERROR" if r.error else "no improvement")
        measurement_tag = ""
        if r.measurement_status == "extraction_failed":
            measurement_tag = " [MEASUREMENT FAILED]"
        elif r.measurement_status == "sandbox_error":
            measurement_tag = " [SANDBOX ERROR]"
        summary_lines.append(
            f"- **{r.hypothesis_id}** ({r.hypothesis_type}): "
            f"{metric_name}={r.metric_value:.4f} (Δ{r.delta:+.4f}, {r.delta_pct:+.1f}%) "
            f"| guard={'pass' if r.regression_guard_passed else 'fail'} "
            f"| {status_str}{measurement_tag}"
            + (f"\n  Error: {r.error}" if r.error else "")
        )
        if r.improved and (best_result is None or r.delta > best_result.delta):
            best_result = r
    results_summary = "\n".join(summary_lines) or "No results."

    pm = AHVSPromptManager(config.prompts_override_path)
    prompt = pm.for_stage(
        "ahvs_report",
        question=config.question,
        metric_name=metric_name,
        baseline_value=str(baseline["value"]),
        results_summary=results_summary,
    )

    report_text = ""
    try:
        llm = _make_llm_client(config)
        response = llm.chat(
            [{"role": "user", "content": prompt.user}],
            system=prompt.system,
            max_tokens=prompt.max_tokens,
        )
        report_text = response.content
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM report generation failed: %s — writing minimal report", exc)
        report_text = (
            f"# AHVS Cycle Report\n\n"
            f"**Question:** {config.question}\n\n"
            f"**Results:**\n{results_summary}\n\n"
            f"*Report generation failed: {exc}*"
        )

    (cycle_dir / "report.md").write_text(report_text, encoding="utf-8")

    # Write friction log (auto-generated from execution errors)
    # Operators should add their own observations below the auto-generated section.
    friction_items = [
        f"- {r.hypothesis_id}: {r.error}"
        for r in results
        if r.error
    ]
    measurement_items = [
        f"- {r.hypothesis_id}: metric extraction failed (measurement_status={r.measurement_status})"
        for r in results
        if r.measurement_status in ("extraction_failed", "sandbox_error")
    ]
    friction_text = (
        "# Friction Log\n\n"
        "## Execution Errors (auto-generated)\n\n"
        + ("\n".join(friction_items) if friction_items else "No execution errors this cycle.")
        + "\n\n"
        "## Measurement Issues (auto-generated)\n\n"
        + ("\n".join(measurement_items) if measurement_items else "No measurement issues.")
        + "\n\n"
        "## Operator Notes\n\n"
        "<!-- Add your observations below: What felt slow? What felt unclear?\n"
        "     What almost got skipped? What should be automated next? -->\n\n"
    )
    (cycle_dir / "friction_log.md").write_text(friction_text, encoding="utf-8")

    # Archive lessons to EvolutionStore
    config.evolution_dir.mkdir(parents=True, exist_ok=True)
    try:
        store = EvolutionStore(config.evolution_dir)
        now = _utcnow_iso()
        cycle_id = cycle_dir.name
        lessons: list[LessonEntry] = []

        for r in results:
            if r.improved:
                lessons.append(LessonEntry(
                    stage_name="ahvs_execution",
                    stage_num=6,
                    category=LessonCategory.EXPERIMENT,
                    severity="info",
                    description=(
                        f"[{cycle_id}] {r.hypothesis_id} ({r.hypothesis_type}) improved "
                        f"{metric_name} by {r.delta:+.4f} ({r.delta_pct:+.1f}%). "
                        f"Eval: {r.eval_method}."
                    ),
                    timestamp=now,
                    run_id=cycle_id,
                ))
            elif r.error:
                lessons.append(LessonEntry(
                    stage_name="ahvs_execution",
                    stage_num=6,
                    category=LessonCategory.EXPERIMENT,
                    severity="warning",
                    description=(
                        f"[{cycle_id}] {r.hypothesis_id} ({r.hypothesis_type}) FAILED: {r.error[:150]}"
                    ),
                    timestamp=now,
                    run_id=cycle_id,
                ))
            elif r.measurement_status != "measured":
                # Infrastructure failure (extraction_failed, sandbox_error, etc.)
                # — the hypothesis was never actually tested.  Do NOT record as
                # a "Rejected approach" or it will teach AHVS to avoid ideas
                # that were never validated.
                lessons.append(LessonEntry(
                    stage_name="ahvs_execution",
                    stage_num=6,
                    category=LessonCategory.EXPERIMENT,
                    severity="warning",
                    description=(
                        f"[{cycle_id}] {r.hypothesis_id} ({r.hypothesis_type}) "
                        f"measurement failed ({r.measurement_status}). "
                        f"Infrastructure issue — hypothesis was not tested."
                    ),
                    timestamp=now,
                    run_id=cycle_id,
                ))
            else:
                lessons.append(LessonEntry(
                    stage_name="ahvs_execution",
                    stage_num=6,
                    category=LessonCategory.EXPERIMENT,
                    severity="info",
                    description=(
                        f"[{cycle_id}] {r.hypothesis_id} ({r.hypothesis_type}) did not improve "
                        f"{metric_name} (Δ{r.delta:+.4f}). Rejected approach."
                    ),
                    timestamp=now,
                    run_id=cycle_id,
                ))

        if lessons:
            store.append_many(lessons)
            logger.info("Archived %d lessons to EvolutionStore", len(lessons))
    except Exception as exc:  # noqa: BLE001
        logger.warning("EvolutionStore archival failed (non-fatal): %s", exc)

    return AHVSStageResult(
        stage=AHVSStage.AHVS_REPORT_MEMORY,
        status=StageStatus.DONE,
        artifacts=("report.md", "friction_log.md"),
    )


def _execute_cycle_verify(
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
    auto_approve: bool,
) -> AHVSStageResult:
    """Stage 8: Validate all artifacts exist and write cycle_summary.json."""
    from researchclaw.ahvs.result import load_results

    # Check required artifacts
    required = [
        "cycle_manifest.json", "context_bundle.json", "hypotheses.md",
        "selection.md", "validation_plan.md", "results.json",
        "report.md", "friction_log.md",
    ]
    missing = [f for f in required if not (cycle_dir / f).exists()]
    if missing:
        return AHVSStageResult(
            stage=AHVSStage.AHVS_CYCLE_VERIFY,
            status=StageStatus.FAILED,
            artifacts=(),
            error=f"Missing artifacts: {missing}",
        )

    # Validate results.json
    try:
        results = load_results(cycle_dir / "results.json")
    except Exception as exc:  # noqa: BLE001
        return AHVSStageResult(
            stage=AHVSStage.AHVS_CYCLE_VERIFY,
            status=StageStatus.FAILED,
            artifacts=(),
            error=f"results.json invalid: {exc}",
        )

    selection = json.loads((cycle_dir / "selection.json").read_text(encoding="utf-8"))
    result_ids = {r.hypothesis_id for r in results}
    missing_results = [hid for hid in selection["selected"] if hid not in result_ids]
    if missing_results:
        return AHVSStageResult(
            stage=AHVSStage.AHVS_CYCLE_VERIFY,
            status=StageStatus.FAILED,
            artifacts=(),
            error=f"Selected hypotheses with no result: {missing_results}",
        )

    # Build cycle summary
    improved = [r for r in results if r.improved]
    best = max(improved, key=lambda r: r.delta) if improved else None
    bundle = json.loads((cycle_dir / "context_bundle.json").read_text(encoding="utf-8"))
    metric_name = bundle["baseline"]["primary_metric"]

    extraction_failures = sum(1 for r in results if r.measurement_status == "extraction_failed")
    measured_count = sum(1 for r in results if r.measurement_status == "measured")
    all_unmeasured = measured_count == 0 and len(results) > 0

    # Build recommendation based on measurement validity
    if all_unmeasured:
        recommendation = (
            "INVALID CYCLE — all hypotheses failed measurement. "
            "No valid comparison to baseline is possible."
        )
    elif best:
        recommendation = (
            f"KEEP {best.hypothesis_id}: {metric_name} improved by "
            f"{best.delta:+.4f} ({best.delta_pct:+.1f}%)"
        )
    else:
        recommendation = "no improvement this cycle — revert all changes"

    summary = {
        "cycle_id": cycle_dir.name,
        "question": config.question,
        "hypotheses_run": len(results),
        "hypotheses_measured": measured_count,
        "hypotheses_improved": len(improved),
        "extraction_failures": extraction_failures,
        "all_unmeasured": all_unmeasured,
        "best_hypothesis": best.hypothesis_id if best else None,
        "best_delta": best.delta if best else 0.0,
        "best_metric_value": best.metric_value if best else None,
        "recommendation": recommendation,
        "kept_worktree": best.worktree_path if best and best.worktree_path else None,
        "kept_patch": best.patch_path if best and best.patch_path else None,
        "all_patches": [r.patch_path for r in results if r.patch_path],
        "per_hypothesis": [
            {
                "id": r.hypothesis_id,
                "execution_mode": r.execution_mode,
                "metric_value": r.metric_value,
                "delta": r.delta,
                "measurement_status": r.measurement_status,
            }
            for r in results
        ],
        "completed_at": _utcnow_iso(),
        "artifacts_verified": required,
    }
    (cycle_dir / "cycle_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(f"\n[AHVS] Cycle complete — {recommendation}")

    # All-unmeasured cycle is a verification failure
    if all_unmeasured:
        return AHVSStageResult(
            stage=AHVSStage.AHVS_CYCLE_VERIFY,
            status=StageStatus.FAILED,
            artifacts=("cycle_summary.json",),
            error="All hypotheses failed measurement — cycle is invalid",
        )

    return AHVSStageResult(
        stage=AHVSStage.AHVS_CYCLE_VERIFY,
        status=StageStatus.DONE,
        artifacts=("cycle_summary.json",),
    )


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    AHVSStage.AHVS_SETUP:           _execute_setup,
    AHVSStage.AHVS_CONTEXT_LOAD:    _execute_context_load,
    AHVSStage.AHVS_HYPOTHESIS_GEN:  _execute_hypothesis_gen,
    AHVSStage.AHVS_HUMAN_SELECTION: _execute_human_selection,
    AHVSStage.AHVS_VALIDATION_PLAN: _execute_validation_plan,
    AHVSStage.AHVS_EXECUTION:       _execute_hypotheses,
    AHVSStage.AHVS_REPORT_MEMORY:   _execute_report_and_memory,
    AHVSStage.AHVS_CYCLE_VERIFY:    _execute_cycle_verify,
}


def execute_ahvs_stage(
    stage: AHVSStage,
    *,
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
    auto_approve: bool = False,
) -> AHVSStageResult:
    """Dispatch to the appropriate stage handler."""
    handler = _HANDLERS.get(stage)
    if handler is None:
        return AHVSStageResult(
            stage=stage,
            status=StageStatus.FAILED,
            artifacts=(),
            error=f"No handler registered for stage {stage!r}",
        )
    return handler(cycle_dir, config, skill_library, auto_approve)
