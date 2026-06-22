"""Tests for goal-devin worktree module."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from goal_devin import worktree as wt
from goal_devin.worktree import (
    is_git_repo, repo_root, main_repo_root, branch_name, worktree_path,
    create_worktree, remove_worktree, list_worktrees, merge_worktree,
)


def _init_repo(path):
    """Create a real git repo for testing."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)
    (Path(path) / "README").write_text("test")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True)


class TestWorktreeHelpers(unittest.TestCase):
    def test_branch_name(self):
        self.assertEqual(branch_name("abc123"), "goal-devin/abc123")

    def test_not_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(is_git_repo(tmp))

    def test_is_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            self.assertTrue(is_git_repo(tmp))

    def test_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            root = repo_root(tmp)
            self.assertIsNotNone(root)
            self.assertEqual(Path(root), Path(tmp).resolve())

    def test_main_repo_root_from_main(self):
        """main_repo_root returns the main repo root when called from main repo."""
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            root = main_repo_root(tmp)
            self.assertIsNotNone(root)
            self.assertEqual(Path(root), Path(tmp).resolve())

    def test_main_repo_root_from_worktree(self):
        """main_repo_root returns the MAIN repo root when called from a worktree,
        not the worktree's own top-level. This is the key difference from repo_root."""
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            wt_path, err = create_worktree("test-sid", cwd=tmp)
            self.assertIsNone(err)
            # repo_root from worktree returns the worktree path
            rr = repo_root(str(wt_path))
            self.assertEqual(Path(rr), Path(wt_path).resolve())
            # main_repo_root from worktree returns the MAIN repo root
            mrr = main_repo_root(str(wt_path))
            self.assertEqual(Path(mrr), Path(tmp).resolve())

    def test_worktree_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            p = worktree_path("abc", cwd=tmp)
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "abc")
            self.assertEqual(p.parent.name, ".goal-wt")


class TestCreateRemoveWorktree(unittest.TestCase):
    def test_create_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            wt_path, err = create_worktree("test-sid", cwd=tmp)
            self.assertIsNone(err, f"create failed: {err}")
            self.assertIsNotNone(wt_path)
            self.assertTrue(wt_path.exists())
            # verify .goal-wt is gitignored
            gitignore = Path(tmp) / ".gitignore"
            self.assertIn(".goal-wt/", gitignore.read_text())
            # remove
            ok, err = remove_worktree("test-sid", cwd=tmp, force=True)
            self.assertTrue(ok, f"remove failed: {err}")
            self.assertFalse(wt_path.exists())

    def test_create_not_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, err = create_worktree("test", cwd=tmp)
            self.assertIsNone(p)
            self.assertIn("not a git repo", err)

    def test_remove_from_worktree_cwd(self):
        """remove_worktree must work when cwd is the worktree path itself,
        not just the main repo root. This is what _on_done passes."""
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            wt_path, err = create_worktree("test-sid", cwd=tmp)
            self.assertIsNone(err)
            # remove using the worktree path as cwd (not the main repo root)
            ok, err = remove_worktree("test-sid", cwd=str(wt_path), force=True)
            self.assertTrue(ok, f"remove from worktree cwd failed: {err}")
            self.assertFalse(wt_path.exists())


class TestListWorktrees(unittest.TestCase):
    def test_list_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            self.assertEqual(list_worktrees(cwd=tmp), [])

    def test_list_after_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            create_worktree("sid1", cwd=tmp)
            wts = list_worktrees(cwd=tmp)
            self.assertEqual(len(wts), 1)
            self.assertTrue(wts[0]["branch"].replace("refs/heads/", "").startswith("goal-devin/"))



class TestMergeWorktree(unittest.TestCase):
    """merge_worktree must use the worktree_id (not the devin session_id)."""

    def test_merge_uses_worktree_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            create_worktree("goal-abc123", cwd=tmp)
            wt_dir = Path(tmp) / ".goal-wt" / "goal-abc123"
            (wt_dir / "newfile").write_text("content")
            subprocess.run(["git", "add", "-A"], cwd=wt_dir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "test change"], cwd=wt_dir, capture_output=True)
            ok, err = merge_worktree("goal-abc123", cwd=tmp)
            self.assertTrue(ok, f"merge failed: {err}")

    def test_merge_from_worktree_cwd(self):
        """merge_worktree must work when cwd is the worktree path itself,
        not just the main repo root. This is what GoalDetailScreen passes."""
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp)
            wt_path, err = create_worktree("goal-abc123", cwd=tmp)
            self.assertIsNone(err)
            wt_dir = Path(tmp) / ".goal-wt" / "goal-abc123"
            (wt_dir / "newfile").write_text("content")
            subprocess.run(["git", "add", "-A"], cwd=wt_dir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "test change"], cwd=wt_dir, capture_output=True)
            # merge using the worktree path as cwd (not the main repo root)
            ok, err = merge_worktree("goal-abc123", cwd=str(wt_path))
            self.assertTrue(ok, f"merge from worktree cwd failed: {err}")


if __name__ == "__main__":
    unittest.main()
