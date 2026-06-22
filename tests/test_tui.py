"""TUI integration tests using Textual's test pilot.

Tests the full TUI flow: launch, start goal, see it appear, iter updates,
kill, error display, startup recovery. Mocks GoalLoop to avoid real devin calls.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from goal_devin.tui import GoalDevinApp, GoalListItem
from goal_devin.core import GoalState, STATUS_STARTING, STATUS_RUNNING, STATUS_STOPPED, STATUS_ERROR, STATUS_KILLED


@pytest.fixture
def app():
    """Create a GoalDevinApp with mocked devin."""
    return GoalDevinApp()


def _make_goal_state(**kwargs):
    """Create a GoalState with sensible defaults."""
    defaults = dict(goal="test goal", model="glm-5.2", session_id="test-sid",
                    status=STATUS_RUNNING, iters=1, elapsed=5.0)
    defaults.update(kwargs)
    return GoalState(**defaults)


async def test_app_launches_with_no_goals(app):
    """TUI launches and shows 'no goals' message."""
    async with app.run_test() as pilot:
        await pilot.pause()
        lv = app.screen.query_one("ListView")
        assert len(lv) == 1  # the "no goals" placeholder


async def test_goal_appears_in_registry_immediately(app):
    """When start_goal is called, the goal appears in the registry before any iteration."""
    async with app.run_test() as pilot:
        with patch("goal_devin.tui.is_git_repo", return_value=False):
            with patch("goal_devin.tui.GoalLoop") as MockLoop:
                mock_loop = MagicMock()
                mock_loop.is_alive.return_value = True
                mock_loop.session_id = None
                MockLoop.return_value = mock_loop

                app.start_goal("say hello", "glm-5.2", 0, False, False)
                await pilot.pause()

                # Goal should be in the registry with "starting" status
                assert len(app.goals) == 1
                gs = list(app.goals.values())[0]
                assert gs.status == STATUS_STARTING
                assert gs.goal == "say hello"


async def test_iter_updates_goal_state(app):
    """When _on_iter fires, the GoalState updates with iters and last_output."""
    async with app.run_test() as pilot:
        track_key = "tmp-abc"
        gs = GoalState(goal="test", model="glm-5.2", session_id=track_key,
                       status=STATUS_STARTING)
        app.goals[track_key] = gs

        app._on_iter(track_key, "real-sid", 1, "did something\nlast line", 5.0)
        await pilot.pause()

        # Registry should have remapped to real session_id
        assert "real-sid" in app.goals
        assert "tmp-abc" not in app.goals
        gs = app.goals["real-sid"]
        assert gs.status == STATUS_RUNNING
        assert gs.iters == 1
        assert gs.last_output == "last line"
        assert gs.elapsed == 5.0


async def test_done_updates_status_to_stopped(app):
    """When _on_done fires with max_iters, status changes to stopped."""
    async with app.run_test() as pilot:
        gs = GoalState(goal="test", model="glm-5.2", session_id="sid1",
                       status=STATUS_RUNNING, iters=5)
        app.goals["sid1"] = gs

        app._on_done("sid1", "max_iters", 5, 30.0)
        await pilot.pause()

        assert app.goals["sid1"].status == STATUS_STOPPED
        assert app.goals["sid1"].iters == 5


async def test_done_with_error_shows_error_status(app):
    """When _on_done fires with error, status changes to error."""
    async with app.run_test() as pilot:
        gs = GoalState(goal="test", model="glm-5.2", session_id="sid1",
                       status=STATUS_RUNNING, iters=0)
        app.goals["sid1"] = gs

        app._on_done("sid1", "error", 0, 0)
        await pilot.pause()

        assert app.goals["sid1"].status == STATUS_ERROR


async def test_status_error_sets_error_field(app):
    """When _on_status receives STATUS_ERROR, GoalState.error is set."""
    async with app.run_test() as pilot:
        gs = GoalState(goal="test", model="glm-5.2", session_id="sid1",
                       status=STATUS_RUNNING)
        app.goals["sid1"] = gs

        app._on_status("sid1", STATUS_ERROR, "devin exited 2")
        await pilot.pause()

        assert app.goals["sid1"].status == STATUS_ERROR
        assert app.goals["sid1"].error == "devin exited 2"


async def test_startup_recovery_loads_state_files(app):
    """On mount, existing state files are loaded into the registry as 'stopped'."""
    with patch("goal_devin.tui.all_states") as mock_states:
        mock_states.return_value = [{
            "session_id": "old-session",
            "goal": "old goal",
            "model": "glm-5.2",
            "iters": 10,
            "status": "running",
            "cwd": "/fake",
            "use_worktree": False,
            "use_sandbox": False,
        }]
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "old-session" in app.goals
            gs = app.goals["old-session"]
            assert gs.status == STATUS_STOPPED
            assert gs.goal == "old goal"
            assert gs.iters == 10


async def test_kill_updates_status(app):
    """When _on_done fires with killed, status changes to killed."""
    async with app.run_test() as pilot:
        gs = GoalState(goal="test", model="glm-5.2", session_id="sid1",
                       status=STATUS_RUNNING, iters=3)
        app.goals["sid1"] = gs

        app._on_done("sid1", "killed", 3, 15.0)
        await pilot.pause()

        assert app.goals["sid1"].status == STATUS_KILLED


async def test_goal_list_item_shows_starting_status(app):
    """GoalListItem renders starting status correctly."""
    async with app.run_test() as pilot:
        gs = GoalState(goal="test goal that is long", model="glm-5.2",
                       session_id="tmp-abc", status=STATUS_STARTING)
        app.goals["tmp-abc"] = gs
        screen = app.screen
        screen.refresh_goals()
        await pilot.pause()

        lv = screen.query_one("ListView")
        assert len(lv) == 1
        item = lv.query("ListItem")[0]
        assert isinstance(item, GoalListItem)
        assert item.gs.status == STATUS_STARTING


async def test_kill_removes_worktree(app):
    """When goal is killed, worktree is removed from disk."""
    async with app.run_test() as pilot:
        gs = GoalState(goal="test", model="glm-5.2", session_id="sid1",
                       status=STATUS_RUNNING, iters=3,
                       use_worktree=True, worktree_id="goal-abc",
                       cwd="/fake/repo")
        app.goals["sid1"] = gs

        with patch("goal_devin.tui.remove_worktree") as mock_remove:
            mock_remove.return_value = (True, None)
            app._on_done("sid1", "killed", 3, 15.0)
            await pilot.pause()

            mock_remove.assert_called_once_with("goal-abc", cwd="/fake/repo", force=True)
        assert app.goals["sid1"].status == STATUS_KILLED


async def test_max_iters_keeps_worktree(app):
    """When goal hits max_iters, worktree is NOT removed (user wants to merge)."""
    async with app.run_test() as pilot:
        gs = GoalState(goal="test", model="glm-5.2", session_id="sid1",
                       status=STATUS_RUNNING, iters=10,
                       use_worktree=True, worktree_id="goal-abc",
                       cwd="/fake/repo")
        app.goals["sid1"] = gs

        with patch("goal_devin.tui.remove_worktree") as mock_remove:
            app._on_done("sid1", "max_iters", 10, 60.0)
            await pilot.pause()

            mock_remove.assert_not_called()
        assert app.goals["sid1"].status == STATUS_STOPPED


async def test_error_keeps_worktree(app):
    """When goal errors, worktree is NOT removed (user wants to debug)."""
    async with app.run_test() as pilot:
        gs = GoalState(goal="test", model="glm-5.2", session_id="sid1",
                       status=STATUS_RUNNING, iters=0,
                       use_worktree=True, worktree_id="goal-abc",
                       cwd="/fake/repo")
        app.goals["sid1"] = gs

        with patch("goal_devin.tui.remove_worktree") as mock_remove:
            app._on_done("sid1", "error", 0, 0)
            await pilot.pause()

            mock_remove.assert_not_called()
        assert app.goals["sid1"].status == STATUS_ERROR


async def test_kill_without_worktree_does_not_call_remove(app):
    """Kill on a goal with no worktree does not call remove_worktree."""
    async with app.run_test() as pilot:
        gs = GoalState(goal="test", model="glm-5.2", session_id="sid1",
                       status=STATUS_RUNNING, iters=3,
                       use_worktree=False, worktree_id=None,
                       cwd="/fake/repo")
        app.goals["sid1"] = gs

        with patch("goal_devin.tui.remove_worktree") as mock_remove:
            app._on_done("sid1", "killed", 3, 15.0)
            await pilot.pause()

            mock_remove.assert_not_called()
        assert app.goals["sid1"].status == STATUS_KILLED


async def test_shutdown_cleans_up_running_worktrees(app):
    """on_shutdown removes worktrees for goals still running/starting."""
    async with app.run_test() as pilot:
        gs_running = GoalState(goal="g1", model="glm-5.2", session_id="sid1",
                               status=STATUS_RUNNING, iters=3,
                               use_worktree=True, worktree_id="goal-r1",
                               cwd="/fake/repo")
        gs_starting = GoalState(goal="g2", model="glm-5.2", session_id="tmp-abc",
                                status=STATUS_STARTING,
                                use_worktree=True, worktree_id="goal-s2",
                                cwd="/fake/repo2")
        gs_stopped = GoalState(goal="g3", model="glm-5.2", session_id="sid3",
                               status=STATUS_STOPPED, iters=10,
                               use_worktree=True, worktree_id="goal-s3",
                               cwd="/fake/repo3")
        app.goals["sid1"] = gs_running
        app.goals["tmp-abc"] = gs_starting
        app.goals["sid3"] = gs_stopped

        mock_loop = MagicMock()
        mock_loop.is_alive.return_value = True
        app.loops["sid1"] = mock_loop

        with patch("goal_devin.tui.remove_worktree") as mock_remove:
            mock_remove.return_value = (True, None)
            app.on_shutdown()
            await pilot.pause()

            # running + starting goals get worktree removed
            calls = mock_remove.call_args_list
            removed_ids = {c.kwargs["cwd"] for c in calls}
            assert any(c.args[0] == "goal-r1" for c in calls), "running goal worktree not removed"
            assert any(c.args[0] == "goal-s2" for c in calls), "starting goal worktree not removed"
            # stopped goal worktree NOT removed
            assert not any(c.args[0] == "goal-s3" for c in calls), "stopped goal worktree should not be removed"
