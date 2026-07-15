"""Deterministic candidate tests for the native launcher happy path."""

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CANDIDATE = REPO_ROOT / "experiments" / "native-launcher-python" / "goal-devin-dev"
TESTKIT = REPO_ROOT / "experiments" / "native-launcher-testkit"
FAKE_DEVIN = TESTKIT / "fake-devin"
RUN_CONTRACT = TESTKIT / "run-contract.py"
CANARY_FIXTURE = TESTKIT / "fixtures" / "canary"
EXISTING_HOOKS = TESTKIT / "fixtures" / "existing-hooks" / ".devin" / "hooks.json"

_spec = importlib.util.spec_from_file_location(
    "schema_validator", str(TESTKIT / "schema_validator.py")
)
schema_validator = importlib.util.module_from_spec(_spec)
sys.modules["schema_validator"] = schema_validator
_spec.loader.exec_module(schema_validator)


def _run_contract(
    *,
    tty: bool = False,
    existing_hooks: bool = False,
    process_overlap: bool = False,
    keep: bool = False,
    extra_env: dict | None = None,
) -> tuple[int, list[str], Path | None]:
    base_dir = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-test-"))
    runtime_root = base_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3",
        str(RUN_CONTRACT),
        "--candidate",
        str(CANDIDATE),
        "--devin-bin",
        str(FAKE_DEVIN),
        "--canary-fixture",
        str(CANARY_FIXTURE),
        "--runtime-root",
        str(runtime_root),
        "--base-dir",
        str(base_dir),
    ]
    if existing_hooks:
        cmd.extend(["--existing-hooks", str(EXISTING_HOOKS)])
    if tty:
        cmd.append("--tty")
    if process_overlap:
        cmd.append("--process-overlap")
    if keep:
        cmd.append("--keep-artifacts")
    env = os.environ.copy()
    env["GOAL_DEVIN_FAKE_EXIT_CODE"] = "0"
    env["GOAL_DEVIN_FAKE_SLEEP"] = "0.1"
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    errors = [line.strip() for line in result.stderr.splitlines() if line.startswith("  - ")]
    return result.returncode, errors, runtime_root if keep else None


@pytest.fixture
def contract_pass(tmp_path):
    """Run the contract and return the runtime directory for assertions."""
    base_dir = tmp_path / "base"
    runtime_root = base_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3",
        str(RUN_CONTRACT),
        "--candidate",
        str(CANDIDATE),
        "--devin-bin",
        str(FAKE_DEVIN),
        "--canary-fixture",
        str(CANARY_FIXTURE),
        "--runtime-root",
        str(runtime_root),
        "--base-dir",
        str(base_dir),
        "--keep-artifacts",
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "GOAL_DEVIN_FAKE_EXIT_CODE": "0", "GOAL_DEVIN_FAKE_SLEEP": "0.1"},
    )
    assert result.returncode == 0, result.stderr
    run_dirs = [p for p in runtime_root.iterdir() if p.is_dir() and p.name != "canary"]
    assert run_dirs, f"No run directory found in {runtime_root}"
    return run_dirs[0]


def test_happy_path_lifecycle():
    rc, errors, _ = _run_contract()
    assert rc == 0, "\n".join(errors)


def test_no_print_mode_flag_in_argv(contract_pass):
    record = json.loads((contract_pass / "fake-devin.record.json").read_text())
    assert "-p" not in record["argv"]
    assert "--print" not in record["argv"]


def test_exact_argv(contract_pass):
    record = json.loads((contract_pass / "fake-devin.record.json").read_text())
    assert record["argv"] == ["--model", "swe-1-7", "--permission-mode", "accept-edits"]


def test_exact_root_worker_model_equality(contract_pass):
    manifest = json.loads((contract_pass / "manifest.json").read_text())
    model = manifest["model"]
    record = json.loads((contract_pass / "fake-devin.record.json").read_text())
    assert record["model"] == model
    profile_id = manifest["profile_id"]
    summary = json.loads((contract_pass / "summary.json").read_text())
    assert summary["last_event"]["profile"] == profile_id


def test_runtime_directory_permissions(contract_pass):
    assert stat.S_IMODE(contract_pass.stat().st_mode) == 0o700
    assert stat.S_IMODE((contract_pass / "events").stat().st_mode) == 0o700


def test_runtime_file_permissions(contract_pass):
    assert stat.S_IMODE((contract_pass / "manifest.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((contract_pass / "summary.json").stat().st_mode) == 0o600


def test_atomic_event_publication(contract_pass):
    tmp_files = list((contract_pass / "events").glob("*.tmp"))
    assert not tmp_files
    json_files = list((contract_pass / "events").glob("*.json"))
    assert len(json_files) == 1


def test_event_schema_rejection_for_invalid_fixture():
    from native_launcher.schema import validate_file

    schema_path = TESTKIT / "expected" / "event.schema.json"
    bad_event = {
        "schema_version": 1,
        "event": "PreToolUse",
        "tool_name": "run_subagent",
        "profile": "p",
        "is_background": False,
        "success": None,
        "observed_at": "now",
        "extra": "not allowed",
    }
    errors = validate_file(bad_event, schema_path)
    assert errors


def test_sidecar_event_consumption(contract_pass):
    summary = json.loads((contract_pass / "summary.json").read_text())
    assert summary["total_events"] >= 1
    assert summary["last_event"]["tool_name"] == "run_subagent"


def test_existing_hook_exact_byte_restoration():
    original = EXISTING_HOOKS.read_bytes()
    rc, errors, runtime_root = _run_contract(existing_hooks=True, keep=True)
    assert rc == 0, "\n".join(errors)
    try:
        restored = (runtime_root / "canary" / ".devin" / "hooks.json").read_bytes()
        assert restored == original
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_profile_cleanup(contract_pass):
    manifest = json.loads((contract_pass / "manifest.json").read_text())
    canary = Path(manifest["canary"])
    profile_dir = canary / ".devin" / "agents" / manifest["profile_id"]
    assert not profile_dir.exists()


def test_no_writes_outside_allowed_roots(contract_pass):
    base_dir = contract_pass.parent.parent
    manifest = json.loads((contract_pass / "manifest.json").read_text())
    runtime_root = Path(manifest["summary_path"]).parent.parent
    canary = Path(manifest["canary"])
    for root in (runtime_root, canary):
        for path in root.rglob("*"):
            assert path.resolve().is_relative_to(root.resolve())
    for path in base_dir.rglob("*"):
        if path.is_file() or path.is_dir():
            assert path.resolve().is_relative_to(runtime_root.resolve())


def test_secret_scan_of_generated_artifacts(contract_pass):
    runtime_root = contract_pass.parent
    redact = str(runtime_root.resolve())
    patterns = [
        re.compile(r"\bapi[_-]?key\b", re.IGNORECASE),
        re.compile(r"\btoken\b", re.IGNORECASE),
        re.compile(r"\bsecret\b", re.IGNORECASE),
        re.compile(r"\bpassword\b", re.IGNORECASE),
        re.compile(r"\bcredential\b", re.IGNORECASE),
        re.compile(r"\bbearer\b", re.IGNORECASE),
    ]
    for path in contract_pass.rglob("*"):
        if path.is_file() and path.stat().st_size < 1024 * 1024:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            text = text.replace(redact, "REDACTED_PATH")
            for pattern in patterns:
                assert not pattern.search(text), (
                    f"{path.name} contains secret-like string matching {pattern.pattern!r}"
                )


def test_tty_inheritance():
    rc, errors, _ = _run_contract(tty=True)
    assert rc == 0, "\n".join(errors)


def test_process_overlap():
    rc, errors, runtime_root = _run_contract(process_overlap=True, keep=True)
    try:
        assert rc == 0, "\n".join(errors)
        run_dirs = [p for p in runtime_root.iterdir() if p.is_dir() and p.name != "canary"]
        assert run_dirs
        run_dir = run_dirs[0]
        lifecycle = (run_dir / "lifecycle.log").read_text(encoding="utf-8")
        for label in ("supervisor_start", "sidecar_start", "child_start"):
            assert label in lifecycle
        for name in ("supervisor.pid", "sidecar.pid", "child.pid"):
            assert (run_dir / name).exists()
        record = json.loads((run_dir / "fake-devin.record.json").read_text())
        assert record.get("sidecar_total_events", 0) >= 1
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_lifecycle_order(contract_pass):
    log_path = contract_pass / "lifecycle.log"
    assert log_path.exists()
    lines = [
        line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    labels = [line.split()[0] for line in lines]
    expected = [
        "supervisor_start",
        "sidecar_start",
        "child_start",
        "child_end",
        "sidecar_stop",
        "supervisor_end",
    ]
    for label in expected:
        assert label in labels
    for i in range(len(expected) - 1):
        assert labels.index(expected[i]) < labels.index(expected[i + 1])


def test_sidecar_consumed_event_before_child_exit(contract_pass):
    record = json.loads((contract_pass / "fake-devin.record.json").read_text())
    assert record.get("sidecar_total_events", 0) >= 1


def test_hook_is_fail_open():
    hook_script = (
        REPO_ROOT / "experiments" / "native-launcher-python" / "native_launcher" / "hook.py"
    )
    # Malformed input and missing events dir must not block Devin.
    result = subprocess.run(
        ["python3", str(hook_script)],
        input="not-json",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.returncode == 0
    # Oversized input must also exit zero.
    result = subprocess.run(
        ["python3", str(hook_script)],
        input="x" * (1024 * 1024 + 1),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.returncode == 0


def test_profile_name_matches_directory(contract_pass):
    manifest = json.loads((contract_pass / "manifest.json").read_text())
    record = json.loads((contract_pass / "fake-devin.record.json").read_text())
    profile_id = manifest["profile_id"]
    assert record["profile_id"] == profile_id
    agents_dir = Path(manifest["canary"]) / ".devin" / "agents"
    if not agents_dir.exists():
        return
    found = [p for p in agents_dir.iterdir() if p.is_dir() and p.name == profile_id]
    assert not found, "Profile directory still exists after cleanup"


def test_complete_file_modes(contract_pass):
    for name, mode in [
        ("supervisor.pid", 0o600),
        ("sidecar.pid", 0o600),
        ("child.pid", 0o600),
        ("sidecar-ready", 0o600),
        ("lifecycle.log", 0o600),
        ("manifest.json", 0o600),
        ("summary.json", 0o600),
        ("event.schema.json", 0o600),
        ("fake-devin.record.json", 0o600),
        ("hook", 0o700),
    ]:
        path = contract_pass / name
        assert path.exists(), f"{name} missing"
        assert stat.S_IMODE(path.stat().st_mode) == mode, f"{name} mode mismatch"
    for event_file in (contract_pass / "events").glob("*.json"):
        assert stat.S_IMODE(event_file.stat().st_mode) == 0o600


def test_event_schema_accepts_tool_and_session_events_and_rejects_extra():
    schema_path = TESTKIT / "expected" / "event.schema.json"
    tool_event = {
        "schema_version": 1,
        "event": "PostToolUse",
        "tool_name": "run_subagent",
        "profile": "goal-devin-worker-abc123",
        "is_background": False,
        "success": True,
        "observed_at": "2024-01-01T00:00:00+00:00",
    }
    assert not schema_validator.validate_file(tool_event, schema_path)

    session_event = {
        "schema_version": 1,
        "event": "SessionStart",
        "tool_name": None,
        "profile": None,
        "is_background": None,
        "success": None,
        "observed_at": "2024-01-01T00:00:00+00:00",
    }
    assert not schema_validator.validate_file(session_event, schema_path)

    bad_event = dict(tool_event)
    bad_event["extra_field"] = "not allowed"
    assert schema_validator.validate_file(bad_event, schema_path)


def test_summary_schema_accepts_initial_and_final():
    schema_path = TESTKIT / "expected" / "summary.schema.json"
    initial = {
        "schema_version": 1,
        "run_id": "a" * 32,
        "total_events": 0,
        "consumed_event_ids": [],
        "tools": {},
        "profiles": {},
        "last_event": None,
    }
    assert not schema_validator.validate_file(initial, schema_path)

    final = {
        "schema_version": 1,
        "run_id": "a" * 32,
        "total_events": 1,
        "consumed_event_ids": ["event1"],
        "tools": {"run_subagent": 1},
        "profiles": {"goal-devin-worker-abc123": 1},
        "last_event": {
            "tool_name": "run_subagent",
            "profile": "goal-devin-worker-abc123",
            "is_background": False,
            "success": True,
            "observed_at": "2024-01-01T00:00:00+00:00",
        },
    }
    assert not schema_validator.validate_file(final, schema_path)

    bad = dict(final)
    bad["extra"] = "field"
    assert schema_validator.validate_file(bad, schema_path)


def test_manifest_schema_is_closed_and_complete(contract_pass):
    manifest = json.loads((contract_pass / "manifest.json").read_text())
    schema_path = TESTKIT / "expected" / "manifest.schema.json"
    assert not schema_validator.validate_file(manifest, schema_path)


def test_contract_dir_is_required_and_validated():
    base_dir = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-contract-dir-"))
    runtime_root = base_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    try:
        cmd = [
            "python3",
            str(RUN_CONTRACT),
            "--candidate",
            str(CANDIDATE),
            "--devin-bin",
            str(FAKE_DEVIN),
            "--canary-fixture",
            str(CANARY_FIXTURE),
            "--runtime-root",
            str(runtime_root),
            "--base-dir",
            str(base_dir),
            "--contract-dir",
            str(base_dir / "empty"),
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert result.returncode != 0
        assert "contract-dir" in result.stderr.lower() or "schema" in result.stderr.lower()
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_canary_symlink_escape_is_rejected(tmp_path):
    from native_launcher.utils import safe_path_under

    base = tmp_path / "base"
    base.mkdir()
    runtime_root = base / "runtime"
    runtime_root.mkdir()
    outside = base / "outside"
    outside.mkdir()
    canary = runtime_root / "canary"
    canary.symlink_to(outside)
    assert not safe_path_under(runtime_root, canary)


def test_agents_symlink_escape_is_rejected(tmp_path):
    from native_launcher.utils import safe_path_under

    canary = tmp_path / "canary"
    canary.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    agents = canary / ".devin" / "agents"
    agents.parent.mkdir(parents=True)
    agents.symlink_to(outside)
    profile_dir = agents / "goal-devin-worker-123"
    assert not safe_path_under(canary, profile_dir)


def test_production_source_tree_unchanged():
    result = subprocess.run(
        ["git", "status", "--short", "--", "src/", "tests/", "pyproject.toml"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
