"""Textual TUI for goal-devin.

Screens:
  - MainScreen: goal list + normal menu
  - NewGoalScreen: prompt + model picker + worktree/sandbox toggles
  - GoalDetailScreen: selected goal info + log tail + actions
  - AdvancedScreen: advanced controls
  - LogsScreen: full log viewer + follow mode
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Label, ListItem, ListView, Input, Button,
    Select, Checkbox, RichLog, Static, TextArea,
)
from rich.panel import Panel
from rich.table import Table

from . import core
from .core import (
    GoalLoop, GoalState, all_states, fmt_elapsed,
    read_log_tail, log_path, MODELS, DEFAULTS, notify_desktop,
)
from .worktree import is_git_repo, create_worktree, merge_worktree, list_worktrees, remove_worktree


CSS = """
Screen {
    background: $surface;
    color: $text;
}

#main-container {
    padding: 1 2;
}

.title-bar {
    height: 3;
    content-align: center middle;
    background: $primary;
    color: $text;
    text-align: center;
}

.goal-list {
    height: 1fr;
    border: $primary;
    margin: 1 0;
}

.form-container {
    padding: 1 2;
}

.form-field {
    margin: 1 0;
}

.form-label {
    color: $accent;
    text-style: bold;
}

.detail-panel {
    padding: 1 2;
}

.log-view {
    height: 1fr;
    border: $accent;
    margin: 1 0;
}

.action-bar {
    height: 3;
    dock: bottom;
    background: $boost;
    padding: 0 1;
}

.status-line {
    dock: bottom;
    height: 1;
    background: $boost;
    color: $text-muted;
    padding: 0 1;
}

.advanced-list {
    padding: 1 2;
}

.advanced-item {
    padding: 0 1;
    height: 3;
    border-bottom: $boost;
}

.error-text {
    color: $error;
    text-style: bold;
}

.dim-text {
    color: $text-muted;
}

"""


class GoalListItem(ListItem):
    """A goal entry in the main list — reads from GoalState."""

    def __init__(self, gs: GoalState) -> None:
        self.gs = gs
        sid = gs.session_id or "starting..."
        goal = gs.goal or "?"
        if len(goal) > 50:
            goal = goal[:47] + "..."
        iters = gs.iters
        status = gs.status
        elapsed = fmt_elapsed(gs.elapsed) if gs.elapsed else "0s"
        super().__init__(Label(f"  {sid:<20} {goal:<50} iter {iters}  {elapsed}  [{status}]", classes="goal-item"))


class MainScreen(Screen):
    """Main screen: goal list + normal menu."""

    BINDINGS = [
        Binding("n", "new_goal", "new"),
        Binding("r", "resume_goal", "resume"),
        Binding("s", "toggle_status", "status"),
        Binding("l", "logs", "logs"),
        Binding("a", "advanced", "advanced"),
        Binding("enter", "detail", "detail"),
    ]

    show_status = reactive(False)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static(f"goal-devin v{core.__version__} — unbounded goal loop",
                   classes="title-bar"),
            Static("  Active Goals (↑↓ navigate, Enter for details)",
                   classes="dim-text"),
            ListView(classes="goal-list"),
            Static("", id="status-panel", classes="dim-text"),
            classes="main-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_goals()
        # 1s timer to update elapsed time for running goals
        self.set_interval(1.0, self._tick_elapsed)

    def _tick_elapsed(self) -> None:
        """Update elapsed time for running goals and refresh the list."""
        now = time.time()
        changed = False
        for gs in self.app.goals.values():
            if gs.status == core.STATUS_RUNNING and gs.started_at:
                try:
                    started = datetime.fromisoformat(gs.started_at).timestamp()
                    gs.elapsed = now - started
                    changed = True
                except (ValueError, OSError):
                    pass
        if changed:
            self.refresh_goals()

    def refresh_goals(self) -> None:
        """Refresh the goal list from in-memory registry, preserving selection."""
        lv = self.query_one(ListView)
        prev_index = lv.index
        goals = list(self.app.goals.values())
        lv.clear()
        for gs in goals:
            lv.append(GoalListItem(gs))
        if not goals:
            lv.append(ListItem(Label("  no goals — press n to start one",
                                     classes="dim-text")))
        if prev_index is not None and prev_index < len(lv):
            lv.index = prev_index
        if self.show_status:
            self._render_status_panel(goals)

    def _render_status_panel(self, goals) -> None:
        panel = self.query_one("#status-panel")
        if not goals:
            panel.update("  no goal states found.")
            return
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("session", style="cyan")
        table.add_column("iters", justify="right")
        table.add_column("elapsed")
        table.add_column("model", style="magenta")
        table.add_column("status")
        table.add_column("goal")
        for gs in goals:
            goal = gs.goal or "?"
            if len(goal) > 30:
                goal = goal[:27] + "..."
            table.add_row(
                gs.session_id or "starting...",
                str(gs.iters),
                fmt_elapsed(gs.elapsed) if gs.elapsed else "0s",
                gs.model or "?",
                gs.status,
                goal,
            )
        panel.update(table)

    def action_toggle_status(self) -> None:
        self.show_status = not self.show_status
        self.refresh_goals()

    def action_new_goal(self) -> None:
        self.app.push_screen(NewGoalScreen())

    def _selected_goal(self) -> GoalState | None:
        lv = self.query_one(ListView)
        items = lv.query("ListItem")
        if lv.index is None or not items:
            return None
        if lv.index < len(items):
            item = items[lv.index]
            if isinstance(item, GoalListItem):
                return item.gs
        return None

    def action_resume_goal(self) -> None:
        """Actually resume a stopped/killed goal's loop."""
        gs = self._selected_goal()
        if not gs:
            self.app.bell()
            return
        sid = gs.session_id
        if not sid or sid.startswith("tmp-"):
            self.app.bell()
            return
        if self.app.get_loop(sid):
            self.app.push_screen(GoalDetailScreen(sid, gs))
            return
        # Convert GoalState to dict for resume_goal
        self.app.resume_goal(asdict(gs))

    def action_logs(self) -> None:
        gs = self._selected_goal()
        if gs and gs.session_id and not gs.session_id.startswith("tmp-"):
            self.app.push_screen(LogsScreen(gs.session_id))

    def action_advanced(self) -> None:
        self.app.push_screen(AdvancedScreen())

    def action_detail(self) -> None:
        gs = self._selected_goal()
        if gs:
            self.app.push_screen(GoalDetailScreen(gs.session_id or "", gs))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, GoalListItem):
            gs = event.item.gs
            self.app.push_screen(GoalDetailScreen(gs.session_id or "", gs))


class NewGoalScreen(Screen):
    """New goal form: prompt + model + worktree + sandbox + max iters."""

    BINDINGS = [
        Binding("escape", "cancel", "cancel"),
        Binding("ctrl+s", "start", "start"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(
            Static("New Goal (ctrl+s to start, Esc to cancel)", classes="title-bar"),
            Static("  Goal prompt:", classes="form-label"),
            TextArea(id="goal-prompt", classes="form-field"),
            Static("  Model:", classes="form-label"),
            Select(
                [(m, m) for m in MODELS],
                value=DEFAULTS["model"],
                id="model-select",
                classes="form-field",
            ),
            Static("  Max iters (0 = forever):", classes="form-label"),
            Input(value="0", id="max-iters", type="integer"),
            Checkbox("git worktree (branch isolation)",
                     value=DEFAULTS["use_worktree"] and is_git_repo(),
                     id="use-worktree"),
            Checkbox("devin sandbox (OS-level exec isolation)",
                     value=DEFAULTS["use_sandbox"],
                     id="use-sandbox"),
            Static("", id="form-error", classes="error-text"),
            Horizontal(
                Button("Start", id="start-btn", variant="primary"),
                Button("Cancel", id="cancel-btn", variant="default"),
                classes="action-bar",
            ),
            classes="form-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#goal-prompt").focus()

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def action_start(self) -> None:
        self._start_goal()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.app.pop_screen()
        elif event.button.id == "start-btn":
            self._start_goal()

    def _start_goal(self) -> None:
        prompt = self.query_one("#goal-prompt").text.strip()
        if not prompt:
            self.query_one("#form-error").update("error: goal prompt is empty")
            return
        model = self.query_one("#model-select").value
        max_iters = self.query_one("#max-iters").value or 0
        use_worktree = self.query_one("#use-worktree").value
        use_sandbox = self.query_one("#use-sandbox").value
        self.app.pop_screen()
        self.app.start_goal(
            goal=prompt,
            model=model,
            max_iters=int(max_iters),
            use_worktree=use_worktree,
            use_sandbox=use_sandbox,
        )


class GoalDetailScreen(Screen):
    """Detail view for a single goal: info + log tail + actions."""

    BINDINGS = [
        Binding("p", "pause_resume", "pause/resume"),
        Binding("k", "kill", "kill"),
        Binding("L", "full_logs", "logs"),
        Binding("m", "merge", "merge"),
        Binding("escape", "back", "back"),
    ]

    def __init__(self, session_id: str, gs: GoalState) -> None:
        super().__init__()
        self.session_id = session_id
        self.gs = gs

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static(f"Goal: {self.session_id or 'starting...'}", classes="title-bar"),
            VerticalScroll(
                Static(self._render_info(), id="detail-info"),
                Static("  Log tail (last 20 lines):", classes="form-label"),
                RichLog(id="detail-log", classes="log-view", wrap=True, markup=True),
                id="detail-scroll",
            ),
            Static("", id="detail-status", classes="status-line"),
            classes="detail-panel",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(1.0, self._refresh)

    def _render_info(self) -> Panel:
        gs = self.gs
        cwd = (gs.cwd or "?").replace(str(Path.home()), "~")
        elapsed = fmt_elapsed(gs.elapsed) if gs.elapsed else "0s"
        info = (
            f"  goal:     {gs.goal or '?'}\n"
            f"  session:  {gs.session_id or 'starting...'}\n"
            f"  model:    {gs.model or '?'}\n"
            f"  iters:    {gs.iters}\n"
            f"  elapsed:  {elapsed}\n"
            f"  status:   {gs.status}\n"
            f"  cwd:      {cwd}\n"
            f"  worktree: {'yes' if gs.use_worktree else 'no'}\n"
            f"  sandbox:  {'yes' if gs.use_sandbox else 'no'}\n"
        )
        if gs.error:
            info += f"  error:    {gs.error}\n"
        info += "\n  [p] pause/resume  [k] kill  [L] full logs  [m] merge worktree  [Esc] back"
        return Panel(info, title=self.session_id or "starting...", border_style="cyan")

    def _refresh(self) -> None:
        """Refresh from in-memory registry."""
        fresh = self.app.get_goal(self.session_id)
        if fresh:
            self.gs = fresh
        self.query_one("#detail-info").update(self._render_info())
        log = self.query_one("#detail-log")
        log.clear()
        if self.session_id:
            tail = read_log_tail(self.session_id, lines=20)
            if tail:
                for line in tail.splitlines():
                    log.write(line)
            else:
                log.write("(no logs yet)", style="dim")
        else:
            log.write("(waiting for session to start...)", style="dim")

    def action_pause_resume(self) -> None:
        loop = self.app.get_loop(self.session_id)
        if not loop:
            self.query_one("#detail-status").update(
                f"  no running loop for {self.session_id}")
            return
        if loop.pause_event.is_set():
            loop.resume()
            self.query_one("#detail-status").update(f"  resumed {self.session_id}")
        else:
            loop.pause()
            self.query_one("#detail-status").update(f"  paused {self.session_id}")

    def action_kill(self) -> None:
        loop = self.app.get_loop(self.session_id)
        if loop:
            loop.kill()
            self.query_one("#detail-status").update(f"  killed {self.session_id}")
        else:
            self.query_one("#detail-status").update(
                f"  no running loop for {self.session_id}")

    def action_full_logs(self) -> None:
        if self.session_id:
            self.app.push_screen(LogsScreen(self.session_id))

    def action_merge(self) -> None:
        if not self.gs.use_worktree:
            self.query_one("#detail-status").update("  no worktree for this goal")
            return
        wt_id = self.gs.worktree_id or self.session_id
        ok, err = merge_worktree(wt_id, cwd=self.gs.cwd)
        if ok:
            self.query_one("#detail-status").update(f"  merged {wt_id}")
        else:
            self.query_one("#detail-status").update(f"  merge failed: {err}")

    def action_back(self) -> None:
        self.app.pop_screen()


class AdvancedScreen(Screen):
    """Advanced controls menu."""

    BINDINGS = [
        Binding("escape", "back", "back"),
        Binding("m", "model", "model"),
        Binding("p", "permission", "permission"),
        Binding("w", "worktree", "worktree"),
        Binding("t", "timeout", "timeout"),
        Binding("s", "sleep", "sleep"),
        Binding("k", "kill", "kill"),
        Binding("e", "export", "export"),
        Binding("d", "delete", "delete"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(
            Static("Advanced", classes="title-bar"),
            self._menu_item("m", "model picker", "change default model"),
            self._menu_item("p", "permission mode", "dangerous / auto"),
            self._menu_item("w", "worktree mgmt", "list / create / remove / merge worktrees"),
            self._menu_item("t", "iter timeout", f"per-iter timeout ({DEFAULTS['iter_timeout']}s)"),
            self._menu_item("s", "sleep between iters", f"seconds ({DEFAULTS['sleep_secs']}s)"),
            self._menu_item("k", "kill session", "stop a running goal by session id"),
            self._menu_item("e", "export session", "export conversation to file"),
            self._menu_item("d", "delete state", "remove a goal's state file"),
            Static("", id="advanced-status", classes="status-line"),
            classes="advanced-list",
        )
        yield Footer()

    def _menu_item(self, key: str, label: str, desc: str) -> Static:
        return Static(f"  [{key}]  {label:<22} {desc}", classes="advanced-item")

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_model(self) -> None:
        self.query_one("#advanced-status").update(
            f"  default model: {DEFAULTS['model']} (set via GOAL_DEVIN_MODEL env)")

    def action_permission(self) -> None:
        self.query_one("#advanced-status").update(
            f"  permission mode: {DEFAULTS['permission_mode']} (set via GOAL_DEVIN_PERMISSION_MODE env)")

    def action_worktree(self) -> None:
        wts = list_worktrees()
        if not wts:
            self.query_one("#advanced-status").update("  no worktrees found")
            return
        lines = ["  worktrees:"]
        for w in wts:
            lines.append(f"    {w.get('branch', '?')}  {w.get('path', '?')}")
        self.query_one("#advanced-status").update("\n".join(lines))

    def action_timeout(self) -> None:
        self.query_one("#advanced-status").update(
            f"  iter timeout: {DEFAULTS['iter_timeout']}s (set via GOAL_DEVIN_ITER_TIMEOUT env)")

    def action_sleep(self) -> None:
        self.query_one("#advanced-status").update(
            f"  sleep: {DEFAULTS['sleep_secs']}s (set via GOAL_DEVIN_SLEEP env)")

    def action_kill(self) -> None:
        self.query_one("#advanced-status").update(
            "  press k on a goal detail screen to kill it")

    def action_export(self) -> None:
        self.query_one("#advanced-status").update(
            "  use `devin --export -- -r <session-id>` to export a session")

    def action_delete(self) -> None:
        self.query_one("#advanced-status").update(
            "  delete state files manually in ~/.goal-devin/states/")


class LogsScreen(Screen):
    """Full log viewer with optional follow mode."""

    BINDINGS = [
        Binding("f", "toggle_follow", "follow"),
        Binding("escape", "back", "back"),
    ]

    follow = reactive(False)

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id
        self._offset = 0  # byte offset for follow mode

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static(f"Logs: {self.session_id}", classes="title-bar"),
            RichLog(id="full-log", classes="log-view", wrap=True, markup=True),
            Static("", id="log-status", classes="status-line"),
            classes="detail-panel",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_full_log()
        self.set_interval(1.0, self._poll_follow)

    def _load_full_log(self) -> None:
        log = self.query_one("#full-log")
        log.clear()
        lp = log_path(self.session_id)
        if not lp.exists():
            log.write(f"(no log at {lp})", style="dim")
            self._offset = 0
            return
        text = lp.read_text()
        self._offset = len(text.encode())
        for line in text.splitlines():
            log.write(line)

    def action_toggle_follow(self) -> None:
        self.follow = not self.follow
        status = self.query_one("#log-status")
        if self.follow:
            status.update("  following (press f to stop)")
            self._load_full_log()
        else:
            status.update("  paused (press f to follow)")

    def _poll_follow(self) -> None:
        if not self.follow:
            return
        lp = log_path(self.session_id)
        if not lp.exists():
            return
        with lp.open("rb") as f:
            f.seek(self._offset)
            new_bytes = f.read()
        if not new_bytes:
            return
        self._offset += len(new_bytes)
        new_text = new_bytes.decode("utf-8", errors="replace")
        log = self.query_one("#full-log")
        for line in new_text.splitlines():
            log.write(line)

    def action_back(self) -> None:
        self.app.pop_screen()


class GoalDevinApp(App):
    """Main TUI application."""

    CSS = CSS
    TITLE = "goal-devin"
    BINDINGS = [
        Binding("ctrl+c", "quit", "quit", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.goals: dict[str, GoalState] = {}  # session_id -> GoalState
        self.loops: dict[str, GoalLoop] = {}   # session_id -> GoalLoop

    def on_mount(self) -> None:
        # Load existing state files into registry on startup
        for state in all_states():
            sid = state.get("session_id", "")
            if not sid:
                continue
            gs = GoalState(
                goal=state.get("goal", ""),
                model=state.get("model", ""),
                session_id=sid,
                status=core.STATUS_STOPPED,  # previous session, not running
                iters=state.get("iters", 0),
                started_at=state.get("started_at", ""),
                cwd=state.get("cwd", ""),
                worktree_id=state.get("worktree_id"),
                use_worktree=state.get("use_worktree", False),
                use_sandbox=state.get("use_sandbox", False),
            )
            self.goals[sid] = gs
        self.push_screen(MainScreen())

    def on_shutdown(self) -> None:
        """Kill all running loops on quit."""
        for loop in self.loops.values():
            if loop.is_alive():
                loop.kill()

    def get_loop(self, session_id: str) -> GoalLoop | None:
        return self.loops.get(session_id)

    def get_goal(self, session_id: str) -> GoalState | None:
        return self.goals.get(session_id)

    def _refresh_main_screen(self):
        """Trigger MainScreen to re-read the goals registry."""
        screen = self.screen
        if hasattr(screen, "refresh_goals"):
            screen.refresh_goals()

    def start_goal(self, goal: str, model: str, max_iters: int,
                   use_worktree: bool, use_sandbox: bool) -> None:
        """Start a new goal loop in a background thread."""
        worktree_id = f"goal-{uuid.uuid4().hex[:8]}"
        cwd = os.getcwd()

        if use_worktree and is_git_repo(cwd):
            wt_path, err = create_worktree(worktree_id, cwd=cwd)
            if wt_path:
                cwd = str(wt_path)
            else:
                self.notify(f"worktree creation failed: {err}", severity="error")
                use_worktree = False
                worktree_id = None
        else:
            worktree_id = None

        # Create in-memory state immediately — shows in list before iter 0
        track_key = worktree_id or f"tmp-{uuid.uuid4().hex[:8]}"
        gs = GoalState(
            goal=goal,
            model=model,
            session_id=track_key,  # placeholder until real session_id
            status=core.STATUS_STARTING,
            started_at=datetime.now().isoformat(timespec="seconds"),
            cwd=cwd,
            worktree_id=worktree_id,
            use_worktree=use_worktree,
            use_sandbox=use_sandbox,
        )
        self.goals[track_key] = gs
        self._refresh_main_screen()
        self.notify(f"started goal: {goal[:40]}", timeout=5)

        def on_iter(iters, sid, output, elapsed):
            self.call_from_thread(self._on_iter, track_key, sid, iters, output, elapsed)

        def on_status(status, detail):
            self.call_from_thread(self._on_status, track_key, status, detail)

        def on_done(reason, iters, elapsed):
            self.call_from_thread(self._on_done, track_key, reason, iters, elapsed)

        loop = GoalLoop(
            goal=goal,
            model=model,
            max_iters=max_iters,
            use_worktree=use_worktree,
            use_sandbox=use_sandbox,
            cwd=cwd,
            worktree_id=worktree_id,
            on_iter=on_iter,
            on_status=on_status,
            on_done=on_done,
        )
        loop.start()
        self.loops[track_key] = loop

    def resume_goal(self, state: dict) -> None:
        """Resume a stopped/killed goal from saved state."""
        session_id = state.get("session_id")
        goal = state.get("goal", "")
        if not session_id or not goal:
            self.bell()
            return
        cwd = state.get("cwd", os.getcwd())
        worktree_id = state.get("worktree_id")
        use_worktree = state.get("use_worktree", False)
        use_sandbox = state.get("use_sandbox", False)

        # Update in-memory state
        gs = GoalState(
            goal=goal,
            model=state.get("model", ""),
            session_id=session_id,
            status=core.STATUS_STARTING,
            iters=state.get("iters", 0),
            started_at=state.get("started_at", ""),
            cwd=cwd,
            worktree_id=worktree_id,
            use_worktree=use_worktree,
            use_sandbox=use_sandbox,
        )
        self.goals[session_id] = gs
        self._refresh_main_screen()
        self.notify(f"resumed goal: {goal[:40]}", timeout=5)

        def on_iter(iters, sid, output, elapsed):
            self.call_from_thread(self._on_iter, session_id, sid, iters, output, elapsed)

        def on_status(status, detail):
            self.call_from_thread(self._on_status, session_id, status, detail)

        def on_done(reason, iters, elapsed):
            self.call_from_thread(self._on_done, session_id, reason, iters, elapsed)

        loop = GoalLoop(
            goal=goal,
            session_id=session_id,
            model=state.get("model"),
            permission_mode=state.get("permission_mode"),
            use_worktree=use_worktree,
            use_sandbox=use_sandbox,
            cwd=cwd,
            worktree_id=worktree_id,
            on_iter=on_iter,
            on_status=on_status,
            on_done=on_done,
        )
        loop.start()
        self.loops[session_id] = loop

    def _on_iter(self, track_key, sid, iters, output, elapsed):
        """Update GoalState on each iteration."""
        gs = self.goals.get(track_key)
        if gs:
            # Remap temp key to real session_id on first iter
            if track_key != sid:
                self.goals[sid] = self.goals.pop(track_key)
                gs = self.goals[sid]
                # Also remap loops dict
                if track_key in self.loops:
                    self.loops[sid] = self.loops.pop(track_key)
            gs.session_id = sid
            gs.status = core.STATUS_RUNNING
            gs.iters = iters
            gs.elapsed = elapsed
            gs.last_output = output.strip().split("\n")[-1] if output else ""
        self._refresh_main_screen()

    def _on_status(self, track_key, status, detail):
        """Update GoalState on status change."""
        gs = self.goals.get(track_key)
        if gs:
            gs.status = status
            if status == core.STATUS_ERROR:
                gs.error = detail
                self.notify(f"error: {detail}", severity="error", timeout=10)
        self._refresh_main_screen()

    def _on_done(self, track_key, reason, iters, elapsed):
        """Update GoalState on completion."""
        gs = self.goals.get(track_key)
        elapsed_str = fmt_elapsed(elapsed)
        if gs:
            gs.iters = iters
            gs.elapsed = elapsed
            if reason == "killed":
                gs.status = core.STATUS_KILLED
                # ponytail: remove worktree on kill — user discarded the work.
                # max_iters/error keep worktree so user can merge/debug.
                if gs.use_worktree and gs.worktree_id:
                    ok, err = remove_worktree(gs.worktree_id, cwd=gs.cwd, force=True)
                    if not ok:
                        self.notify(f"worktree cleanup failed: {err}", severity="warning", timeout=10)
            elif reason == "error":
                gs.status = core.STATUS_ERROR
            else:
                gs.status = core.STATUS_STOPPED
        if reason == "max_iters":
            msg = f"goal done — {iters} iters in {elapsed_str}"
        elif reason == "killed":
            msg = f"goal killed at iter {iters} ({elapsed_str})"
        elif reason == "error":
            msg = f"goal error at iter {iters}"
        else:
            msg = f"goal stopped: {reason}"
        notify_desktop("goal-devin", msg)
        self.notify(msg, timeout=10)
        self._refresh_main_screen()


def run_tui():
    """Entry point for the TUI."""
    app = GoalDevinApp()
    app.run()


if __name__ == "__main__":
    run_tui()
