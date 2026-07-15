"""Deterministic candidate tests for the native launcher happy path."""

import json
import os
import re
import shutil
import stat
import subprocess
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


def _run_contract(
    *,
    tty: bool = False,
    existing_hooks: bool = False,
    keep: bool = False,
    extra_env: dict | None = None,
) -> tuple[int, list[str], Path | None]:
    runtime_root = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-test-"))
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
    ]
    if existing_hooks:
        cmd.extend(["--existing-hooks", str(EXISTING_HOOKS)])
    if tty:
        cmd.append("--tty")
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
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
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


def test_exact_argv(contract_pass):
    record = json.loads((contract_pass / "fake-devin.record.json").read_text())
    assert "--model" in record["argv"]
    assert "--permission-mode" in record["argv"]
    assert "swe-1-7" in record["argv"]
    assert "accept-edits" in record["argv"]


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
    manifest = json.loads((contract_pass / "manifest.json").read_text())
    runtime_root = Path(manifest["summary_path"]).parent.parent
    canary = Path(manifest["canary"])
    for root in (runtime_root, canary):
        for path in root.rglob("*"):
            assert path.resolve().is_relative_to(root.resolve())


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
