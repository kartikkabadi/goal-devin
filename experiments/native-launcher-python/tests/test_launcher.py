"""Black-box tests for the R1A Python native launcher."""

from __future__ import annotations

import json
import time
from pathlib import Path

import fake_devin
import pytest
from native_launcher_python.launcher import Launcher, LauncherOptions


def _make_workdir(tmp_path: Path) -> Path:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    return workdir


def _wait_for_summary(runtime_dir: Path, timeout: float = 5.0) -> dict:
    summary_path = runtime_dir / "summary.json"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if summary_path.exists():
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        time.sleep(0.05)
    raise TimeoutError("summary.json did not appear")


def _fake_devin_path() -> str:
    return str(Path(fake_devin.__file__).resolve())


def test_launcher_runs_fake_devin_and_captures_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workdir = _make_workdir(tmp_path)
    runtime_base = tmp_path / "runtime"
    runtime_base.mkdir()

    monkeypatch.setenv("DEVIN_EXECUTABLE", _fake_devin_path())
    monkeypatch.setenv("GOAL_DEVIN_RUNTIME_DIR_ENV_OVERRIDE", str(runtime_base))

    options = LauncherOptions(
        workdir=workdir,
        model="swe-1-7",
        permission_mode="accept-edits",
        keep_runtime=True,
        extra_devin_args=["-p", "--export", str(workdir / "atif.json"), "--", "read fib.py"],
    )
    launcher = Launcher(options)
    exit_code = launcher.run()

    assert exit_code == 0
    assert launcher.runtime is not None
    summary = _wait_for_summary(launcher.runtime.runtime_dir)
    assert summary["event_count"] >= 2
    assert "run_subagent" in summary["tool_names"]
    assert summary["profiles"]
    assert (workdir / ".devin" / "agents").exists() is False or not any(
        (workdir / ".devin" / "agents").iterdir()
    )


def test_launcher_restores_existing_hook_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workdir = _make_workdir(tmp_path)
    devin_dir = workdir / ".devin"
    devin_dir.mkdir()
    original = json.dumps({"SessionStart": []}, indent=2) + "\n"
    hook_path = devin_dir / "hooks.v1.json"
    hook_path.write_text(original, encoding="utf-8")

    runtime_base = tmp_path / "runtime"
    runtime_base.mkdir()

    monkeypatch.setenv("DEVIN_EXECUTABLE", _fake_devin_path())
    monkeypatch.setenv("GOAL_DEVIN_RUNTIME_DIR_ENV_OVERRIDE", str(runtime_base))

    options = LauncherOptions(
        workdir=workdir,
        model="swe-1-7",
        permission_mode="accept-edits",
        keep_runtime=True,
        extra_devin_args=["-p", "--", "hello"],
    )
    launcher = Launcher(options)
    exit_code = launcher.run()

    assert exit_code == 0
    assert hook_path.read_text(encoding="utf-8") == original


def test_launcher_cleans_up_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workdir = _make_workdir(tmp_path)
    runtime_base = tmp_path / "runtime"
    runtime_base.mkdir()

    monkeypatch.setenv("DEVIN_EXECUTABLE", _fake_devin_path())
    monkeypatch.setenv("DEVIN_EXIT_CODE", "7")
    monkeypatch.setenv("GOAL_DEVIN_RUNTIME_DIR_ENV_OVERRIDE", str(runtime_base))

    options = LauncherOptions(
        workdir=workdir,
        model="swe-1-7",
        permission_mode="accept-edits",
        keep_runtime=True,
        extra_devin_args=["-p", "--", "fail"],
    )
    launcher = Launcher(options)
    exit_code = launcher.run()

    assert exit_code == 7
    profile_dir = workdir / ".devin" / "agents"
    assert not profile_dir.exists() or not any(profile_dir.iterdir())


def test_sidecar_is_separate_failure_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workdir = _make_workdir(tmp_path)
    runtime_base = tmp_path / "runtime"
    runtime_base.mkdir()

    monkeypatch.setenv("DEVIN_EXECUTABLE", _fake_devin_path())
    monkeypatch.setenv("GOAL_DEVIN_RUNTIME_DIR_ENV_OVERRIDE", str(runtime_base))

    options = LauncherOptions(
        workdir=workdir,
        model="swe-1-7",
        permission_mode="accept-edits",
        keep_runtime=True,
        extra_devin_args=["-p", "--", "hello"],
    )
    launcher = Launcher(options)
    launcher._validate()  # noqa: SLF001
    launcher._prepare()  # noqa: SLF001
    try:
        assert launcher.sidecar is not None
        launcher.sidecar.terminate()
        launcher.child = launcher._spawn()
        exit_code = launcher.child.wait()
    finally:
        launcher._cleanup(exit_code)  # noqa: SLF001

    assert exit_code == 0


def test_permission_mode_validation() -> None:
    options = LauncherOptions(
        workdir=Path("."),
        model="swe-1-7",
        permission_mode="invalid",
    )
    launcher = Launcher(options)
    with pytest.raises(ValueError):
        launcher._validate()  # noqa: SLF001
