"""AHVS-specific pre-flight health checks.

Extends ARC's CheckResult/DoctorReport pattern from researchclaw.health.
Pre-flight runs twice per cycle:
  1. At AHVS_SETUP — minimal: baseline file + LLM connectivity
  2. After AHVS_HUMAN_SELECTION — full: tools required by selected hypothesis types
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from researchclaw.health import CheckResult, DoctorReport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hypothesis type → required external tools
# ---------------------------------------------------------------------------

HYPOTHESIS_TOOL_REQUIREMENTS: dict[str, list[str]] = {
    "prompt_rewrite":      ["promptfoo"],
    "model_comparison":    ["promptfoo"],
    "config_change":       ["promptfoo"],
    "dspy_optimize":       ["dspy", "promptfoo"],
    "phoenix_eval":        ["arize-phoenix"],
    # code_change, architecture_change, multi_llm_judge use the local
    # ExperimentSandbox (python3), not Docker.  No external tool required.
    "code_change":         [],
    "architecture_change": [],
    "multi_llm_judge":     [],
}


def check_tool(name: str) -> CheckResult:
    """Generic availability check: CLI tool, Python package, or Node package (npx)."""
    # 1. CLI tool — covers docker, promptfoo (global install), etc.
    if shutil.which(name):
        return CheckResult(
            name=f"tool_{name}",
            status="pass",
            detail=f"'{name}' found on PATH: {shutil.which(name)}",
        )

    # 2. Python package — covers dspy, arize-phoenix (import as arize_phoenix), etc.
    pkg_name = name.replace("-", "_")
    if importlib.util.find_spec(pkg_name) is not None:
        return CheckResult(
            name=f"tool_{name}",
            status="pass",
            detail=f"Python package '{name}' is importable",
        )

    # 3. Node package via npx — covers promptfoo (npm install)
    if name == "promptfoo":
        try:
            r = subprocess.run(
                ["npx", name, "--version"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if r.returncode == 0:
                version = r.stdout.decode(errors="replace").strip().splitlines()[0]
                return CheckResult(
                    name=f"tool_{name}",
                    status="pass",
                    detail=f"'{name}' available via npx: {version}",
                )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    return CheckResult(
        name=f"tool_{name}",
        status="fail",
        detail=f"'{name}' not found (checked: PATH, Python packages, npx)",
        fix=f"Install '{name}'. See project docs for setup instructions.",
    )


def check_baseline_metric(baseline_path: Path) -> CheckResult:
    """Validate .ahvs/baseline_metric.json exists and contains required fields."""
    if not baseline_path.exists():
        return CheckResult(
            name="ahvs_baseline",
            status="fail",
            detail=f"Baseline metric file not found: {baseline_path}",
            fix=(
                "Create .ahvs/baseline_metric.json. Example:\n"
                '  {"primary_metric": "answer_relevance", "answer_relevance": 0.74,\n'
                '   "recorded_at": "2026-03-17T10:00:00Z",\n'
                '   "eval_command": "promptfoo eval --config .ahvs/eval/baseline.yaml"}'
            ),
        )
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return CheckResult(
            name="ahvs_baseline",
            status="fail",
            detail=f"baseline_metric.json is invalid: {exc}",
            fix="Fix JSON syntax in .ahvs/baseline_metric.json",
        )

    required = ("primary_metric", "recorded_at", "eval_command")
    missing = [f for f in required if f not in data]
    if missing:
        return CheckResult(
            name="ahvs_baseline",
            status="fail",
            detail=f"baseline_metric.json missing fields: {missing}",
            fix="Add the missing fields to .ahvs/baseline_metric.json",
        )

    metric_key = data["primary_metric"]
    if metric_key not in data:
        return CheckResult(
            name="ahvs_baseline",
            status="fail",
            detail=f"baseline_metric.json must contain key '{metric_key}' with its numeric value",
            fix=f'Add "{metric_key}": <float> to .ahvs/baseline_metric.json',
        )

    return CheckResult(
        name="ahvs_baseline",
        status="pass",
        detail=(
            f"Baseline: {metric_key}={data[metric_key]} "
            f"(recorded {str(data.get('recorded_at', ''))[:10]})"
        ),
    )


def check_baseline_commit(baseline_path: Path) -> CheckResult | None:
    """Warn if baseline_metric.json lacks a 'commit' field.

    Returns None if the baseline file doesn't exist (that's caught by
    check_baseline_metric). Returns a warn CheckResult if commit is missing.
    """
    if not baseline_path.exists():
        return None
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None  # Caught by check_baseline_metric
    if "commit" not in data or not data["commit"]:
        return CheckResult(
            name="ahvs_baseline_commit",
            status="warn",
            detail=(
                "baseline_metric.json has no 'commit' field — "
                "cannot verify baseline was measured on the current repo state"
            ),
            fix='Add "commit": "<git-sha>" to .ahvs/baseline_metric.json',
        )
    return CheckResult(
        name="ahvs_baseline_commit",
        status="pass",
        detail=f"Baseline commit: {data['commit']}",
    )


def check_regression_guard(guard_path: Path) -> CheckResult:
    """Validate regression_guard.sh exists and is executable."""
    if not guard_path.exists():
        return CheckResult(
            name="ahvs_regression_guard",
            status="fail",
            detail=f"Regression guard script not found: {guard_path}",
            fix="Create the script or remove --regression-guard from config",
        )
    if not os.access(guard_path, os.X_OK):
        return CheckResult(
            name="ahvs_regression_guard",
            status="fail",
            detail=f"Regression guard not executable: {guard_path}",
            fix=f"chmod +x {guard_path}",
        )
    return CheckResult(
        name="ahvs_regression_guard",
        status="pass",
        detail=f"Regression guard found and executable: {guard_path}",
    )


def check_clean_branch(repo_path: Path) -> CheckResult:
    """Fail if the target repo has uncommitted changes.

    AHVS creates hypothesis worktrees from committed HEAD, so uncommitted
    changes in the working tree are **not** tested.  A dirty repo means
    the operator thinks they are validating the current state, but AHVS
    actually measures an older committed snapshot — a real reproducibility
    trap.  Therefore this is a hard fail, not a warning.
    """
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            cwd=repo_path,
            timeout=10,
            check=False,
        )
        if r.returncode != 0:
            return CheckResult(
                name="ahvs_clean_branch",
                status="warn",
                detail="Could not check git status (not a git repo?)",
                fix="Ensure the target repo is a git repository",
            )
        output = r.stdout.decode(errors="replace").strip()
        if output:
            return CheckResult(
                name="ahvs_clean_branch",
                status="fail",
                detail=(
                    "Target repo has uncommitted changes — AHVS worktrees are "
                    "created from committed HEAD, so uncommitted work would not "
                    "be included in the experiment"
                ),
                fix="Commit or stash changes before running an AHVS cycle",
            )
        return CheckResult(
            name="ahvs_clean_branch",
            status="pass",
            detail="Target repo working tree is clean",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return CheckResult(
            name="ahvs_clean_branch",
            status="warn",
            detail="git not found — cannot verify branch cleanliness",
            fix="Install git to enable this check",
        )


def check_llm_connectivity(
    api_key: str,
    model: str,
    base_url: str = "",
    provider: str = "",
    ahvs_config: object | None = None,
) -> CheckResult:
    """Lightweight LLM ping — verify connectivity before the cycle starts.

    When *provider* is ``"acp"``, uses ``ACPClient.preflight()`` instead
    of sending a real chat completion — no API key required.

    *ahvs_config* is an optional ``AHVSConfig`` instance used only in ACP
    mode to construct the client via the shared factory shim.
    """
    # ── ACP path: verify acpx + agent binary, no API key needed ──────
    if provider == "acp":
        return _check_llm_acp(ahvs_config)

    # ── API-key path (original behaviour) ────────────────────────────
    if not api_key:
        return CheckResult(
            name="ahvs_llm_connectivity",
            status="fail",
            detail="No API key configured (checked env var and config)",
            fix="Set the API key env var (e.g. ANTHROPIC_API_KEY) or pass --api-key-env",
        )
    try:
        from researchclaw.llm.client import LLMClient, LLMConfig

        llm_cfg = LLMConfig(
            base_url=base_url or "https://api.anthropic.com/v1",
            api_key=api_key,
            primary_model=model,
        )
        client = LLMClient(llm_cfg)

        # Use the Anthropic adapter for Claude models
        if any(p in model.lower() for p in ("claude", "anthropic")):
            try:
                from researchclaw.llm.anthropic_adapter import AnthropicAdapter

                client._anthropic = AnthropicAdapter(  # type: ignore[attr-defined]
                    api_key=api_key,
                    model=model,
                )
            except (ImportError, Exception):  # noqa: BLE001
                pass

        response = client.chat(
            [{"role": "user", "content": "Reply with OK"}],
            max_tokens=10,
        )
        if response and response.content:
            return CheckResult(
                name="ahvs_llm_connectivity",
                status="pass",
                detail=f"LLM reachable (model={model})",
            )
        return CheckResult(
            name="ahvs_llm_connectivity",
            status="fail",
            detail="LLM returned empty response",
            fix="Check your API key and model name",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM connectivity check failed: %s", exc)
        return CheckResult(
            name="ahvs_llm_connectivity",
            status="fail",
            detail=f"LLM connectivity failed: {exc}",
            fix="Check your API key, model name, and network connectivity",
        )


def _check_llm_acp(ahvs_config: object | None) -> CheckResult:
    """ACP-specific preflight: verify acpx binary and agent CLI are available."""
    try:
        from researchclaw.llm.acp_client import ACPClient, ACPConfig

        if ahvs_config is not None:
            acp_cfg = ACPConfig(
                agent=getattr(ahvs_config, "acp_agent", "claude"),
                cwd=getattr(ahvs_config, "acp_cwd", "."),
                acpx_command=getattr(ahvs_config, "acpx_command", ""),
                session_name=getattr(ahvs_config, "acp_session_name", "researchclaw-ahvs"),
                timeout_sec=getattr(ahvs_config, "acp_timeout_sec", 1800),
            )
        else:
            acp_cfg = ACPConfig()

        client = ACPClient(acp_cfg)
        ok, detail = client.preflight()
        if ok:
            return CheckResult(
                name="ahvs_llm_connectivity",
                status="pass",
                detail=f"ACP agent ready: {detail}",
            )
        return CheckResult(
            name="ahvs_llm_connectivity",
            status="fail",
            detail=f"ACP preflight failed: {detail}",
            fix="Install acpx (npm install -g acpx) and ensure the agent CLI is on PATH",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("ACP connectivity check failed: %s", exc)
        return CheckResult(
            name="ahvs_llm_connectivity",
            status="fail",
            detail=f"ACP connectivity check failed: {exc}",
            fix="Install acpx (npm install -g acpx) and ensure the agent CLI is on PATH",
        )


def run_ahvs_preflight(
    baseline_path: Path,
    repo_path: Path,
    regression_guard_path: Path | None = None,
    hypothesis_types: list[str] | None = None,
    llm_api_key: str = "",
    llm_model: str = "",
    llm_base_url: str = "",
    skip_llm_check: bool = False,
    llm_provider: str = "",
    ahvs_config: object | None = None,
) -> DoctorReport:
    """Run AHVS pre-flight checks.

    Args:
        baseline_path: Path to .ahvs/baseline_metric.json
        repo_path: Root of the target repository
        regression_guard_path: Optional path to regression_guard.sh
        hypothesis_types: If provided, also check required tools for these types.
            Pass None for the minimal setup check (before hypothesis selection).
        skip_llm_check: If True, skip LLM connectivity check.  Used by the
            Stage 4 secondary preflight where connectivity was already verified
            at Stage 1 — avoids manufacturing a false failure when LLM
            credentials are not re-passed.
        llm_provider: Provider string (e.g. "anthropic", "acp").  Passed to
            ``check_llm_connectivity`` for provider-aware behaviour.
        ahvs_config: Optional AHVSConfig, forwarded to ``check_llm_connectivity``
            for ACP client construction.
    """
    from datetime import datetime, timezone

    checks: list[CheckResult] = [
        check_baseline_metric(baseline_path),
        check_clean_branch(repo_path),
    ]

    commit_check = check_baseline_commit(baseline_path)
    if commit_check is not None:
        checks.append(commit_check)

    # Always run LLM check at setup (Stage 1).  Skip at Stage 4 secondary
    # preflight where we only care about tool availability.
    if not skip_llm_check:
        checks.append(check_llm_connectivity(
            llm_api_key, llm_model, llm_base_url,
            provider=llm_provider, ahvs_config=ahvs_config,
        ))

    if regression_guard_path is not None:
        checks.append(check_regression_guard(regression_guard_path))

    if hypothesis_types:
        required_tools: set[str] = set()
        for h_type in hypothesis_types:
            required_tools.update(HYPOTHESIS_TOOL_REQUIREMENTS.get(h_type, []))
        for tool in sorted(required_tools):
            checks.append(check_tool(tool))

    overall = "fail" if any(c.status == "fail" for c in checks) else "pass"
    return DoctorReport(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        checks=checks,
        overall=overall,
    )
