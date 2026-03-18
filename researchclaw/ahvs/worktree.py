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


# ---------------------------------------------------------------------------
# Shared path-safety utility (used by both worktree writes and tool_runs writes)
# ---------------------------------------------------------------------------


def validate_safe_relpath(relpath: str, root: Path) -> None:
    """Reject *relpath* if it would escape *root* when joined.

    Checks performed (in order):
    1. Absolute path (e.g. ``/tmp/evil``)
    2. ``..`` component anywhere in the path
    3. Resolved destination is not a descendant of *root*
       (catches symlink escapes and edge cases)

    Uses :meth:`Path.is_relative_to` for the containment check — immune
    to the string-prefix false-positive where ``/tmp/wt2/f`` appears to
    be inside ``/tmp/wt``.

    Raises:
        ValueError: with a descriptive message when the path is unsafe.
    """
    from pathlib import PurePosixPath

    pure = PurePosixPath(relpath)

    if pure.is_absolute():
        raise ValueError(
            f"Refusing absolute path from CodeAgent output: {relpath!r}"
        )

    if ".." in pure.parts:
        raise ValueError(
            f"Refusing path with '..' traversal from CodeAgent output: {relpath!r}"
        )

    dest_resolved = (root / relpath).resolve()
    root_resolved = root.resolve()
    if not dest_resolved.is_relative_to(root_resolved):
        raise ValueError(
            f"Path escapes boundary: {relpath!r} "
            f"resolves to {dest_resolved}, outside {root_resolved}"
        )


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

        Raises ValueError if any path would escape the worktree boundary
        (absolute paths, ``..`` traversal, or symlink escape).
        """
        written: list[Path] = []
        wt_resolved = self.worktree_path.resolve()
        for relpath, content in files.items():
            self._validate_relpath(relpath, wt_resolved)
            dest = (self.worktree_path / relpath).resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            written.append(dest)
        return written

    @staticmethod
    def _validate_relpath(relpath: str, worktree_root: Path) -> None:
        """Reject paths that escape the worktree boundary.

        Delegates to the module-level :func:`validate_safe_relpath` so
        the same logic is reused for ``tool_runs`` writes in the executor.
        """
        validate_safe_relpath(relpath, worktree_root)

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
