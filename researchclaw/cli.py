"""ResearchClaw CLI — run the 23-stage autonomous research pipeline."""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import cast

from researchclaw.adapters import AdapterBundle
from researchclaw.config import (
    CONFIG_SEARCH_ORDER,
    EXAMPLE_CONFIG,
    RCConfig,
    resolve_config_path,
)
from researchclaw.health import print_doctor_report, run_doctor, write_doctor_report


def _resolve_config_or_exit(args: argparse.Namespace) -> Path | None:
    """Resolve config path from args, printing helpful errors on failure.

    Returns the resolved Path on success, or None if the config cannot be found
    (after printing an error message to stderr).
    """
    path = resolve_config_path(getattr(args, "config", None))
    if path is not None and not path.exists():
        print(f"Error: config file not found: {path}", file=sys.stderr)
        return None
    if path is None:
        search_list = ", ".join(CONFIG_SEARCH_ORDER)
        print(
            f"Error: no config file found (searched: {search_list}).\n"
            f"Run 'researchclaw init' to create one from the example template.",
            file=sys.stderr,
        )
        return None
    return path


def _generate_run_id(topic: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    topic_hash = hashlib.sha256(topic.encode()).hexdigest()[:6]
    return f"rc-{ts}-{topic_hash}"


def cmd_run(args: argparse.Namespace) -> int:
    resolved = _resolve_config_or_exit(args)
    if resolved is None:
        return 1
    config_path = resolved
    topic = cast(str | None, args.topic)
    output = cast(str | None, args.output)
    from_stage_name = cast(str | None, args.from_stage)
    auto_approve = cast(bool, args.auto_approve)
    skip_preflight = cast(bool, args.skip_preflight)
    resume = cast(bool, args.resume)
    skip_noncritical = cast(bool, args.skip_noncritical_stage)

    kb_root_path = None
    config = RCConfig.load(config_path, check_paths=False)

    if topic:
        import dataclasses

        new_research = dataclasses.replace(config.research, topic=topic)
        config = dataclasses.replace(config, research=new_research)

    # --- LLM Preflight ---
    if not skip_preflight:
        from researchclaw.llm import create_llm_client

        client = create_llm_client(config)
        print("Preflight check...", end=" ", flush=True)
        ok, msg = client.preflight()
        if ok:
            print(msg)
        else:
            print(f"FAILED — {msg}", file=sys.stderr)
            return 1

    run_id = _generate_run_id(config.research.topic)
    run_dir = Path(output or f"artifacts/{run_id}")
    run_dir.mkdir(parents=True, exist_ok=True)

    if config.knowledge_base.root:
        kb_root_path = Path(config.knowledge_base.root)
        kb_root_path.mkdir(parents=True, exist_ok=True)

    adapters = AdapterBundle()

    from researchclaw.pipeline.runner import execute_pipeline, read_checkpoint
    from researchclaw.pipeline.stages import Stage

    # --- Determine start stage ---
    from_stage = Stage.TOPIC_INIT
    if from_stage_name:
        from_stage = Stage[from_stage_name.upper()]
    elif resume:
        resumed = read_checkpoint(run_dir)
        if resumed is not None:
            from_stage = resumed
            print(f"Resuming from checkpoint: Stage {int(from_stage)}: {from_stage.name}")

    print(f"ResearchClaw v0.1.0 — Starting pipeline")
    print(f"  Run ID:  {run_id}")
    print(f"  Topic:   {config.research.topic}")
    print(f"  Output:  {run_dir}")
    print(f"  Mode:    {config.experiment.mode}")
    print(f"  From:    Stage {int(from_stage)}: {from_stage.name}")
    print()

    results = execute_pipeline(
        run_dir=run_dir,
        run_id=run_id,
        config=config,
        adapters=adapters,
        from_stage=from_stage,
        auto_approve_gates=auto_approve,
        skip_noncritical=skip_noncritical,
        kb_root=kb_root_path,
    )

    done = sum(1 for r in results if r.status.value == "done")
    failed = sum(1 for r in results if r.status.value == "failed")
    print(f"\nPipeline complete: {done}/{len(results)} stages done, {failed} failed")
    return 0 if failed == 0 else 1


def cmd_validate(args: argparse.Namespace) -> int:
    from researchclaw.config import validate_config
    import yaml

    resolved = _resolve_config_or_exit(args)
    if resolved is None:
        return 1
    config_path = resolved
    no_check_paths = cast(bool, args.no_check_paths)

    with config_path.open(encoding="utf-8") as f:
        loaded = cast(object, yaml.safe_load(f))

    if loaded is None:
        data: dict[str, object] = {}
    elif isinstance(loaded, dict):
        loaded_map = cast(Mapping[object, object], loaded)
        data = {str(key): value for key, value in loaded_map.items()}
    else:
        print("Config validation FAILED:")
        print("  Error: Config root must be a mapping")
        return 1

    result = validate_config(data, check_paths=not no_check_paths)
    if result.ok:
        print("Config validation passed")
        for w in result.warnings:
            print(f"  Warning: {w}")
        return 0
    else:
        print("Config validation FAILED:")
        for e in result.errors:
            print(f"  Error: {e}")
        return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    resolved = _resolve_config_or_exit(args)
    if resolved is None:
        return 1
    config_path = resolved
    output = cast(str | None, args.output)

    report = run_doctor(config_path)
    print_doctor_report(report)
    if output:
        write_doctor_report(report, Path(output))
    return 0 if report.overall == "pass" else 1

_PROVIDER_CHOICES = {
    "1": ("openai", "OPENAI_API_KEY"),
    "2": ("openrouter", "OPENROUTER_API_KEY"),
    "3": ("deepseek", "DEEPSEEK_API_KEY"),
    "4": ("acp", ""),
}

_PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com/v1",
}

_PROVIDER_MODELS = {
    "openai": ("gpt-4o", ["gpt-4.1", "gpt-4o-mini"]),
    "openrouter": (
        "anthropic/claude-3.5-sonnet",
        ["google/gemini-pro-1.5", "meta-llama/llama-3.1-70b-instruct"],
    ),
    "deepseek": ("deepseek-chat", ["deepseek-reasoner"]),
}


def cmd_init(args: argparse.Namespace) -> int:
    force = cast(bool, args.force)
    dest = Path("config.arc.yaml")

    if dest.exists() and not force:
        print(f"{dest} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    # Look for the example config: first in repo root (relative to package),
    # then in CWD (for development), then bundled in the package data dir.
    _candidates = [
        Path(__file__).resolve().parent.parent / EXAMPLE_CONFIG,  # repo root
        Path.cwd() / EXAMPLE_CONFIG,                              # cwd fallback
        Path(__file__).resolve().parent / "data" / EXAMPLE_CONFIG, # packaged
    ]
    example = next((p for p in _candidates if p.exists()), None)
    if example is None:
        print(
            f"Error: example config not found.\n"
            f"Searched: {', '.join(str(c) for c in _candidates)}",
            file=sys.stderr,
        )
        return 1

    # Interactive provider prompt (TTY only, else default to openai)
    choice = "1"
    if sys.stdin.isatty():
        print("Select LLM provider:")
        print("  1) openai       (requires OPENAI_API_KEY)")
        print("  2) openrouter   (requires OPENROUTER_API_KEY)")
        print("  3) deepseek     (requires DEEPSEEK_API_KEY)")
        print("  4) acp          (local AI agent — no API key needed)")
        try:
            raw = input("Choice [1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            raw = ""
        if raw in _PROVIDER_CHOICES:
            choice = raw

    provider, api_key_env = _PROVIDER_CHOICES[choice]

    content = example.read_text(encoding="utf-8")

    # String-based replacement to preserve YAML comments
    content = content.replace(
        'provider: "openai-compatible"', f'provider: "{provider}"'
    )

    if provider == "acp":
        # ACP doesn't need base_url or api_key_env
        content = content.replace(
            'base_url: "https://api.openai.com/v1"', 'base_url: ""'
        )
        content = content.replace('api_key_env: "OPENAI_API_KEY"', 'api_key_env: ""')
    else:
        base_url = _PROVIDER_URLS.get(provider, "https://api.openai.com/v1")
        content = content.replace(
            'base_url: "https://api.openai.com/v1"', f'base_url: "{base_url}"'
        )
        if api_key_env:
            content = content.replace(
                'api_key_env: "OPENAI_API_KEY"', f'api_key_env: "{api_key_env}"'
            )

    if provider in _PROVIDER_MODELS:
        primary, fallbacks = _PROVIDER_MODELS[provider]
        content = content.replace('primary_model: "gpt-4o"', f'primary_model: "{primary}"')
        # Replace fallback models block
        old_fallbacks = '  fallback_models:\n    - "gpt-4.1"\n    - "gpt-4o-mini"'
        new_fallbacks = "  fallback_models:\n" + "".join(
            f'    - "{m}"\n' for m in fallbacks
        )
        content = content.replace(old_fallbacks, new_fallbacks.rstrip("\n"))

    dest.write_text(content, encoding="utf-8")
    print(f"Created {dest} (provider: {provider})")

    if provider == "acp":
        print("\nNext steps:")
        print("  1. Ensure your ACP agent is installed and on PATH")
        print("  2. Edit config.arc.yaml to set llm.acp.agent if needed")
        print("  3. Run: researchclaw doctor")
    else:
        env_var = api_key_env or "OPENAI_API_KEY"
        print(f"\nNext steps:")
        print(f"  1. Export your API key: export {env_var}=sk-...")
        print("  2. Edit config.arc.yaml to customize your settings")
        print("  3. Run: researchclaw doctor")

    return 0


def cmd_ahvs(args: argparse.Namespace) -> int:
    """Run one AHVS hypothesis-validation cycle."""
    from pathlib import Path as _Path
    from researchclaw.ahvs.config import AHVSConfig
    from researchclaw.ahvs.runner import execute_ahvs_cycle, read_ahvs_checkpoint
    from researchclaw.ahvs.stages import AHVSStage, StageStatus

    repo_path = _Path(args.repo).resolve()
    if not repo_path.exists():
        print(f"Error: repo path does not exist: {repo_path}", file=sys.stderr)
        return 1

    config = AHVSConfig(
        repo_path=repo_path,
        question=args.question,
        max_hypotheses=args.max_hypotheses,
        regression_guard_path=_Path(args.regression_guard).resolve() if args.regression_guard else None,
        skill_registry_path=_Path(args.skill_registry).resolve() if args.skill_registry else None,
        prompts_override_path=_Path(args.prompts).resolve() if args.prompts else None,
        llm_provider=args.provider or "anthropic",
        llm_model=args.model or "claude-opus-4-6",
        llm_api_key_env=args.api_key_env or "ANTHROPIC_API_KEY",
        run_dir=_Path(args.run_dir).resolve() if args.run_dir else None,
        acp_agent=getattr(args, "acp_agent", "claude") or "claude",
        acpx_command=getattr(args, "acpx_command", "") or "",
        acp_session_name=getattr(args, "acp_session_name", "researchclaw-ahvs") or "researchclaw-ahvs",
        acp_timeout_sec=getattr(args, "acp_timeout_sec", 1800) or 1800,
    )

    from_stage: AHVSStage | None = None
    if args.from_stage:
        try:
            from_stage = AHVSStage[args.from_stage.upper()]
        except KeyError:
            valid = [s.name for s in AHVSStage]
            print(
                f"Error: unknown stage '{args.from_stage}'. Valid: {', '.join(valid)}",
                file=sys.stderr,
            )
            return 1
    elif args.resume:
        # Auto-detect latest cycle dir if --run-dir was not provided
        if not args.run_dir:
            cycles_root = repo_path / ".ahvs" / "cycles"
            if cycles_root.is_dir():
                cycle_dirs = sorted(
                    [d for d in cycles_root.iterdir() if d.is_dir()],
                    key=lambda d: d.name,
                    reverse=True,
                )
                if cycle_dirs:
                    config.run_dir = cycle_dirs[0]
                    print(f"[AHVS] Auto-detected latest cycle: {cycle_dirs[0].name}")
                else:
                    print(
                        "Error: --resume requires a previous cycle, but no cycles found "
                        f"under {cycles_root}",
                        file=sys.stderr,
                    )
                    return 1
            else:
                print(
                    "Error: --resume requires a previous cycle, but "
                    f"{cycles_root} does not exist. Run a cycle first or pass --run-dir.",
                    file=sys.stderr,
                )
                return 1

        resumed = read_ahvs_checkpoint(config.run_dir)
        if resumed is not None:
            # Advance one stage past the last completed checkpoint
            from researchclaw.ahvs.stages import AHVS_NEXT_STAGE
            nxt = AHVS_NEXT_STAGE.get(resumed)
            if nxt is not None:
                from_stage = nxt
                print(f"[AHVS] Resuming from checkpoint: {nxt.name}")
            else:
                print("[AHVS] Checkpoint shows cycle already complete.")
                return 0
        else:
            print(
                f"Error: no checkpoint found in {config.run_dir}. "
                "Cannot resume — start a new cycle instead.",
                file=sys.stderr,
            )
            return 1

    results = execute_ahvs_cycle(
        config,
        auto_approve=args.auto_approve,
        from_stage=from_stage,
    )

    failed = [r for r in results if r.status != StageStatus.DONE]
    return 0 if not failed else 1


def cmd_report(args: argparse.Namespace) -> int:
    from researchclaw.report import generate_report, write_report

    run_dir = Path(cast(str, args.run_dir))
    output = cast(str | None, args.output)

    try:
        report = generate_report(run_dir)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(report)
    if output:
        write_report(run_dir, Path(output))
        print(f"\nReport written to {output}")
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="researchclaw",
        description="ResearchClaw — Autonomous Research Pipeline",
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run the 23-stage research pipeline")
    _ = run_p.add_argument("--topic", "-t", help="Override research topic")
    _ = run_p.add_argument(
        "--config", "-c", default=None,
        help="Config file (default: auto-detect config.arc.yaml or config.yaml)",
    )
    _ = run_p.add_argument("--output", "-o", help="Output directory")
    _ = run_p.add_argument(
        "--from-stage", help="Start from a specific stage (e.g. PAPER_OUTLINE)"
    )
    _ = run_p.add_argument(
        "--auto-approve", action="store_true", help="Auto-approve gate stages"
    )
    _ = run_p.add_argument(
        "--skip-preflight", action="store_true", help="Skip LLM preflight check"
    )
    _ = run_p.add_argument(
        "--resume", action="store_true", help="Resume from last checkpoint"
    )
    _ = run_p.add_argument(
        "--skip-noncritical-stage", action="store_true",
        help="Skip noncritical stages on failure instead of aborting"
    )
    val_p = sub.add_parser("validate", help="Validate config file")
    _ = val_p.add_argument(
        "--config", "-c", default=None,
        help="Config file (default: auto-detect config.arc.yaml or config.yaml)",
    )
    _ = val_p.add_argument(
        "--no-check-paths", action="store_true", help="Skip path existence checks"
    )

    doc_p = sub.add_parser("doctor", help="Check environment and configuration health")
    _ = doc_p.add_argument(
        "--config", "-c", default=None,
        help="Config file (default: auto-detect config.arc.yaml or config.yaml)",
    )
    _ = doc_p.add_argument("--output", "-o", help="Write JSON report to file")

    init_p = sub.add_parser("init", help="Create config.arc.yaml from example template")
    _ = init_p.add_argument(
        "--force", action="store_true", help="Overwrite existing config.arc.yaml"
    )

    rpt_p = sub.add_parser("report", help="Generate human-readable run report")
    _ = rpt_p.add_argument(
        "--run-dir", required=True, help="Path to run artifacts directory"
    )
    _ = rpt_p.add_argument("--output", "-o", help="Write report to file")

    ahvs_p = sub.add_parser(
        "ahvs",
        help="Run an AHVS hypothesis-validation cycle on a target repo",
    )
    _ = ahvs_p.add_argument(
        "--repo", "-r", required=True,
        help="Path to target repository to improve",
    )
    _ = ahvs_p.add_argument(
        "--question", "-q", required=True,
        help="Cycle question (e.g. 'How can we improve answer_relevance by 5%%?')",
    )
    _ = ahvs_p.add_argument(
        "--max-hypotheses", type=int, default=3,
        help="Maximum hypotheses to generate per cycle (default: 3, hard cap: 5)",
    )
    _ = ahvs_p.add_argument(
        "--regression-guard",
        help="Path to regression guard shell script (optional)",
    )
    _ = ahvs_p.add_argument(
        "--auto-approve", action="store_true",
        help="Skip interactive gate and run all generated hypotheses",
    )
    _ = ahvs_p.add_argument(
        "--from-stage",
        help="Start from a specific stage (e.g. AHVS_HYPOTHESIS_GEN)",
    )
    _ = ahvs_p.add_argument(
        "--resume", action="store_true",
        help="Resume from the last written checkpoint in the cycle directory",
    )
    _ = ahvs_p.add_argument(
        "--skill-registry",
        help="Path to custom skill registry YAML file (optional)",
    )
    _ = ahvs_p.add_argument(
        "--prompts",
        help="Path to AHVS prompts override YAML file (optional)",
    )
    _ = ahvs_p.add_argument(
        "--model", default="claude-opus-4-6",
        help="LLM model ID (default: claude-opus-4-6)",
    )
    _ = ahvs_p.add_argument(
        "--api-key-env", default="ANTHROPIC_API_KEY",
        help="Environment variable holding the LLM API key (default: ANTHROPIC_API_KEY)",
    )
    _ = ahvs_p.add_argument(
        "--provider", default="anthropic",
        choices=["anthropic", "openai", "openai-compatible", "openrouter", "deepseek", "acp"],
        help="LLM provider for AHVS orchestration (default: anthropic). Use 'acp' for local agent (Claude Code, Codex)",
    )
    _ = ahvs_p.add_argument(
        "--acp-agent", default="claude",
        help="ACP agent CLI name (default: claude). Only used with --provider acp",
    )
    _ = ahvs_p.add_argument(
        "--acpx-command", default="",
        help="Path to acpx binary (auto-detected if omitted). Only used with --provider acp",
    )
    _ = ahvs_p.add_argument(
        "--acp-session-name", default="researchclaw-ahvs",
        help="ACP session name (default: researchclaw-ahvs). Only used with --provider acp",
    )
    _ = ahvs_p.add_argument(
        "--acp-timeout", type=int, default=1800, dest="acp_timeout_sec",
        help="ACP per-prompt timeout in seconds (default: 1800). Only used with --provider acp",
    )
    _ = ahvs_p.add_argument(
        "--run-dir",
        help="Override cycle output directory (default: <repo>/.ahvs/cycles/<timestamp>)",
    )

    args = parser.parse_args(argv)

    command = cast(str | None, args.command)

    if command == "run":
        return cmd_run(args)
    elif command == "validate":
        return cmd_validate(args)
    elif command == "doctor":
        return cmd_doctor(args)
    elif command == "init":
        return cmd_init(args)
    elif command == "report":
        return cmd_report(args)
    elif command == "ahvs":
        return cmd_ahvs(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
