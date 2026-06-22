"""Tests for goal-devin. Run with: python -m pytest tests/ or python -m unittest tests/test_cli.py"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# ensure src on path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from goal_devin import cli
from goal_devin.cli import (
    fmt_elapsed, state_file_for, load_state, save_state, all_states,
    build_parser, C, _strip_ansi,
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
    """State must be keyed by cwd so concurrent goals don't collide."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_state_dir = cli.STATE_DIR
        self.orig_states_dir = cli.STATE_DIR_FOR_CWD
        self.orig_log_dir = cli.LOG_DIR
        cli.STATE_DIR = Path(self.tmp) / "state"
        cli.STATE_DIR_FOR_CWD = cli.STATE_DIR / "states"
        cli.LOG_DIR = cli.STATE_DIR / "logs"

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

    def test_save_atomic(self):
        """save_state must not leave corrupt state on disk."""
        save_state({"session_id": "x", "iters": 1}, cwd="/test")
        f = state_file_for(cwd="/test")
        # no tmp file left behind
        self.assertFalse(f.with_suffix(".json.tmp").exists())


class TestParser(unittest.TestCase):
    def test_goal_subcommand(self):
        args = build_parser().parse_args(["goal", "make tests pass"])
        self.assertEqual(args.command, "goal")
        self.assertEqual(args.prompt, "make tests pass")

    def test_resume_subcommand(self):
        args = build_parser().parse_args(["resume", "session-123"])
        self.assertEqual(args.command, "resume")
        self.assertEqual(args.session_id, "session-123")

    def test_resume_no_session_id(self):
        args = build_parser().parse_args(["resume"])
        self.assertIsNone(args.session_id)

    def test_status_all(self):
        args = build_parser().parse_args(["status", "--all"])
        self.assertTrue(args.all)

    def test_logs_follow(self):
        args = build_parser().parse_args(["logs", "-f"])
        self.assertTrue(args.follow)

    def test_version(self):
        args = build_parser().parse_args(["version"])
        self.assertEqual(args.command, "version")

    def test_model_flag(self):
        args = build_parser().parse_args(["goal", "test", "--model", "kimi-k2.7"])
        self.assertEqual(args.model, "kimi-k2.7")

    def test_max_iters_flag(self):
        args = build_parser().parse_args(["goal", "test", "--max-iters", "10"])
        self.assertEqual(args.max_iters, 10)

    def test_quiet_flag(self):
        args = build_parser().parse_args(["goal", "test", "--quiet"])
        self.assertTrue(args.quiet)


class TestStripAnsi(unittest.TestCase):
    def test_strips_codes(self):
        text = f"{C.RED}hello{C.RESET} world"
        self.assertEqual(_strip_ansi(text), "hello world")

    def test_plain_text_unchanged(self):
        self.assertEqual(_strip_ansi("hello world"), "hello world")


class TestRunDevinMissingBinary(unittest.TestCase):
    """run_devin must exit cleanly if devin binary not found."""

    @patch("goal_devin.cli.subprocess.run", side_effect=FileNotFoundError())
    def test_missing_binary_exits_2(self, _):
        with self.assertRaises(SystemExit) as cm:
            cli.run_devin(["--help"])
        self.assertEqual(cm.exception.code, 2)


class TestRunDevinTimeout(unittest.TestCase):
    """run_devin must return code 124 on timeout, not crash."""

    @patch("goal_devin.cli.subprocess.run",
           side_effect=__import__("subprocess").TimeoutExpired(cmd="devin", timeout=1))
    def test_timeout_returns_124(self, _):
        r = cli.run_devin(["--help"], timeout=1)
        self.assertEqual(r.returncode, 124)


if __name__ == "__main__":
    unittest.main()
