"""HypothesisWorktree — manages a git worktree for one AHVS hypothesis.

Each hypothesis gets a detached worktree at repo HEAD where CodeAgent-generated
files are applied, the eval_command is run, and a diff/patch is captured.
The worktree is cleaned up unless it produced the best improvement.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvalResult:
    """Outcome of running eval_command inside a hypothesis worktree."""

    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float
    timed_out: bool = False


class HypothesisWorktree:
    """Lifecycle manager for a single hypothesis git worktree."""

    def __init__(self, repo_path: Path, worktree_path: Path) -> None:
        self.repo_path = repo_path
        self.worktree_path = worktree_path
        self._created = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self) -> None:
        """Create a detached worktree at repo HEAD."""
        self.worktree_path.parent.mkdir(parents=True, exist_ok=True)
        result = self._run_git(
            ["worktree", "add", "--detach", str(self.worktree_path)],
            cwd=self.repo_path,
        )
        if result is None or result.returncode != 0:
            stderr = result.stderr if result else "unknown error"
            raise RuntimeError(f"Failed to create worktree: {stderr}")
        self._created = True
        logger.info("Created worktree at %s", self.worktree_path)

    def apply_files(self, files: dict[str, str]) -> list[Path]:
        """Write CodeAgent-generated files into the worktree.

        *files* maps repo-relative paths to file contents.
        Returns list of absolute paths written.
        """
        written: list[Path] = []
        for relpath, content in files.items():
            dest = self.worktree_path / relpath
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            written.append(dest)
        return written

    def run_eval_command(
        self, cmd: str, timeout: int = 300
    ) -> EvalResult:
        """Run *cmd* (shell) inside the worktree and return the result."""
        t0 = time.monotonic()
        try:
            r = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.worktree_path),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            elapsed = time.monotonic() - t0
            return EvalResult(
                returncode=r.returncode,
                stdout=r.stdout,
                stderr=r.stderr,
                elapsed_sec=round(elapsed, 2),
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - t0
            return EvalResult(
                returncode=-1,
                stdout="",
                stderr=f"eval_command timed out after {timeout}s",
                elapsed_sec=round(elapsed, 2),
                timed_out=True,
            )

    def capture_diff(self) -> str:
        """Return `git diff` output from the worktree (staged + unstaged)."""
        # Stage everything so diff captures new files too
        self._run_git(["add", "-A"], cwd=self.worktree_path)
        result = self._run_git(
            ["diff", "--cached"],
            cwd=self.worktree_path,
        )
        if result is None:
            return ""
        return result.stdout

    def save_patch(self, dest: Path) -> Path:
        """Write the worktree diff to *dest* as a .patch file."""
        diff = self.capture_diff()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(diff, encoding="utf-8")
        logger.info("Saved patch (%d bytes) to %s", len(diff), dest)
        return dest

    def cleanup(self) -> None:
        """Remove the worktree from the main repo."""
        if not self._created:
            return
        result = self._run_git(
            ["worktree", "remove", "--force", str(self.worktree_path)],
            cwd=self.repo_path,
        )
        if result and result.returncode == 0:
            logger.info("Removed worktree %s", self.worktree_path)
        else:
            logger.warning(
                "Failed to remove worktree %s — manual cleanup may be needed",
                self.worktree_path,
            )
        self._created = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_git(
        args: list[str], cwd: Path
    ) -> subprocess.CompletedProcess[str] | None:
        try:
            logger.debug("Running git command: git %s (cwd=%s)", " ".join(args), cwd)
            return subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Git operation failed (%s): %s", " ".join(args), exc)
            return None
