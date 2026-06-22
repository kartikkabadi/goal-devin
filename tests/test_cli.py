"""Tests for the hidden CLI — verifies resume passes session_id (the bug fix)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from goal_devin import cli, core


class TestCmdResume(unittest.TestCase):
    """cmd_resume must pass session_id to GoalLoop (was broken — started fresh session)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        core.STATE_DIR = Path(self.tmp) / "state"
        core.STATE_DIR_FOR_CWD = core.STATE_DIR / "states"
        core.LOG_DIR = core.STATE_DIR / "logs"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("goal_devin.cli._run_goal_loop")
    def test_resume_passes_session_id(self, mock_run):
        """resume must pass the existing session_id, not start fresh."""
        # save a state as if a goal was already running
        state = {
            "session_id": "existing-sid-123",
            "cwd": "/some/path",
            "goal": "make tests pass",
            "model": "glm-5.2",
            "permission_mode": "dangerous",
            "use_worktree": False,
            "use_sandbox": False,
            "worktree_id": None,
            "iters": 5,
            "status": "stopped",
        }
        core.save_state(state, cwd="/some/path")
        # call cmd_resume with args from argparse
        args = MagicMock()
        args.session_id = None  # should use state's session_id
        args.goal = None        # should use state's goal
        args.model = None
        args.permission_mode = None
        args.sleep = None
        args.max_iters = None
        args.iter_timeout = None
        with patch("goal_devin.cli.load_state", return_value=state):
            cli.cmd_resume(args)
        # verify _run_goal_loop was called with the existing session_id
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("session_id"), "existing-sid-123")
        self.assertEqual(kwargs.get("goal"), "make tests pass")

    @patch("goal_devin.cli._run_goal_loop")
    def test_resume_explicit_session_id_overrides(self, mock_run):
        """explicit --session-id overrides state."""
        state = {
            "session_id": "old-sid",
            "cwd": "/path",
            "goal": "old goal",
            "model": "glm-5.2",
            "permission_mode": "dangerous",
            "use_worktree": False,
            "use_sandbox": False,
            "worktree_id": None,
            "iters": 3,
            "status": "stopped",
        }
        args = MagicMock()
        args.session_id = "new-explicit-sid"
        args.goal = "new goal"
        args.model = None
        args.permission_mode = None
        args.sleep = None
        args.max_iters = None
        args.iter_timeout = None
        with patch("goal_devin.cli.load_state", return_value=state):
            cli.cmd_resume(args)
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("session_id"), "new-explicit-sid")
        self.assertEqual(kwargs.get("goal"), "new goal")

    @patch("goal_devin.cli._run_goal_loop")
    def test_resume_uses_worktree_id_from_state(self, mock_run):
        """resume must use the stored worktree_id, not create a new worktree."""
        state = {
            "session_id": "devin-sid-xyz",
            "cwd": "/repo/.goal-wt/goal-abc123",
            "goal": "fix bug",
            "model": "glm-5.2",
            "permission_mode": "dangerous",
            "use_worktree": True,
            "use_sandbox": False,
            "worktree_id": "goal-abc123",
            "iters": 5,
            "status": "stopped",
        }
        args = MagicMock()
        args.session_id = None
        args.goal = None
        args.model = None
        args.permission_mode = None
        args.sleep = None
        args.max_iters = None
        args.iter_timeout = None
        with patch("goal_devin.cli.load_state", return_value=state):
            cli.cmd_resume(args)
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("worktree_id"), "goal-abc123")
        self.assertEqual(kwargs.get("cwd"), "/repo/.goal-wt/goal-abc123")


class TestCmdGoalNoWorktree(unittest.TestCase):
    """cmd_goal with --no-worktree must not create a worktree."""

    @patch("goal_devin.cli._run_goal_loop")
    def test_no_worktree(self, mock_run):
        args = MagicMock()
        args.prompt = "test goal"
        args.model = None
        args.permission_mode = None
        args.sleep = None
        args.max_iters = None
        args.iter_timeout = None
        args.worktree = False
        args.sandbox = False
        cli.cmd_goal(args)
        _, kwargs = mock_run.call_args
        self.assertFalse(kwargs.get("use_worktree"))
        self.assertIsNone(kwargs.get("worktree_id"))


if __name__ == "__main__":
    unittest.main()
