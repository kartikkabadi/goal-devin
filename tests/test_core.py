"""Tests for goal-devin core. Run with: pytest tests/ or python -m unittest tests/test_core.py"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from goal_devin import core
from goal_devin.core import (
    fmt_elapsed, state_file_for, load_state, save_state, all_states,
    read_log_tail, GoalLoop, MODELS, parse_devin_models,
    STATUS_RUNNING, STATUS_PAUSED, STATUS_KILLED,
)


class TestFmtElapsed(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(fmt_elapsed(5), "5s")
        self.assertEqual(fmt_elapsed(59), "59s")

    def test_minutes(self):
        self.assertEqual(fmt_elapsed(60), "1m 0s")
        self.assertEqual(fmt_elapsed(83), "1m 23s")

    def test_hours(self):
        self.assertEqual(fmt_elapsed(3600), "1h 0m")
        self.assertEqual(fmt_elapsed(8040), "2h 14m")


class TestStatePerCwd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_state_dir = core.STATE_DIR
        self.orig_states_dir = core.STATE_DIR_FOR_CWD
        self.orig_log_dir = core.LOG_DIR
        core.STATE_DIR = Path(self.tmp) / "state"
        core.STATE_DIR_FOR_CWD = core.STATE_DIR / "states"
        core.LOG_DIR = core.STATE_DIR / "logs"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_different_cwd_different_file(self):
        f1 = state_file_for("/foo/bar")
        f2 = state_file_for("/baz/qux")
        self.assertNotEqual(f1, f2)

    def test_same_cwd_same_file(self):
        f1 = state_file_for("/foo/bar")
        f2 = state_file_for("/foo/bar")
        self.assertEqual(f1, f2)

    def test_save_load_roundtrip(self):
        state = {"session_id": "abc", "goal": "test", "iters": 5}
        save_state(state, cwd="/fake/path")
        loaded = load_state(cwd="/fake/path")
        self.assertEqual(loaded["session_id"], "abc")
        self.assertEqual(loaded["iters"], 5)

    def test_load_nonexistent_returns_none(self):
        self.assertIsNone(load_state(cwd="/nonexistent"))

    def test_all_states(self):
        save_state({"session_id": "a", "cwd": "/x", "goal": "g1"}, cwd="/x")
        save_state({"session_id": "b", "cwd": "/y", "goal": "g2"}, cwd="/y")
        states = list(all_states())
        self.assertEqual(len(states), 2)

    def test_save_atomic_no_tmp_left(self):
        save_state({"session_id": "x", "iters": 1}, cwd="/test")
        self.assertFalse(state_file_for(cwd="/test").with_suffix(".json.tmp").exists())


class TestReadLogTail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        core.LOG_DIR = Path(self.tmp) / "logs"
        core.LOG_DIR.mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_log(self):
        self.assertEqual(read_log_tail("nonexistent"), "")

    def test_tail(self):
        from goal_devin.core import append_log
        append_log("test-sid", "line1\nline2\nline3\n")
        self.assertEqual(read_log_tail("test-sid", lines=2), "line2\nline3")


class TestModels(unittest.TestCase):
    def test_models_not_empty(self):
        self.assertGreater(len(MODELS), 10)

    def test_glm_in_models(self):
        self.assertIn("glm-5.2", MODELS)

    def test_kimi_in_models(self):
        self.assertIn("kimi-k2.7", MODELS)


class TestParseDevinModels(unittest.TestCase):
    @patch("goal_devin.core.run_devin")
    def test_parse_success(self, mock_run):
        cp = MagicMock()
        cp.returncode = 0
        cp.stdout = ""
        cp.stderr = "Error: Unknown model: 'foo'\nAvailable: glm-5.2, kimi-k2.7, gpt-5.5"
        mock_run.return_value = cp
        models = parse_devin_models()
        self.assertIsNotNone(models)
        self.assertIn("glm-5.2", models)
        self.assertIn("kimi-k2.7", models)

    @patch("goal_devin.core.run_devin", side_effect=FileNotFoundError())
    def test_parse_no_devin(self, _):
        self.assertIsNone(parse_devin_models())


class TestGoalLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        core.STATE_DIR = Path(self.tmp) / "state"
        core.STATE_DIR_FOR_CWD = core.STATE_DIR / "states"
        core.LOG_DIR = core.STATE_DIR / "logs"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pause_sets_event(self):
        loop = GoalLoop(goal="test", cwd="/fake")
        loop.pause()
        self.assertTrue(loop.pause_event.is_set())

    def test_resume_clears_event(self):
        loop = GoalLoop(goal="test", cwd="/fake")
        loop.pause()
        loop.resume()
        self.assertFalse(loop.pause_event.is_set())

    def test_kill_sets_event(self):
        loop = GoalLoop(goal="test", cwd="/fake")
        loop.kill()
        self.assertTrue(loop.kill_event.is_set())

    def test_sandbox_forces_autonomous(self):
        loop = GoalLoop(goal="test", use_sandbox=True, cwd="/fake")
        self.assertEqual(loop.permission_mode, "autonomous")

    def test_no_sandbox_keeps_permission(self):
        loop = GoalLoop(goal="test", use_sandbox=False,
                        permission_mode="dangerous", cwd="/fake")
        self.assertEqual(loop.permission_mode, "dangerous")

    def test_worktree_id_stored(self):
        """worktree_id is preserved on the loop instance."""
        loop = GoalLoop(goal="test", cwd="/fake", worktree_id="goal-abc123")
        self.assertEqual(loop.worktree_id, "goal-abc123")

    def test_worktree_id_defaults_none(self):
        loop = GoalLoop(goal="test", cwd="/fake")
        self.assertIsNone(loop.worktree_id)

    @patch("goal_devin.core.subprocess.Popen")
    def test_run_devin_passes_cwd(self, mock_popen):
        """_run_devin passes self.cwd to Popen — critical for worktree isolation."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("output", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc
        loop = GoalLoop(goal="test", cwd="/some/worktree/path")
        loop._run_devin(["-p", "test"])
        _, kwargs = mock_popen.call_args
        self.assertEqual(kwargs.get("cwd"), "/some/worktree/path")

    @patch("goal_devin.core.subprocess.Popen")
    def test_run_devin_default_cwd(self, mock_popen):
        """_run_devin uses process cwd when no cwd specified."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("output", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc
        loop = GoalLoop(goal="test")
        loop._run_devin(["-p", "test"])
        _, kwargs = mock_popen.call_args
        self.assertIn("cwd", kwargs)


class TestNotifySplit(unittest.TestCase):
    """notify_desktop and notify_bell are separate — bell must not fire in TUI."""

    @patch("goal_devin.core.notify_bell")
    @patch("goal_devin.core.notify_desktop")
    def test_notify_calls_both_by_default(self, mock_desktop, mock_bell):
        core.notify("title", "msg")
        mock_desktop.assert_called_once_with("title", "msg")
        mock_bell.assert_called_once()

    @patch("goal_devin.core.notify_bell")
    @patch("goal_devin.core.notify_desktop")
    def test_notify_bell_suppressed_when_false(self, mock_desktop, mock_bell):
        core.notify("title", "msg", bell=False)
        mock_desktop.assert_called_once_with("title", "msg")
        mock_bell.assert_not_called()


class TestVersionDedup(unittest.TestCase):
    """core.__version__ should come from __init__, not be hardcoded."""

    def test_core_version_matches_init(self):
        from goal_devin import __version__ as init_version
        self.assertEqual(core.__version__, init_version)


if __name__ == "__main__":
    unittest.main()
