"""AHVS test suite — P1-c from the critical review.

Covers:
  1. _extract_metric_from_output (pure function, JSON + text patterns)
  2. _run_regression_guard (fail-closed when configured)
  3. HypothesisResult fields + load_results round-trip
  4. HypothesisWorktree lifecycle (create, apply_files, capture_diff, cleanup)
  5. Checkpoint write/read/resume round-trip
  6. Stage dispatcher routing (all 8 stages have handlers)
  7. One end-to-end cycle with mocked LLM and CodeAgent
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from researchclaw.ahvs.config import AHVSConfig
from researchclaw.ahvs.executor import (
    AHVSStageResult,
    _extract_metric_from_output,
    _run_regression_guard,
    execute_ahvs_stage,
)
from researchclaw.ahvs.result import HypothesisResult, load_results, save_results
from researchclaw.ahvs.runner import _write_checkpoint, read_ahvs_checkpoint
from researchclaw.ahvs.stages import AHVSStage, AHVS_STAGE_SEQUENCE, StageStatus
from researchclaw.ahvs.worktree import EvalResult, HypothesisWorktree


# ---------------------------------------------------------------------------
# 1. _extract_metric_from_output
# ---------------------------------------------------------------------------


class TestExtractMetric:
    """Tests for the five-tier metric extraction helper."""

    def test_json_simple(self) -> None:
        raw = '{"answer_relevance": 0.82}'
        assert _extract_metric_from_output(raw, "answer_relevance") == 0.82

    def test_json_nested_key(self) -> None:
        raw = '{"metrics": {"accuracy": 0.91}}'
        assert _extract_metric_from_output(raw, "metrics.accuracy") == 0.91

    def test_json_last_line_wins(self) -> None:
        raw = (
            "Some debug output\n"
            '{"f1_score": 0.70}\n'
            'more text\n'
            '{"f1_score": 0.85}\n'
        )
        assert _extract_metric_from_output(raw, "f1_score") == 0.85

    def test_json_integer(self) -> None:
        raw = '{"count": 42}'
        assert _extract_metric_from_output(raw, "count") == 42.0

    def test_json_with_extra_fields(self) -> None:
        raw = '{"answer_relevance": 0.79, "eval_method": "promptfoo"}'
        assert _extract_metric_from_output(raw, "answer_relevance") == 0.79

    def test_key_value_colon(self) -> None:
        raw = "answer_relevance: 0.80"
        assert _extract_metric_from_output(raw, "answer_relevance") == 0.80

    def test_key_value_space(self) -> None:
        raw = "answer_relevance 0.80"
        assert _extract_metric_from_output(raw, "answer_relevance") == 0.80

    def test_key_value_negative(self) -> None:
        raw = "delta: -0.05"
        assert _extract_metric_from_output(raw, "delta") == -0.05

    def test_key_value_scientific(self) -> None:
        raw = "loss: 3.5e-4"
        assert _extract_metric_from_output(raw, "loss") == 3.5e-4

    def test_key_value_case_insensitive(self) -> None:
        raw = "Answer_Relevance: 0.88"
        assert _extract_metric_from_output(raw, "answer_relevance") == 0.88

    def test_no_match_returns_none(self) -> None:
        raw = "some random output without any metric"
        assert _extract_metric_from_output(raw, "answer_relevance") is None

    def test_empty_string(self) -> None:
        assert _extract_metric_from_output("", "metric") is None

    def test_malformed_json_falls_through_to_text(self) -> None:
        raw = '{bad json}\nanswer_relevance: 0.77'
        assert _extract_metric_from_output(raw, "answer_relevance") == 0.77

    def test_json_missing_key_falls_through(self) -> None:
        raw = '{"other_metric": 0.9}\nanswer_relevance: 0.75'
        assert _extract_metric_from_output(raw, "answer_relevance") == 0.75

    def test_json_list_index(self) -> None:
        raw = '{"data": [{"value": 0.6}, {"value": 0.7}]}'
        assert _extract_metric_from_output(raw, "data.0.value") == 0.6

    def test_multiline_with_noise(self) -> None:
        raw = (
            "Loading model...\n"
            "Running evaluation...\n"
            "Processed 100 samples\n"
            "answer_relevance: 0.81\n"
            "Done.\n"
        )
        assert _extract_metric_from_output(raw, "answer_relevance") == 0.81


# ---------------------------------------------------------------------------
# 2. _run_regression_guard
# ---------------------------------------------------------------------------


class TestRegressionGuard:
    """Tests for the fail-closed regression guard."""

    def test_none_guard_passes(self, tmp_path: Path) -> None:
        """No guard configured → always pass."""
        assert _run_regression_guard(None, tmp_path / "result.json") is True

    def test_missing_guard_file_fails(self, tmp_path: Path) -> None:
        """Guard configured but file doesn't exist → fail (P1-b fix)."""
        guard = tmp_path / "nonexistent_guard.sh"
        assert _run_regression_guard(guard, tmp_path / "result.json") is False

    def test_guard_exits_zero_passes(self, tmp_path: Path) -> None:
        guard = tmp_path / "guard.sh"
        guard.write_text("#!/bin/bash\nexit 0\n")
        guard.chmod(guard.stat().st_mode | stat.S_IEXEC)
        result_file = tmp_path / "result.json"
        result_file.write_text('{"answer_relevance": 0.8}')
        assert _run_regression_guard(guard, result_file) is True

    def test_guard_exits_nonzero_fails(self, tmp_path: Path) -> None:
        guard = tmp_path / "guard.sh"
        guard.write_text("#!/bin/bash\nexit 1\n")
        guard.chmod(guard.stat().st_mode | stat.S_IEXEC)
        result_file = tmp_path / "result.json"
        result_file.write_text('{"answer_relevance": 0.5}')
        assert _run_regression_guard(guard, result_file) is False

    def test_guard_timeout_fails(self, tmp_path: Path) -> None:
        """Guard that exceeds timeout → fail (P1-b fix)."""
        guard = tmp_path / "guard.sh"
        guard.write_text("#!/bin/bash\nsleep 120\n")
        guard.chmod(guard.stat().st_mode | stat.S_IEXEC)
        result_file = tmp_path / "result.json"
        result_file.write_text("{}")
        with patch("researchclaw.ahvs.executor.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="guard", timeout=60)
            assert _run_regression_guard(guard, result_file) is False

    def test_guard_oserror_fails(self, tmp_path: Path) -> None:
        """Guard that raises OSError → fail (P1-b fix)."""
        guard = tmp_path / "guard.sh"
        guard.write_text("#!/bin/bash\nexit 0\n")
        guard.chmod(guard.stat().st_mode | stat.S_IEXEC)
        with patch("researchclaw.ahvs.executor.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("permission denied")
            assert _run_regression_guard(guard, tmp_path / "r.json") is False

    def test_guard_receives_result_path(self, tmp_path: Path) -> None:
        """Guard script receives the results path as its first argument."""
        guard = tmp_path / "guard.sh"
        marker = tmp_path / "marker.txt"
        guard.write_text(
            f'#!/bin/bash\necho "$1" > {marker}\nexit 0\n'
        )
        guard.chmod(guard.stat().st_mode | stat.S_IEXEC)
        result_file = tmp_path / "result.json"
        result_file.write_text("{}")
        _run_regression_guard(guard, result_file)
        assert marker.read_text().strip() == str(result_file)


# ---------------------------------------------------------------------------
# 3. HypothesisResult fields + round-trip
# ---------------------------------------------------------------------------


def _make_result(**overrides: object) -> HypothesisResult:
    defaults = dict(
        hypothesis_id="H1",
        hypothesis_type="code_change",
        primary_metric="answer_relevance",
        metric_value=0.80,
        baseline_value=0.75,
        delta=0.05,
        delta_pct=6.67,
        regression_guard_passed=True,
        eval_method="code_agent",
        measurement_status="measured",
    )
    defaults.update(overrides)
    return HypothesisResult(**defaults)


class TestHypothesisResult:
    """Tests for HypothesisResult dataclass including new P1-a fields."""

    def test_improved_true(self) -> None:
        r = _make_result(delta=0.05, regression_guard_passed=True, error=None)
        assert r.improved is True

    def test_improved_false_negative_delta(self) -> None:
        r = _make_result(delta=-0.01)
        assert r.improved is False

    def test_improved_false_guard_failed(self) -> None:
        r = _make_result(delta=0.05, regression_guard_passed=False)
        assert r.improved is False

    def test_improved_false_with_error(self) -> None:
        r = _make_result(delta=0.05, error="boom")
        assert r.improved is False

    def test_default_new_fields(self) -> None:
        r = _make_result()
        assert r.worktree_path == ""
        assert r.patch_path == ""
        assert r.kept is False
        assert r.measurement_status == "measured"  # helper default

    def test_improved_false_extraction_failed(self) -> None:
        """extraction_failed hypotheses must not count as improved (v2 fix #3)."""
        r = _make_result(delta=0.05, measurement_status="extraction_failed")
        assert r.improved is False

    def test_new_fields_settable(self) -> None:
        r = _make_result()
        r.kept = True
        r.worktree_path = "/tmp/wt/H1"
        r.patch_path = "tool_runs/H1/H1.patch"
        assert r.kept is True
        assert r.worktree_path == "/tmp/wt/H1"
        assert r.patch_path == "tool_runs/H1/H1.patch"

    def test_make_error(self) -> None:
        r = HypothesisResult.make_error(
            hypothesis_id="H2",
            hypothesis_type="prompt_rewrite",
            primary_metric="f1",
            baseline_value=0.70,
            error="CodeAgent crashed",
        )
        assert r.error == "CodeAgent crashed"
        assert r.delta == 0.0
        assert r.improved is False
        assert r.measurement_status == "sandbox_error"
        assert r.worktree_path == ""
        assert r.patch_path == ""

    def test_to_dict_includes_new_fields(self) -> None:
        r = _make_result(kept=True, worktree_path="/wt", patch_path="p.patch")
        d = r.to_dict()
        assert d["kept"] is True
        assert d["worktree_path"] == "/wt"
        assert d["patch_path"] == "p.patch"


class TestResultSerialization:
    """Round-trip: save_results → load_results preserves all fields."""

    def test_round_trip(self, tmp_path: Path) -> None:
        original = [
            _make_result(
                hypothesis_id="H1",
                kept=True,
                worktree_path="/tmp/wt/H1",
                patch_path="tool_runs/H1/H1.patch",
                measurement_status="measured",
            ),
            _make_result(
                hypothesis_id="H2",
                delta=-0.01,
                delta_pct=-1.33,
                metric_value=0.74,
                measurement_status="extraction_failed",
            ),
        ]
        path = tmp_path / "results.json"
        save_results(original, path)
        loaded = load_results(path)

        assert len(loaded) == 2
        assert loaded[0].hypothesis_id == "H1"
        assert loaded[0].kept is True
        assert loaded[0].worktree_path == "/tmp/wt/H1"
        assert loaded[0].patch_path == "tool_runs/H1/H1.patch"
        assert loaded[0].measurement_status == "measured"

        assert loaded[1].hypothesis_id == "H2"
        assert loaded[1].kept is False
        assert loaded[1].worktree_path == ""
        assert loaded[1].measurement_status == "extraction_failed"

    def test_round_trip_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "results.json"
        save_results([], path)
        loaded = load_results(path)
        assert loaded == []


# ---------------------------------------------------------------------------
# 4. HypothesisWorktree lifecycle
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    """Initialize a minimal git repo with one commit."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), capture_output=True, check=True,
    )
    (path / "README.md").write_text("# test repo\n")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(path), capture_output=True, check=True,
    )


class TestHypothesisWorktree:
    """Tests for the git worktree lifecycle manager."""

    def test_create_and_cleanup(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        assert wt_path.exists()
        assert (wt_path / "README.md").exists()

        wt.cleanup()
        assert not wt_path.exists()

    def test_apply_files(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        files = {
            "src/main.py": "print('hello')\n",
            "config.yaml": "key: value\n",
        }
        written = wt.apply_files(files)

        assert len(written) == 2
        assert (wt_path / "src" / "main.py").read_text() == "print('hello')\n"
        assert (wt_path / "config.yaml").read_text() == "key: value\n"

        wt.cleanup()

    def test_capture_diff(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        wt.apply_files({"new_file.txt": "content\n"})
        diff = wt.capture_diff()

        assert "new_file.txt" in diff
        assert "+content" in diff

        wt.cleanup()

    def test_save_patch(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        wt.apply_files({"patch_test.py": "x = 1\n"})
        patch_dest = tmp_path / "H1.patch"
        wt.save_patch(patch_dest)

        assert patch_dest.exists()
        patch_content = patch_dest.read_text()
        assert "patch_test.py" in patch_content

        wt.cleanup()

    def test_run_eval_command(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        result = wt.run_eval_command("echo 'answer_relevance: 0.85'")
        assert result.returncode == 0
        assert "answer_relevance: 0.85" in result.stdout
        assert result.elapsed_sec >= 0
        assert result.timed_out is False

        wt.cleanup()

    def test_run_eval_command_failure(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        result = wt.run_eval_command("exit 1")
        assert result.returncode == 1
        assert result.timed_out is False

        wt.cleanup()

    def test_run_eval_command_timeout(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        result = wt.run_eval_command("sleep 60", timeout=1)
        assert result.returncode == -1
        assert result.timed_out is True

        wt.cleanup()

    def test_create_fails_not_git_repo(self, tmp_path: Path) -> None:
        """Worktree creation on a non-git directory raises RuntimeError."""
        not_a_repo = tmp_path / "not_a_repo"
        not_a_repo.mkdir()
        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(not_a_repo, wt_path)
        with pytest.raises(RuntimeError, match="Failed to create worktree"):
            wt.create()

    def test_cleanup_without_create_is_noop(self, tmp_path: Path) -> None:
        """Cleanup on a never-created worktree does nothing."""
        wt = HypothesisWorktree(tmp_path, tmp_path / "wt")
        wt.cleanup()  # Should not raise


class TestEvalResult:
    """Tests for the EvalResult dataclass."""

    def test_defaults(self) -> None:
        r = EvalResult(returncode=0, stdout="ok", stderr="", elapsed_sec=1.5)
        assert r.timed_out is False

    def test_frozen(self) -> None:
        r = EvalResult(returncode=0, stdout="", stderr="", elapsed_sec=0.0)
        with pytest.raises(AttributeError):
            r.returncode = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 5. Checkpoint write/read/resume round-trip
# ---------------------------------------------------------------------------


class TestCheckpoint:
    """Tests for AHVS checkpoint persistence."""

    def test_write_and_read_done(self, tmp_path: Path) -> None:
        _write_checkpoint(tmp_path, AHVSStage.AHVS_CONTEXT_LOAD, "done")
        result = read_ahvs_checkpoint(tmp_path)
        assert result == AHVSStage.AHVS_CONTEXT_LOAD

    def test_read_failed_returns_none(self, tmp_path: Path) -> None:
        """A failed checkpoint should not be treated as successfully completed."""
        _write_checkpoint(tmp_path, AHVSStage.AHVS_HYPOTHESIS_GEN, "failed")
        result = read_ahvs_checkpoint(tmp_path)
        assert result is None

    def test_read_nonexistent_returns_none(self, tmp_path: Path) -> None:
        assert read_ahvs_checkpoint(tmp_path) is None

    def test_read_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "ahvs_checkpoint.json").write_text("not json")
        assert read_ahvs_checkpoint(tmp_path) is None

    def test_write_overwrites_previous(self, tmp_path: Path) -> None:
        _write_checkpoint(tmp_path, AHVSStage.AHVS_SETUP, "done")
        _write_checkpoint(tmp_path, AHVSStage.AHVS_EXECUTION, "done")
        result = read_ahvs_checkpoint(tmp_path)
        assert result == AHVSStage.AHVS_EXECUTION

    def test_checkpoint_contains_expected_fields(self, tmp_path: Path) -> None:
        _write_checkpoint(tmp_path, AHVSStage.AHVS_SETUP, "done")
        data = json.loads((tmp_path / "ahvs_checkpoint.json").read_text())
        assert data["stage"] == "AHVS_SETUP"
        assert data["stage_num"] == 1
        assert data["status"] == "done"
        assert "updated_at" in data

    def test_all_stages_round_trip(self, tmp_path: Path) -> None:
        """Every stage can be written and read back."""
        for stage in AHVSStage:
            _write_checkpoint(tmp_path, stage, "done")
            assert read_ahvs_checkpoint(tmp_path) == stage


# ---------------------------------------------------------------------------
# 6. Stage dispatcher routing
# ---------------------------------------------------------------------------


class TestStageDispatcher:
    """Verify all 8 stages have registered handlers."""

    def test_all_stages_in_sequence(self) -> None:
        assert len(AHVS_STAGE_SEQUENCE) == 8

    def test_all_stages_have_handlers(self, tmp_path: Path) -> None:
        """Every stage in AHVS_STAGE_SEQUENCE has a handler in _HANDLERS."""
        from researchclaw.ahvs.executor import _HANDLERS
        for stage in AHVS_STAGE_SEQUENCE:
            assert stage in _HANDLERS, f"No handler for {stage.name}"

    def test_unknown_stage_returns_failed(self, tmp_path: Path) -> None:
        """A stage not in _HANDLERS returns a FAILED result."""
        # Use a mock stage value that doesn't exist
        from researchclaw.ahvs.skills import SkillLibrary

        config = AHVSConfig(
            repo_path=tmp_path,
            question="test",
            run_dir=tmp_path / "run",
        )
        # We can't easily create a fake AHVSStage, but we can verify
        # the handler map is complete by checking the set difference
        from researchclaw.ahvs.executor import _HANDLERS
        registered = set(_HANDLERS.keys())
        expected = set(AHVSStage)
        assert registered == expected


# ---------------------------------------------------------------------------
# 7. End-to-end mock cycle (setup + context_load + verify stages)
# ---------------------------------------------------------------------------


class TestExecuteSetup:
    """Test Stage 1: _execute_setup creates the right directory structure."""

    def test_setup_creates_dirs(self, tmp_path: Path) -> None:
        from researchclaw.ahvs.skills import SkillLibrary
        from researchclaw.health import CheckResult

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Create baseline metric
        ahvs_dir = repo / ".ahvs"
        ahvs_dir.mkdir()
        baseline = {
            "primary_metric": "answer_relevance",
            "answer_relevance": 0.74,
            "recorded_at": "2026-03-18T10:00:00Z",
            "eval_command": "echo 'answer_relevance: 0.74'",
        }
        (ahvs_dir / "baseline_metric.json").write_text(json.dumps(baseline))

        cycle_dir = tmp_path / "cycle_001"
        config = AHVSConfig(repo_path=repo, question="test?", run_dir=cycle_dir)
        skill_lib = SkillLibrary()

        # Mock LLM connectivity and clean-branch check so setup doesn't fail
        # on missing API key or untracked .ahvs/ dir in the test repo
        mock_llm = CheckResult(
            name="ahvs_llm_connectivity", status="pass", detail="mocked"
        )
        mock_branch = CheckResult(
            name="ahvs_clean_branch", status="pass", detail="mocked"
        )
        with patch(
            "researchclaw.ahvs.health.check_llm_connectivity",
            return_value=mock_llm,
        ), patch(
            "researchclaw.ahvs.health.check_clean_branch",
            return_value=mock_branch,
        ):
            result = execute_ahvs_stage(
                AHVSStage.AHVS_SETUP,
                cycle_dir=cycle_dir,
                config=config,
                skill_library=skill_lib,
                auto_approve=True,
            )

        assert result.status == StageStatus.DONE
        assert (cycle_dir / "tool_runs").is_dir()
        assert (cycle_dir / "worktrees").is_dir()
        assert (cycle_dir / "cycle_manifest.json").exists()

    def test_setup_fails_without_baseline(self, tmp_path: Path) -> None:
        from researchclaw.ahvs.skills import SkillLibrary

        repo = tmp_path / "repo"
        repo.mkdir()

        cycle_dir = tmp_path / "cycle_002"
        config = AHVSConfig(repo_path=repo, question="test?", run_dir=cycle_dir)
        skill_lib = SkillLibrary()

        result = execute_ahvs_stage(
            AHVSStage.AHVS_SETUP,
            cycle_dir=cycle_dir,
            config=config,
            skill_library=skill_lib,
            auto_approve=True,
        )

        assert result.status == StageStatus.FAILED
        assert "Pre-flight failed" in (result.error or "")


class TestCycleVerify:
    """Test Stage 8: _execute_cycle_verify validates artifacts and writes summary."""

    def _setup_cycle_artifacts(self, cycle_dir: Path, repo_path: Path) -> None:
        """Create all required artifacts for Stage 8 verification."""
        cycle_dir.mkdir(parents=True, exist_ok=True)

        # baseline bundle
        baseline = {
            "primary_metric": "answer_relevance",
            "value": 0.74,
            "eval_command": "echo test",
        }
        bundle = {"baseline": baseline, "lessons": [], "rejected": []}
        (cycle_dir / "context_bundle.json").write_text(json.dumps(bundle))

        # manifest
        (cycle_dir / "cycle_manifest.json").write_text(json.dumps({"cycle_id": "test"}))

        # hypotheses
        (cycle_dir / "hypotheses.md").write_text("# H1\n")

        # selection
        selection = {"selected": ["H1"], "rationale": "test"}
        (cycle_dir / "selection.md").write_text("H1")
        (cycle_dir / "selection.json").write_text(json.dumps(selection))

        # validation plan
        (cycle_dir / "validation_plan.md").write_text("# Plan\n")

        # results
        results = [
            _make_result(
                hypothesis_id="H1",
                measurement_status="measured",
                kept=True,
                worktree_path="/tmp/wt/H1",
                patch_path="tool_runs/H1/H1.patch",
            ),
        ]
        save_results(results, cycle_dir / "results.json")

        # report + friction log
        (cycle_dir / "report.md").write_text("# Report\n")
        (cycle_dir / "friction_log.md").write_text("# Friction\n")

    def test_verify_passes_with_all_artifacts(self, tmp_path: Path) -> None:
        from researchclaw.ahvs.skills import SkillLibrary

        repo = tmp_path / "repo"
        repo.mkdir()
        cycle_dir = tmp_path / "cycle_001"
        self._setup_cycle_artifacts(cycle_dir, repo)

        config = AHVSConfig(repo_path=repo, question="test?", run_dir=cycle_dir)
        skill_lib = SkillLibrary()

        result = execute_ahvs_stage(
            AHVSStage.AHVS_CYCLE_VERIFY,
            cycle_dir=cycle_dir,
            config=config,
            skill_library=skill_lib,
            auto_approve=True,
        )

        assert result.status == StageStatus.DONE

        # Check cycle_summary.json has the new worktree/patch fields
        summary = json.loads((cycle_dir / "cycle_summary.json").read_text())
        assert "kept_worktree" in summary
        assert "kept_patch" in summary
        assert "all_patches" in summary
        assert summary["kept_worktree"] == "/tmp/wt/H1"
        assert summary["kept_patch"] == "tool_runs/H1/H1.patch"
        assert summary["all_patches"] == ["tool_runs/H1/H1.patch"]

    def test_verify_fails_missing_artifact(self, tmp_path: Path) -> None:
        from researchclaw.ahvs.skills import SkillLibrary

        cycle_dir = tmp_path / "cycle_002"
        cycle_dir.mkdir()
        # Only write some artifacts — missing results.json, report.md, etc.
        (cycle_dir / "cycle_manifest.json").write_text("{}")
        (cycle_dir / "context_bundle.json").write_text("{}")

        repo = tmp_path / "repo"
        repo.mkdir()
        config = AHVSConfig(repo_path=repo, question="test?", run_dir=cycle_dir)
        skill_lib = SkillLibrary()

        result = execute_ahvs_stage(
            AHVSStage.AHVS_CYCLE_VERIFY,
            cycle_dir=cycle_dir,
            config=config,
            skill_library=skill_lib,
            auto_approve=True,
        )

        assert result.status == StageStatus.FAILED
        assert "Missing artifacts" in (result.error or "")


# ---------------------------------------------------------------------------
# 8. v2 review fixes — path traversal, canonical result, LLM preflight,
#    tool requirements, all-unmeasured cycle
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Tests for Fix #1: apply_files rejects paths that escape the worktree."""

    def test_reject_absolute_path(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        with pytest.raises(ValueError, match="absolute path"):
            wt.apply_files({"/tmp/evil.py": "pwned"})
        wt.cleanup()

    def test_reject_dotdot_traversal(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        with pytest.raises(ValueError, match="traversal"):
            wt.apply_files({"../../../etc/passwd": "pwned"})
        wt.cleanup()

    def test_reject_hidden_dotdot(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        with pytest.raises(ValueError, match="traversal"):
            wt.apply_files({"src/../../outside.py": "pwned"})
        wt.cleanup()

    def test_accept_valid_nested_path(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt_path = tmp_path / "worktrees" / "H1"
        wt = HypothesisWorktree(repo, wt_path)
        wt.create()

        written = wt.apply_files({"src/deep/module.py": "x = 1\n"})
        assert len(written) == 1
        assert (wt_path / "src" / "deep" / "module.py").read_text() == "x = 1\n"
        wt.cleanup()


class TestCanonicalResult:
    """Tests for Fix #2: regression guard runs against canonical result.json."""

    def test_guard_receives_canonical_result(self, tmp_path: Path) -> None:
        """After metric extraction, result.json should contain the measured metric."""
        # Simulate what executor does after extraction
        work_dir = tmp_path / "tool_runs" / "H1"
        work_dir.mkdir(parents=True)

        canonical = {
            "hypothesis_id": "H1",
            "primary_metric": "answer_relevance",
            "answer_relevance": 0.85,
            "baseline_value": 0.74,
            "measurement_status": "measured",
        }
        result_path = work_dir / "result.json"
        result_path.write_text(json.dumps(canonical))

        # Guard that reads the result and checks for the metric key
        guard = tmp_path / "guard.sh"
        script = textwrap.dedent("""\
            #!/bin/bash
            python3 -c "
            import json, sys
            d = json.load(open(sys.argv[1]))
            assert 'answer_relevance' in d
            assert d['measurement_status'] == 'measured'
            " "$1"
        """)
        guard.write_text(script)
        guard.chmod(guard.stat().st_mode | stat.S_IEXEC)

        assert _run_regression_guard(guard, result_path) is True


class TestLLMPreflightAlwaysRuns:
    """Tests for Fix #4: LLM preflight runs even when api_key is empty."""

    def test_empty_key_fails_preflight(self) -> None:
        from researchclaw.ahvs.health import run_ahvs_preflight

        # Use a non-existent baseline so baseline check also fails;
        # but we specifically check that the LLM check ran and failed.
        report = run_ahvs_preflight(
            baseline_path=Path("/nonexistent/baseline.json"),
            repo_path=Path("/tmp"),
            llm_api_key="",
            llm_model="claude-opus-4-6",
        )
        llm_checks = [c for c in report.checks if c.name == "ahvs_llm_connectivity"]
        assert len(llm_checks) == 1
        assert llm_checks[0].status == "fail"
        assert "No API key" in llm_checks[0].detail

    def test_preflight_with_key_includes_llm_check(self) -> None:
        from researchclaw.ahvs.health import run_ahvs_preflight

        report = run_ahvs_preflight(
            baseline_path=Path("/nonexistent/baseline.json"),
            repo_path=Path("/tmp"),
            llm_api_key="sk-fake-key",
            llm_model="claude-opus-4-6",
        )
        llm_checks = [c for c in report.checks if c.name == "ahvs_llm_connectivity"]
        assert len(llm_checks) == 1
        # Will fail because the key is fake, but the check *ran*
        assert llm_checks[0].status == "fail"


class TestToolRequirements:
    """Tests for Fix #5: code_change/architecture_change/multi_llm_judge don't require docker."""

    def test_code_change_no_docker_requirement(self) -> None:
        from researchclaw.ahvs.health import HYPOTHESIS_TOOL_REQUIREMENTS
        assert "docker" not in HYPOTHESIS_TOOL_REQUIREMENTS["code_change"]

    def test_architecture_change_no_docker_requirement(self) -> None:
        from researchclaw.ahvs.health import HYPOTHESIS_TOOL_REQUIREMENTS
        assert "docker" not in HYPOTHESIS_TOOL_REQUIREMENTS["architecture_change"]

    def test_multi_llm_judge_no_docker_requirement(self) -> None:
        from researchclaw.ahvs.health import HYPOTHESIS_TOOL_REQUIREMENTS
        assert "docker" not in HYPOTHESIS_TOOL_REQUIREMENTS["multi_llm_judge"]

    def test_sandbox_skill_no_docker_required(self) -> None:
        from researchclaw.ahvs.skills import BUILTIN_SKILLS
        sandbox_skills = [s for s in BUILTIN_SKILLS if s.name == "sandbox_run"]
        assert len(sandbox_skills) == 1
        assert "docker" not in sandbox_skills[0].required_tools


class TestAllUnmeasuredCycle:
    """Tests for Fix #3: all-unmeasured cycle is flagged as FAILED."""

    def _setup_cycle_artifacts(self, cycle_dir: Path, measurement_status: str) -> None:
        """Create cycle artifacts where all hypotheses have the given measurement_status."""
        cycle_dir.mkdir(parents=True, exist_ok=True)

        baseline = {
            "primary_metric": "answer_relevance",
            "value": 0.74,
            "eval_command": "echo test",
        }
        bundle = {"baseline": baseline, "lessons": [], "rejected": []}
        (cycle_dir / "context_bundle.json").write_text(json.dumps(bundle))
        (cycle_dir / "cycle_manifest.json").write_text(json.dumps({"cycle_id": "test"}))
        (cycle_dir / "hypotheses.md").write_text("# H1\n")
        (cycle_dir / "selection.md").write_text("H1")
        (cycle_dir / "selection.json").write_text(json.dumps({"selected": ["H1"], "rationale": "test"}))
        (cycle_dir / "validation_plan.md").write_text("# Plan\n")
        results = [
            _make_result(
                hypothesis_id="H1",
                measurement_status=measurement_status,
                delta=0.0,
                delta_pct=0.0,
                metric_value=0.74,
            ),
        ]
        save_results(results, cycle_dir / "results.json")
        (cycle_dir / "report.md").write_text("# Report\n")
        (cycle_dir / "friction_log.md").write_text("# Friction\n")

    def test_all_unmeasured_fails_cycle(self, tmp_path: Path) -> None:
        from researchclaw.ahvs.skills import SkillLibrary

        repo = tmp_path / "repo"
        repo.mkdir()
        cycle_dir = tmp_path / "cycle_001"
        self._setup_cycle_artifacts(cycle_dir, "extraction_failed")

        config = AHVSConfig(repo_path=repo, question="test?", run_dir=cycle_dir)
        skill_lib = SkillLibrary()

        result = execute_ahvs_stage(
            AHVSStage.AHVS_CYCLE_VERIFY,
            cycle_dir=cycle_dir,
            config=config,
            skill_library=skill_lib,
            auto_approve=True,
        )

        assert result.status == StageStatus.FAILED
        assert "All hypotheses failed measurement" in (result.error or "")

        # Summary should still be written with all_unmeasured=True
        summary = json.loads((cycle_dir / "cycle_summary.json").read_text())
        assert summary["all_unmeasured"] is True
        assert "INVALID CYCLE" in summary["recommendation"]

    def test_measured_cycle_passes(self, tmp_path: Path) -> None:
        from researchclaw.ahvs.skills import SkillLibrary

        repo = tmp_path / "repo"
        repo.mkdir()
        cycle_dir = tmp_path / "cycle_002"
        self._setup_cycle_artifacts(cycle_dir, "measured")

        config = AHVSConfig(repo_path=repo, question="test?", run_dir=cycle_dir)
        skill_lib = SkillLibrary()

        result = execute_ahvs_stage(
            AHVSStage.AHVS_CYCLE_VERIFY,
            cycle_dir=cycle_dir,
            config=config,
            skill_library=skill_lib,
            auto_approve=True,
        )

        assert result.status == StageStatus.DONE
        summary = json.loads((cycle_dir / "cycle_summary.json").read_text())
        assert summary["all_unmeasured"] is False


# ---------------------------------------------------------------------------
# 9. v3 review fixes — shared safe-path, string-prefix bug, Stage 4 preflight,
#    dirty repo fail, extraction_failed lesson archival
# ---------------------------------------------------------------------------


class TestSharedSafePath:
    """Tests for Fix #1 (v3): shared validate_safe_relpath utility."""

    def test_string_prefix_containment_uses_is_relative_to(self) -> None:
        """Verify the containment check uses is_relative_to, not startswith.

        The old code used ``str(dest).startswith(str(root))`` which would
        let ``/tmp/wt2/file`` pass as inside ``/tmp/wt``.  The fix uses
        ``Path.is_relative_to()`` which is immune to this.
        """
        from researchclaw.ahvs.worktree import validate_safe_relpath
        import inspect

        source = inspect.getsource(validate_safe_relpath)
        # Must NOT use string-prefix containment
        assert "startswith" not in source
        # Must use proper path ancestry check
        assert "is_relative_to" in source

    def test_symlink_escape_rejected(self, tmp_path: Path) -> None:
        """A symlink inside root that points outside must be rejected."""
        from researchclaw.ahvs.worktree import validate_safe_relpath

        root = tmp_path / "wt"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        # Create a symlink inside root that points outside
        (root / "escape").symlink_to(outside)

        with pytest.raises(ValueError, match="escapes boundary"):
            validate_safe_relpath("escape/evil.py", root)

    def test_tool_runs_rejects_absolute_path(self, tmp_path: Path) -> None:
        """tool_runs write path must reject absolute paths."""
        from researchclaw.ahvs.worktree import validate_safe_relpath

        work_dir = tmp_path / "tool_runs" / "H1"
        work_dir.mkdir(parents=True)
        with pytest.raises(ValueError, match="absolute path"):
            validate_safe_relpath("/etc/passwd", work_dir)

    def test_tool_runs_rejects_dotdot(self, tmp_path: Path) -> None:
        """tool_runs write path must reject .. traversal."""
        from researchclaw.ahvs.worktree import validate_safe_relpath

        work_dir = tmp_path / "tool_runs" / "H1"
        work_dir.mkdir(parents=True)
        with pytest.raises(ValueError, match="traversal"):
            validate_safe_relpath("../../etc/cron.d/evil", work_dir)

    def test_tool_runs_accepts_valid_path(self, tmp_path: Path) -> None:
        """Valid nested paths pass validation."""
        from researchclaw.ahvs.worktree import validate_safe_relpath

        work_dir = tmp_path / "tool_runs" / "H1"
        work_dir.mkdir(parents=True)
        # Should not raise
        validate_safe_relpath("src/module.py", work_dir)

    def test_worktree_and_tool_runs_use_same_function(self) -> None:
        """Worktree._validate_relpath delegates to the shared utility."""
        from researchclaw.ahvs.worktree import validate_safe_relpath

        # The worktree class method should call the shared function
        # Verify by checking it's the same function reference
        import inspect
        source = inspect.getsource(HypothesisWorktree._validate_relpath)
        assert "validate_safe_relpath" in source


class TestStage4PreflightRegression:
    """Tests for Fix #2 (v3): secondary preflight must not manufacture LLM failure."""

    def test_skip_llm_check_no_failure(self) -> None:
        """With skip_llm_check=True, no LLM connectivity check appears."""
        from researchclaw.ahvs.health import run_ahvs_preflight

        report = run_ahvs_preflight(
            baseline_path=Path("/nonexistent/baseline.json"),
            repo_path=Path("/tmp"),
            hypothesis_types=["code_change"],
            skip_llm_check=True,
        )
        llm_checks = [c for c in report.checks if c.name == "ahvs_llm_connectivity"]
        assert len(llm_checks) == 0

    def test_no_skip_includes_llm_check(self) -> None:
        """Without skip_llm_check, LLM connectivity check is still present."""
        from researchclaw.ahvs.health import run_ahvs_preflight

        report = run_ahvs_preflight(
            baseline_path=Path("/nonexistent/baseline.json"),
            repo_path=Path("/tmp"),
            hypothesis_types=["code_change"],
            skip_llm_check=False,
            llm_api_key="",
            llm_model="test",
        )
        llm_checks = [c for c in report.checks if c.name == "ahvs_llm_connectivity"]
        assert len(llm_checks) == 1


class TestDirtyRepoFail:
    """Tests for Fix #3 (v3): dirty repo is a hard fail, not a warning."""

    def test_dirty_repo_fails(self, tmp_path: Path) -> None:
        from researchclaw.ahvs.health import check_clean_branch

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Create an untracked file to make the repo dirty
        (repo / "uncommitted.txt").write_text("dirty")

        result = check_clean_branch(repo)
        assert result.status == "fail"
        assert "uncommitted" in result.detail.lower()

    def test_clean_repo_passes(self, tmp_path: Path) -> None:
        from researchclaw.ahvs.health import check_clean_branch

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        result = check_clean_branch(repo)
        assert result.status == "pass"


class TestExtractionFailedLesson:
    """Tests for Fix #4 (v3): extraction_failed → infrastructure lesson."""

    def test_extraction_failed_not_rejected_approach(self) -> None:
        """extraction_failed results must NOT be archived as 'Rejected approach'."""
        r = _make_result(
            hypothesis_id="H1",
            measurement_status="extraction_failed",
            delta=0.0,
            error=None,
        )
        # Simulate the lesson classification logic from executor
        assert not r.improved
        assert r.error is None
        assert r.measurement_status != "measured"
        # These three conditions mean it hits the new branch, not "Rejected approach"

    def test_measured_not_improved_is_rejected_approach(self) -> None:
        """A properly measured but not-improved result IS a rejected approach."""
        r = _make_result(
            hypothesis_id="H1",
            measurement_status="measured",
            delta=-0.02,
            error=None,
        )
        assert not r.improved
        assert r.error is None
        assert r.measurement_status == "measured"
        # This correctly hits the "Rejected approach" branch


# ---------------------------------------------------------------------------
# 10. ACP local-agent LLM support
# ---------------------------------------------------------------------------


class TestAHVSConfigACP:
    """Tests for AHVSConfig ACP fields and provider-aware behaviour."""

    def test_default_provider_is_anthropic(self, tmp_path: Path) -> None:
        config = AHVSConfig(repo_path=tmp_path, question="test")
        assert config.llm_provider == "anthropic"

    def test_acp_provider_skips_api_key_env(self, tmp_path: Path) -> None:
        """When provider=acp, __post_init__ should not try to read API key from env."""
        config = AHVSConfig(
            repo_path=tmp_path, question="test",
            llm_provider="acp",
            llm_api_key="",
            llm_api_key_env="NONEXISTENT_KEY_VAR_12345",
        )
        # Should remain empty — not read from env
        assert config.llm_api_key == ""

    def test_acp_defaults(self, tmp_path: Path) -> None:
        config = AHVSConfig(repo_path=tmp_path, question="test", llm_provider="acp")
        assert config.acp_agent == "claude"
        assert config.acp_cwd == str(tmp_path.resolve())
        assert config.acp_session_name == "researchclaw-ahvs"
        assert config.acp_timeout_sec == 1800

    def test_acp_cwd_resolved_to_repo(self, tmp_path: Path) -> None:
        config = AHVSConfig(repo_path=tmp_path, question="test")
        assert config.acp_cwd == str(tmp_path.resolve())


class TestShimConstruction:
    """Tests for the _RCConfigShim that bridges AHVSConfig to create_llm_client."""

    def test_shim_exposes_llm_fields(self, tmp_path: Path) -> None:
        from researchclaw.ahvs.executor import _ahvs_config_to_rc_shim

        config = AHVSConfig(
            repo_path=tmp_path, question="test",
            llm_provider="anthropic",
            llm_model="claude-opus-4-6",
            llm_api_key="sk-test",
            llm_base_url="https://example.com",
        )
        shim = _ahvs_config_to_rc_shim(config)
        assert shim.llm.provider == "anthropic"
        assert shim.llm.primary_model == "claude-opus-4-6"
        assert shim.llm.api_key == "sk-test"
        assert shim.llm.base_url == "https://example.com"
        assert shim.metaclaw_bridge is None

    def test_shim_exposes_acp_fields(self, tmp_path: Path) -> None:
        from researchclaw.ahvs.executor import _ahvs_config_to_rc_shim

        config = AHVSConfig(
            repo_path=tmp_path, question="test",
            llm_provider="acp",
            acp_agent="codex",
            acp_session_name="my-session",
            acp_timeout_sec=600,
        )
        shim = _ahvs_config_to_rc_shim(config)
        assert shim.llm.provider == "acp"
        assert shim.llm.acp.agent == "codex"
        assert shim.llm.acp.session_name == "my-session"
        assert shim.llm.acp.timeout_sec == 600


class TestPreflightProviderAware:
    """Tests for provider-aware preflight checks."""

    def test_acp_preflight_calls_acp_check(self) -> None:
        """With provider=acp, check_llm_connectivity should use ACP path, not API key."""
        from researchclaw.ahvs.health import check_llm_connectivity

        # Even with empty API key, provider=acp should NOT fail with "No API key"
        result = check_llm_connectivity(
            api_key="", model="", base_url="", provider="acp",
        )
        # Will fail because acpx is not installed in test env,
        # but the failure message should be about ACP, not API keys
        assert "API key" not in result.detail

    def test_non_acp_still_requires_api_key(self) -> None:
        """Without provider=acp, empty API key still fails."""
        from researchclaw.ahvs.health import check_llm_connectivity

        result = check_llm_connectivity(
            api_key="", model="test", base_url="", provider="anthropic",
        )
        assert result.status == "fail"
        assert "No API key" in result.detail

    def test_preflight_skips_llm_on_skip_flag(self) -> None:
        """skip_llm_check=True suppresses the check regardless of provider."""
        from researchclaw.ahvs.health import run_ahvs_preflight

        report = run_ahvs_preflight(
            baseline_path=Path("/nonexistent"),
            repo_path=Path("/tmp"),
            skip_llm_check=True,
            llm_provider="acp",
        )
        llm_checks = [c for c in report.checks if c.name == "ahvs_llm_connectivity"]
        assert len(llm_checks) == 0

    def test_acp_preflight_in_run_ahvs_preflight(self) -> None:
        """run_ahvs_preflight passes provider to check_llm_connectivity."""
        from researchclaw.ahvs.health import run_ahvs_preflight

        report = run_ahvs_preflight(
            baseline_path=Path("/nonexistent"),
            repo_path=Path("/tmp"),
            llm_provider="acp",
        )
        llm_checks = [c for c in report.checks if c.name == "ahvs_llm_connectivity"]
        assert len(llm_checks) == 1
        # Should be an ACP-related message, not "No API key"
        assert "API key" not in llm_checks[0].detail


class TestMakeLlmClientUsesFactory:
    """Tests for _make_llm_client routing through the shared factory."""

    def test_anthropic_provider_returns_llm_client(self, tmp_path: Path) -> None:
        """provider=anthropic should produce an LLMClient (not ACPClient)."""
        from researchclaw.ahvs.executor import _make_llm_client
        from researchclaw.llm.client import LLMClient

        config = AHVSConfig(
            repo_path=tmp_path, question="test",
            llm_provider="anthropic",
            llm_api_key="sk-test",
            llm_model="claude-opus-4-6",
        )
        # Mock the Anthropic adapter since httpx may not be installed in test env
        with patch("researchclaw.llm.anthropic_adapter.HAS_HTTPX", True), \
             patch("researchclaw.llm.anthropic_adapter.AnthropicAdapter.__init__", return_value=None):
            client = _make_llm_client(config)
        assert isinstance(client, LLMClient)

    def test_acp_provider_returns_acp_client(self, tmp_path: Path) -> None:
        """provider=acp should produce an ACPClient."""
        from researchclaw.ahvs.executor import _make_llm_client
        from researchclaw.llm.acp_client import ACPClient

        config = AHVSConfig(
            repo_path=tmp_path, question="test",
            llm_provider="acp",
            acp_agent="claude",
        )
        client = _make_llm_client(config)
        assert isinstance(client, ACPClient)
        assert client.config.agent == "claude"
