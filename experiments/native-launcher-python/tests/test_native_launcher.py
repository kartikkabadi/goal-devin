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
import time
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CANDIDATE = REPO_ROOT / "experiments" / "native-launcher-python" / "goal-devin-dev"
TESTKIT = REPO_ROOT / "experiments" / "native-launcher-testkit"
FAKE_DEVIN = TESTKIT / "fake-devin"
RUN_CONTRACT = TESTKIT / "run-contract.py"
CANARY_FIXTURE = TESTKIT / "fixtures" / "canary"
EXISTING_HOOKS = TESTKIT / "fixtures" / "existing-hooks" / ".devin" / "hooks.v1.json"

_spec = importlib.util.spec_from_file_location(
    "schema_validator", str(TESTKIT / "schema_validator.py")
)
schema_validator = importlib.util.module_from_spec(_spec)
sys.modules["schema_validator"] = schema_validator
_spec.loader.exec_module(schema_validator)


def _find_run_dir(runtime_root: Path) -> Path | None:
    hex_chars = set("0123456789abcdef")
    for entry in runtime_root.iterdir():
        name = entry.name
        if entry.is_dir() and len(name) == 32 and all(c in hex_chars for c in name.lower()):
            return entry
    return None


def _run_contract(
    *,
    candidate: Path | None = None,
    canary_fixture: Path | None = None,
    existing_hooks: bool | str | Path = False,
    tty: bool = False,
    process_overlap: bool = False,
    no_poll: bool = False,
    stress: bool = False,
    keep: bool = False,
    extra_env: dict | None = None,
    contract_dir: Path | None = None,
    timeout: float | None = None,
    devin_bin: Path | None = None,
    sentinel: bool | str = False,
) -> tuple[int, list[str], Path]:
    """Run the shared contract and return (rc, error_lines, runtime_root)."""
    base_dir = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-test-"))
    runtime_root = base_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    if sentinel:
        sentinel_path = base_dir / "sentinel.txt"
        sentinel_path.write_text(
            sentinel if isinstance(sentinel, str) else "do not modify or delete",
            encoding="utf-8",
        )
    chosen_candidate = candidate or CANDIDATE
    chosen_canary = canary_fixture or CANARY_FIXTURE
    chosen_contract_dir = contract_dir or TESTKIT
    chosen_devin_bin = devin_bin or FAKE_DEVIN
    existing_hooks_path: Path | None = None
    if isinstance(existing_hooks, (str, Path)) and existing_hooks:
        existing_hooks_path = Path(existing_hooks)
    elif existing_hooks:
        existing_hooks_path = EXISTING_HOOKS
    cmd = [
        "python3",
        str(RUN_CONTRACT),
        "--candidate",
        str(chosen_candidate),
        "--devin-bin",
        str(chosen_devin_bin),
        "--contract-dir",
        str(chosen_contract_dir),
        "--canary-fixture",
        str(chosen_canary),
        "--runtime-root",
        str(runtime_root),
        "--base-dir",
        str(base_dir),
    ]
    if existing_hooks_path:
        cmd.extend(["--existing-hooks", str(existing_hooks_path)])
    if tty:
        cmd.append("--tty")
    if process_overlap:
        cmd.append("--process-overlap")
    if no_poll:
        cmd.append("--no-poll")
    if stress:
        cmd.append("--stress")
    if keep:
        cmd.append("--keep-artifacts")
    if timeout is not None:
        cmd.extend(["--timeout", str(timeout)])
    env = os.environ.copy()
    env["GOAL_DEVIN_FAKE_EXIT_CODE"] = "0"
    env["GOAL_DEVIN_FAKE_SLEEP"] = "0.1"
    if extra_env:
        env.update(extra_env)
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        errors = [line.strip() for line in result.stderr.splitlines() if line.startswith("  - ")]
        return result.returncode, errors, runtime_root
    finally:
        if not keep:
            shutil.rmtree(base_dir, ignore_errors=True)


@pytest.fixture
def contract_pass(tmp_path):
    """Run the contract and return the runtime directory for assertions."""
    rc, errors, runtime_root = _run_contract(keep=True)
    assert rc == 0, "\n".join(errors)
    run_dir = _find_run_dir(runtime_root)
    assert run_dir, f"No run directory found in {runtime_root}"
    yield run_dir
    shutil.rmtree(runtime_root.parent, ignore_errors=True)


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


def test_schema_conformance_corpus():
    """Run the shared schema conformance corpus through both validators.

    Compare acceptance/rejection booleans only; exact error wording and order are
    intentionally not compared so the corpus is language-neutral.
    """
    from native_launcher.schema import (
        validate as runtime_validate,
        validate_file as runtime_validate_file,
    )

    corpus_path = TESTKIT / "fixtures" / "schema-conformance" / "cases.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

    malformed_schema = corpus_path.parent / corpus["malformed_schema_file"]
    with pytest.raises(json.JSONDecodeError):
        schema_validator.validate_file({}, malformed_schema)
    with pytest.raises(json.JSONDecodeError):
        runtime_validate_file({}, malformed_schema)

    for case in corpus["cases"]:
        schema = case["schema"]
        for value in case["valid"]:
            shared = schema_validator.validate(value, schema)
            runtime = runtime_validate(value, schema)
            assert not shared, (
                f"{case['name']} valid: shared validator rejected {value!r}: {shared}"
            )
            assert not runtime, (
                f"{case['name']} valid: runtime validator rejected {value!r}: {runtime}"
            )
        for value in case["invalid"]:
            shared = schema_validator.validate(value, schema)
            runtime = runtime_validate(value, schema)
            assert shared, f"{case['name']} invalid: shared validator accepted {value!r}"
            assert runtime, f"{case['name']} invalid: runtime validator accepted {value!r}"


def test_sidecar_event_consumption(contract_pass):
    summary = json.loads((contract_pass / "summary.json").read_text())
    assert summary["total_events"] >= 1
    assert summary["last_event"]["tool_name"] == "run_subagent"


def test_existing_hook_exact_byte_restoration():
    original = EXISTING_HOOKS.read_bytes()
    rc, errors, runtime_root = _run_contract(existing_hooks=True, keep=True)
    assert rc == 0, "\n".join(errors)
    try:
        restored = (runtime_root / "canary" / ".devin" / "hooks.v1.json").read_bytes()
        assert restored == original
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_profile_cleanup(contract_pass):
    manifest = json.loads((contract_pass / "manifest.json").read_text())
    canary = Path(manifest["canary"])
    profile_dir = canary / ".devin" / "agents" / manifest["profile_id"]
    assert not profile_dir.exists()


MANAGED_BASE_MARKER = "GOAL_DEVIN_CONTRACT_BASE"


def test_no_writes_outside_allowed_roots(contract_pass):
    base_dir = contract_pass.parent.parent
    manifest = json.loads((contract_pass / "manifest.json").read_text())
    runtime_root = Path(manifest["summary_path"]).parent.parent
    canary = Path(manifest["canary"])
    fixture_symlinks = {
        (canary / src.relative_to(CANARY_FIXTURE)).resolve()
        for src in CANARY_FIXTURE.rglob("*")
        if src.is_symlink()
    }
    for root in (runtime_root, canary):
        for path in root.rglob("*"):
            if path.is_symlink() and path.resolve() in fixture_symlinks:
                continue
            assert path.resolve().is_relative_to(root.resolve())
    for path in base_dir.rglob("*"):
        if path.is_symlink() and path.resolve() in fixture_symlinks:
            continue
        if path.is_file() or path.is_dir():
            if path.name == MANAGED_BASE_MARKER and path.parent == base_dir:
                continue
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
        run_dir = _find_run_dir(runtime_root)
        assert run_dir
        lifecycle = (run_dir / "lifecycle.log").read_text(encoding="utf-8")
        for label in ("supervisor_start", "sidecar_start", "child_start"):
            assert label in lifecycle
        for name in ("supervisor.pid", "sidecar.pid", "child.pid"):
            assert (run_dir / name).exists()
        record = json.loads((run_dir / "fake-devin.record.json").read_text())
        assert record.get("sidecar_total_events", 0) >= 1
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


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
        ("limits.json", 0o600),
        ("limits.schema.json", 0o600),
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


def test_ensure_private_dir_creates_with_700_and_preserves_existing_modes(tmp_path):
    from native_launcher.utils import ensure_private_dir

    # New directories are created with 0o700.
    new_leaf = tmp_path / "a" / "b" / "c"
    created = ensure_private_dir(new_leaf, mode=0o700)
    assert new_leaf.exists()
    assert stat.S_IMODE(new_leaf.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o700 for p in created)

    # Pre-existing directories keep their original mode and are not in the returned list.
    existing = tmp_path / "existing"
    existing.mkdir()
    os.chmod(existing, 0o755)
    child = existing / "child"
    created = ensure_private_dir(child, mode=0o700)
    assert child.exists()
    assert stat.S_IMODE(child.stat().st_mode) == 0o700
    assert stat.S_IMODE(existing.stat().st_mode) == 0o755
    assert existing not in created


def _make_canary_fixture_with_symlink(link_name: str, target: Path) -> Path:
    """Return a temporary canary fixture where *link_name* is a symlink to *target*."""
    fixture = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-symlink-fixture-"))
    canary = fixture / "canary"
    canary.mkdir(parents=True)
    for item in CANARY_FIXTURE.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.copytree(item, canary / item.name, symlinks=True)
        elif item.is_symlink():
            (canary / item.name).symlink_to(os.readlink(item))
        else:
            shutil.copy2(item, canary / item.name)
    parts = Path(link_name).parts
    parent = canary
    for part in parts[:-1]:
        parent = parent / part
        parent.mkdir(parents=True, exist_ok=True)
    link = parent / parts[-1]
    link.symlink_to(target, target_is_directory=target.is_dir())
    return fixture


def test_hooks_json_not_treated_as_standalone():
    """Candidate must ignore .devin/hooks.json and only use .devin/hooks.v1.json."""
    base = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-hooks-json-"))
    canary_fixture = base / "canary"
    shutil.copytree(CANARY_FIXTURE, canary_fixture, symlinks=True)
    devin_dir = canary_fixture / ".devin"
    devin_dir.mkdir(parents=True, exist_ok=True)
    seed = {
        "PreToolUse": [
            {
                "matcher": "seed",
                "hooks": [{"type": "command", "command": "/bin/seed", "timeout": 5}],
            }
        ]
    }
    (devin_dir / "hooks.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")
    try:
        rc, errors, runtime_root = _run_contract(
            canary_fixture=canary_fixture, existing_hooks=True, keep=True
        )
        assert rc == 0, "\n".join(errors)
        try:
            hooks_v1 = (runtime_root / "canary" / ".devin" / "hooks.v1.json").read_bytes()
            assert b"/bin/seed" not in hooks_v1, "Candidate merged hooks.json into hooks.v1.json"
            assert hooks_v1 == EXISTING_HOOKS.read_bytes()
        finally:
            shutil.rmtree(runtime_root.parent, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_exec_replacement_is_rejected():
    """A candidate that execs fake-devin must be rejected because PIDs are not distinct."""
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "exec-candidate.py",
        process_overlap=True,
    )
    assert rc != 0
    assert any(
        "duplicate" in e.lower() or "distinct" in e.lower() or "supervisor.pid" in e.lower()
        for e in errors
    )


def test_outside_write_candidate_is_rejected():
    """A candidate that writes a sibling file under the base dir must be rejected."""
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "outside-write-candidate.py",
    )
    assert rc != 0
    assert any("outside" in e.lower() for e in errors)


def test_canary_devin_dir_symlink_rejected_by_candidate():
    fixture = _make_canary_fixture_with_symlink(".devin", Path(tempfile.mkdtemp()))
    sentinel = Path(tempfile.mkdtemp()) / "sentinel.txt"
    sentinel.write_text("preserve me", encoding="utf-8")
    try:
        # Point the .devin symlink at a directory containing the sentinel.
        (fixture / "canary" / ".devin").unlink()
        (fixture / "canary" / ".devin").symlink_to(sentinel.parent, target_is_directory=True)
        original = sentinel.read_bytes()
        rc, errors, _ = _run_contract(canary_fixture=fixture / "canary")
        assert rc != 0
        assert sentinel.read_bytes() == original
        assert any("symlink" in e.lower() for e in errors)
    finally:
        shutil.rmtree(fixture, ignore_errors=True)
        shutil.rmtree(sentinel.parent, ignore_errors=True)


def test_canary_agents_dir_symlink_rejected_by_candidate():
    outside = Path(tempfile.mkdtemp())
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("preserve me", encoding="utf-8")
    fixture = _make_canary_fixture_with_symlink(".devin/agents", outside)
    try:
        original = sentinel.read_bytes()
        rc, errors, _ = _run_contract(canary_fixture=fixture / "canary")
        assert rc != 0
        assert sentinel.read_bytes() == original
        assert any("symlink" in e.lower() for e in errors)
    finally:
        shutil.rmtree(fixture, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_canary_hooks_v1_symlink_rejected_by_candidate():
    outside = Path(tempfile.mkdtemp())
    sentinel = outside / "hooks.v1.json"
    sentinel.write_text('{"PreToolUse": []}', encoding="utf-8")
    fixture = _make_canary_fixture_with_symlink(".devin/hooks.v1.json", sentinel)
    try:
        original = sentinel.read_bytes()
        rc, errors, _ = _run_contract(canary_fixture=fixture / "canary")
        assert rc != 0
        assert sentinel.read_bytes() == original
        assert any("symlink" in e.lower() for e in errors)
    finally:
        shutil.rmtree(fixture, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_invalid_event_schema_rejected_at_startup():
    bad_contract = Path(tempfile.mkdtemp())
    (bad_contract / "expected").mkdir(parents=True)
    (bad_contract / "expected" / "event.schema.json").write_text("not json", encoding="utf-8")
    try:
        rc, errors, _ = _run_contract(contract_dir=bad_contract)
        assert rc != 0
        assert any("schema" in e.lower() for e in errors)
    finally:
        shutil.rmtree(bad_contract, ignore_errors=True)


def test_runtime_root_outside_base_dir_rejected():
    base_dir = Path(tempfile.mkdtemp())
    runtime_root = Path(tempfile.mkdtemp()) / "runtime"
    runtime_root.mkdir(parents=True)
    try:
        cmd = [
            "python3",
            str(RUN_CONTRACT),
            "--candidate",
            str(CANDIDATE),
            "--devin-bin",
            str(FAKE_DEVIN),
            "--contract-dir",
            str(TESTKIT),
            "--canary-fixture",
            str(CANARY_FIXTURE),
            "--runtime-root",
            str(runtime_root),
            "--base-dir",
            str(base_dir),
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert result.returncode != 0
        assert "runtime-root" in result.stderr.lower()
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


@pytest.mark.parametrize(
    "hooks_content",
    [
        "{ not valid json",
        "[]",
        '"scalar"',
        '{"PreToolUse": {"matcher": "", "hooks": []}}',
        '{"PreToolUse": "not-a-list"}',
    ],
    ids=[
        "malformed_json",
        "top_level_array",
        "top_level_scalar",
        "non_list_entry",
        "non_list_event",
    ],
)
def test_malformed_hooks_in_canary_fixture_rejected(hooks_content):
    fixture = Path(tempfile.mkdtemp(prefix="goal-devin-malformed-hooks-"))
    shutil.copytree(CANARY_FIXTURE, fixture, symlinks=True, dirs_exist_ok=True)
    hooks_file = fixture / ".devin" / "hooks.v1.json"
    hooks_file.parent.mkdir(parents=True, exist_ok=True)
    hooks_file.write_text(hooks_content, encoding="utf-8")
    original_mode = stat.S_IMODE(hooks_file.stat().st_mode)
    original_bytes = hooks_file.read_bytes()

    try:
        rc, errors, runtime_root = _run_contract(canary_fixture=fixture, keep=True)
        assert rc != 0, "expected candidate to reject malformed existing hooks"
        assert any(
            "json" in e.lower() or "object" in e.lower() or "list" in e.lower() for e in errors
        )
        # Source fixture must be preserved exactly.
        assert hooks_file.read_bytes() == original_bytes
        assert stat.S_IMODE(hooks_file.stat().st_mode) == original_mode
        canary = runtime_root / "canary"
        assert not (canary / ".devin" / "agents").exists(), "profile must not be created"
    finally:
        shutil.rmtree(fixture, ignore_errors=True)
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


@pytest.mark.parametrize(
    "hooks_content",
    [
        "{ not valid json",
        "[]",
        '{"PreToolUse": "not-a-list"}',
    ],
    ids=["malformed_json", "top_level_array", "non_list_event"],
)
def test_malformed_existing_hooks_argument_rejected(hooks_content):
    tmp_hooks = Path(tempfile.mktemp(prefix="malformed-hooks-", suffix=".json"))
    tmp_hooks.write_text(hooks_content, encoding="utf-8")
    original_mode = stat.S_IMODE(tmp_hooks.stat().st_mode)
    original_bytes = tmp_hooks.read_bytes()

    try:
        rc, errors, runtime_root = _run_contract(existing_hooks=tmp_hooks, keep=True)
        assert rc != 0, "expected candidate to reject malformed --existing-hooks"
        assert any(
            "json" in e.lower() or "object" in e.lower() or "list" in e.lower() for e in errors
        )
        # Source file must be preserved exactly.
        assert tmp_hooks.read_bytes() == original_bytes
        assert stat.S_IMODE(tmp_hooks.stat().st_mode) == original_mode
        canary = runtime_root / "canary"
        assert not (canary / ".devin" / "agents").exists(), "profile must not be created"
    finally:
        tmp_hooks.unlink(missing_ok=True)
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_pre_existing_canary_hooks_and_user_agent_preserved():
    """A canary with a pre-existing hook and a user-owned agent must survive untouched."""
    fixture = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-pre-existing-"))
    canary = fixture / "canary"
    canary.mkdir(parents=True)
    devin_dir = canary / ".devin"
    devin_dir.mkdir()
    agents_dir = devin_dir / "agents"
    agents_dir.mkdir()
    user_dir = agents_dir / "user-agent"
    user_dir.mkdir()
    user_agent = user_dir / "AGENT.md"
    user_agent.write_text("---\nname: user-agent\n---\n", encoding="utf-8")
    original_devin_mode = stat.S_IMODE(devin_dir.stat().st_mode)
    original_agents_mode = stat.S_IMODE(agents_dir.stat().st_mode)
    original_user_dir_mode = stat.S_IMODE(user_dir.stat().st_mode)
    hooks_file = devin_dir / "hooks.v1.json"
    hooks_file.write_text(
        json.dumps(
            {
                "PreToolUse": [
                    {
                        "matcher": "user",
                        "hooks": [{"type": "command", "command": "/bin/user", "timeout": 1}],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    original_hooks_bytes = hooks_file.read_bytes()
    original_hooks_mode = stat.S_IMODE(hooks_file.stat().st_mode)
    original_agent_bytes = user_agent.read_bytes()

    try:
        rc, errors, runtime_root = _run_contract(canary_fixture=canary, keep=True)
        assert rc == 0, "\n".join(errors)
        run_dir = _find_run_dir(runtime_root)
        assert run_dir
        manifest = json.loads((run_dir / "manifest.json").read_text())
        canary_out = runtime_root / "canary"

        # Pre-existing files and directories are preserved byte-for-byte.
        assert (canary_out / ".devin" / "hooks.v1.json").read_bytes() == original_hooks_bytes
        assert (
            stat.S_IMODE((canary_out / ".devin" / "hooks.v1.json").stat().st_mode)
            == original_hooks_mode
        )
        assert (
            canary_out / ".devin" / "agents" / "user-agent" / "AGENT.md"
        ).read_bytes() == original_agent_bytes

        # Pre-existing directory modes are preserved.
        assert stat.S_IMODE((canary_out / ".devin").stat().st_mode) == original_devin_mode
        assert (
            stat.S_IMODE((canary_out / ".devin" / "agents").stat().st_mode) == original_agents_mode
        )
        assert (
            stat.S_IMODE((canary_out / ".devin" / "agents" / "user-agent").stat().st_mode)
            == original_user_dir_mode
        )

        # Ownership must not claim user/project directories or borrowed files.
        owned_paths = {Path(p).resolve() for p in manifest["owned_paths"]}
        owned_roots = {Path(p).resolve() for p in manifest["owned_roots"]}
        assert (canary_out / ".devin").resolve() not in owned_roots
        assert (canary_out / ".devin" / "agents").resolve() not in owned_roots
        assert (canary_out / ".devin" / "hooks.v1.json").resolve() not in owned_paths

        # The generated Goal Devin profile is the only owned subtree under agents.
        profile_path = Path(manifest["profile_path"]).resolve()
        assert profile_path in owned_paths
        profile_dir = profile_path.parent.resolve()
        assert profile_dir in owned_roots
        assert profile_dir.is_relative_to((canary_out / ".devin" / "agents").resolve())
    finally:
        shutil.rmtree(fixture, ignore_errors=True)
        if "runtime_root" in locals():
            shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_runner_timeout_kills_hanging_candidate():
    """The shared runner must reap a candidate that hangs without a run directory."""
    start = time.monotonic()
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "hang-candidate.py",
        timeout=2,
    )
    elapsed = time.monotonic() - start
    assert rc != 0
    assert elapsed < 6, f"runner did not fail within the timeout bound ({elapsed:.1f}s)"
    assert elapsed >= 1.5, "runner should have waited for the timeout"


def test_base_dir_sentinel_preserved():
    """A pre-existing file under --base-dir must survive the run and the runner must not
    remove the caller-supplied base directory."""
    base_dir = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-base-sentinel-"))
    sentinel = base_dir / "sentinel.txt"
    sentinel.write_text("do not delete", encoding="utf-8")
    runtime_root = base_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3",
        str(RUN_CONTRACT),
        "--candidate",
        str(CANDIDATE),
        "--devin-bin",
        str(FAKE_DEVIN),
        "--contract-dir",
        str(TESTKIT),
        "--canary-fixture",
        str(CANARY_FIXTURE),
        "--runtime-root",
        str(runtime_root),
        "--base-dir",
        str(base_dir),
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert result.returncode == 0, result.stderr
        assert sentinel.read_text(encoding="utf-8") == "do not delete"
        # The runner-created runtime root is removed; the caller-owned base dir remains.
        assert not runtime_root.exists()
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_no_poll_final_drain():
    """With --no-poll, fake-devin exits immediately; the sidecar still consumes the event
    during its final drain after supervisor shutdown."""
    rc, errors, runtime_root = _run_contract(no_poll=True, keep=True)
    assert rc == 0, "\n".join(errors)
    try:
        run_dir = _find_run_dir(runtime_root)
        assert run_dir
        record = json.loads((run_dir / "fake-devin.record.json").read_text())
        # The fake child did not poll the summary before exiting.
        assert record.get("sidecar_total_events", -1) == 0
        summary = json.loads((run_dir / "summary.json").read_text())
        assert summary.get("total_events", 0) >= 1
        assert summary["last_event"]["tool_name"] == "run_subagent"
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_lifecycle_log_requires_private_parent(tmp_path):
    """Lifecycle logging must fail if the parent directory is not 0700."""
    from native_launcher.supervisor import _lifecycle_log

    public = tmp_path / "public"
    public.mkdir()
    os.chmod(public, 0o755)
    with pytest.raises(RuntimeError, match="0o700"):
        _lifecycle_log(public / "log", "test")


def test_hook_enforces_runtime_limits():
    """hook.py truncates/limits fields and always exits zero."""
    hook_script = (
        REPO_ROOT / "experiments" / "native-launcher-python" / "native_launcher" / "hook.py"
    )
    runtime_dir = Path(tempfile.mkdtemp(prefix="goal-devin-hook-limits-"))
    events_dir = runtime_dir / "events"
    try:
        shutil.copyfile(TESTKIT / "limits.json", runtime_dir / "limits.json")
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "run_subagent",
            "tool_input": {"profile": "goal-devin-worker-abc", "is_background": False},
            "tool_response": {"success": True, "output": "<redacted>"},
        }
        result = subprocess.run(
            [sys.executable, str(hook_script), str(events_dir)],
            input=json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert result.returncode == 0
        json_files = list(events_dir.glob("*.json"))
        assert len(json_files) == 1
        event = json.loads(json_files[0].read_text(encoding="utf-8"))
        limits = json.loads((TESTKIT / "limits.json").read_text(encoding="utf-8"))
        assert event["tool_name"] == "run_subagent"
        assert event["profile"] == "goal-devin-worker-abc"
        assert len(json.dumps(event).encode("utf-8")) <= limits["max_event_json_bytes"]

        # A huge tool_name is truncated to the limit and the hook still exits zero.
        oversized = payload.copy()
        oversized["tool_name"] = "x" * (limits["max_tool_name_length"] + 100)
        result = subprocess.run(
            [sys.executable, str(hook_script), str(events_dir)],
            input=json.dumps(oversized),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert result.returncode == 0
        events = list(events_dir.glob("*.json"))
        # The first event was consumed by the sidecar in a real run; here we just
        # check that the second oversized invocation produced a bounded event.
        assert events
        last = json.loads(events[-1].read_text(encoding="utf-8"))
        assert isinstance(last["tool_name"], str)
        assert len(last["tool_name"]) <= limits["max_tool_name_length"]
    finally:
        shutil.rmtree(runtime_dir, ignore_errors=True)


def test_sidecar_enforces_runtime_limits():
    """The sidecar caps distinct tools/profiles and trims old event files."""
    from native_launcher.sidecar import Sidecar

    runtime_dir = Path(tempfile.mkdtemp(prefix="goal-devin-sidecar-limits-"))
    events_dir = runtime_dir / "events"
    events_dir.mkdir(parents=True)
    shutil.copyfile(TESTKIT / "expected" / "event.schema.json", runtime_dir / "event.schema.json")
    shutil.copyfile(TESTKIT / "expected" / "limits.schema.json", runtime_dir / "limits.schema.json")
    shutil.copyfile(TESTKIT / "limits.json", runtime_dir / "limits.json")

    def make_event(tool_name: str, profile: str, event_id: str) -> dict:
        return {
            "schema_version": 1,
            "event": "PostToolUse",
            "tool_name": tool_name,
            "profile": profile,
            "is_background": False,
            "success": True,
            "observed_at": "2024-01-01T00:00:00+00:00",
        }

    try:
        limits = json.loads((TESTKIT / "limits.json").read_text(encoding="utf-8"))
        sidecar = Sidecar(runtime_dir)
        sidecar.events_dir = events_dir

        # Create more retained files than the limit.
        total = limits["max_retained_event_files"] + 25
        for i in range(total):
            eid = f"{i:04d}{'a' * 24}"
            path = events_dir / f"{eid}.json"
            path.write_text(
                json.dumps(make_event(f"tool-{i}", f"profile-{i}", eid), indent=2), encoding="utf-8"
            )
            # Artificially stagger mtimes so the trim order is deterministic.
            os.utime(path, (i, i))

        sidecar._drain()
        json_files = list(events_dir.glob("*.json"))
        assert len(json_files) <= limits["max_retained_event_files"]
        assert sidecar.total_events == total
        assert len(sidecar.tools) == limits["max_distinct_tools"]
        assert len(sidecar.profiles) == limits["max_distinct_profiles"]

        # Recent IDs in the summary are capped.
        summary_path = runtime_dir / "summary.json"
        assert summary_path.exists()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert len(summary["consumed_event_ids"]) <= limits["max_recent_event_ids"]
        assert summary["total_events"] == total

        # An oversized event file is dropped without affecting Devin.
        big_path = events_dir / "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz.json"
        big_path.write_bytes(b"x" * (limits["max_event_json_bytes"] + 1))
        before = sidecar.total_events
        sidecar._drain()
        assert sidecar.total_events == before
    finally:
        shutil.rmtree(runtime_dir, ignore_errors=True)


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


def test_limits_required_and_validated():
    """A contract directory without limits.json or with a malformed one is rejected
    before any runtime/project artifacts are created."""
    bad_contract = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-bad-limits-"))
    (bad_contract / "expected").mkdir(parents=True)
    shutil.copyfile(
        TESTKIT / "expected" / "event.schema.json", bad_contract / "expected" / "event.schema.json"
    )
    shutil.copyfile(
        TESTKIT / "expected" / "summary.schema.json",
        bad_contract / "expected" / "summary.schema.json",
    )
    shutil.copyfile(
        TESTKIT / "expected" / "manifest.schema.json",
        bad_contract / "expected" / "manifest.schema.json",
    )
    shutil.copyfile(
        TESTKIT / "expected" / "limits.schema.json",
        bad_contract / "expected" / "limits.schema.json",
    )
    try:
        rc, errors, _ = _run_contract(contract_dir=bad_contract)
        assert rc != 0
        assert any("limits" in e.lower() for e in errors), errors
    finally:
        shutil.rmtree(bad_contract, ignore_errors=True)


@pytest.mark.parametrize(
    "limits_data, expected_substring",
    [
        ([], "JSON object"),
        ({"max_tool_name_length": True}, "positive integer"),
        ({"max_tool_name_length": "128"}, "positive integer"),
        ({"max_tool_name_length": 128.5}, "positive integer"),
        ({"max_tool_name_length": 0}, ">= 1"),
        ({"max_tool_name_length": -5}, ">= 1"),
        (
            {
                "max_tool_name_length": 128,
                "max_profile_length": 128,
                "max_event_value_length": 256,
                "max_event_json_bytes": 100,
                "max_total_spool_bytes": 1024,
                "max_retained_event_files": 100,
                "max_distinct_tools": 50,
                "max_distinct_profiles": 50,
                "max_recent_event_ids": 20,
                "max_summary_size_bytes": 64,
            },
            "max_event_json_bytes",
        ),
    ],
    ids=[
        "non_object",
        "boolean",
        "string",
        "float",
        "zero",
        "negative",
        "cross_field_violation",
    ],
)
def test_validate_limits_rejects_malformed_values(limits_data, expected_substring):
    from native_launcher.limits import validate_limits

    schema = json.loads((TESTKIT / "expected" / "limits.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match=expected_substring):
        validate_limits(limits_data, schema)


def test_validate_limits_rejects_unknown_fields():
    from native_launcher.limits import validate_limits

    schema = json.loads((TESTKIT / "expected" / "limits.schema.json").read_text(encoding="utf-8"))
    data = json.loads((TESTKIT / "limits.json").read_text(encoding="utf-8"))
    data["extra_field"] = 1
    with pytest.raises(ValueError, match="additional property"):
        validate_limits(data, schema)


def test_missing_limits_schema_rejected_before_runtime():
    """A contract directory without limits.schema.json must be rejected before any
    project/runtime artifacts are created."""
    bad_contract = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-missing-limits-schema-"))
    (bad_contract / "expected").mkdir(parents=True)
    shutil.copyfile(
        TESTKIT / "expected" / "event.schema.json", bad_contract / "expected" / "event.schema.json"
    )
    shutil.copyfile(
        TESTKIT / "expected" / "summary.schema.json",
        bad_contract / "expected" / "summary.schema.json",
    )
    shutil.copyfile(
        TESTKIT / "expected" / "manifest.schema.json",
        bad_contract / "expected" / "manifest.schema.json",
    )
    shutil.copyfile(TESTKIT / "limits.json", bad_contract / "limits.json")
    try:
        rc, errors, _ = _run_contract(contract_dir=bad_contract)
        assert rc != 0
        assert any("limits.schema" in e.lower() or "limits" in e.lower() for e in errors), errors
    finally:
        shutil.rmtree(bad_contract, ignore_errors=True)


def test_malformed_limits_schema_rejected_before_runtime():
    """A contract directory with an invalid limits.schema.json must be rejected."""
    bad_contract = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-malformed-limits-schema-"))
    (bad_contract / "expected").mkdir(parents=True)
    for name in ("event.schema.json", "summary.schema.json", "manifest.schema.json"):
        shutil.copyfile(TESTKIT / "expected" / name, bad_contract / "expected" / name)
    (bad_contract / "expected" / "limits.schema.json").write_text("not json", encoding="utf-8")
    shutil.copyfile(TESTKIT / "limits.json", bad_contract / "limits.json")
    try:
        rc, errors, _ = _run_contract(contract_dir=bad_contract)
        assert rc != 0
        assert any("limits.schema" in e.lower() or "schema" in e.lower() for e in errors), errors
    finally:
        shutil.rmtree(bad_contract, ignore_errors=True)


def test_stress_mode_enforces_all_bounds():
    """The shared black-box stress run must stay within every configured limit."""
    rc, errors, runtime_root = _run_contract(stress=True, keep=True, timeout=120)
    assert rc == 0, "\n".join(errors)
    try:
        run_dir = _find_run_dir(runtime_root)
        assert run_dir, f"No run directory found in {runtime_root}"
        limits = json.loads((TESTKIT / "limits.json").read_text(encoding="utf-8"))
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        events_dir = run_dir / "events"

        json_files = list(events_dir.glob("*.json"))
        total_size = sum(p.stat().st_size for p in json_files)
        assert len(json_files) <= limits["max_retained_event_files"]
        assert total_size <= limits["max_total_spool_bytes"]
        for p in json_files:
            assert p.stat().st_size <= limits["max_event_json_bytes"]

        assert summary["total_events"] > limits["max_retained_event_files"]
        assert len(summary["tools"]) <= limits["max_distinct_tools"]
        assert len(summary["profiles"]) <= limits["max_distinct_profiles"]
        assert len(summary["consumed_event_ids"]) <= limits["max_recent_event_ids"]
        assert (run_dir / "summary.json").stat().st_size <= limits["max_summary_size_bytes"]
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_summary_size_pressure_trims_bounded_fields():
    """A schema-valid limits file with a small max_summary_size_bytes forces the
    sidecar to trim consumed_event_ids, tools, profiles, and finally last_event
    while keeping the summary within the bound."""
    pressure_contract = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-pressure-limits-"))
    (pressure_contract / "expected").mkdir(parents=True)
    for name in (
        "event.schema.json",
        "summary.schema.json",
        "manifest.schema.json",
        "limits.schema.json",
    ):
        shutil.copyfile(TESTKIT / "expected" / name, pressure_contract / "expected" / name)

    pressure_limits = {
        "max_tool_name_length": 20,
        "max_profile_length": 34,
        "max_event_value_length": 34,
        "max_event_json_bytes": 256,
        "max_total_spool_bytes": 500,
        "max_retained_event_files": 10,
        "max_distinct_tools": 5,
        "max_distinct_profiles": 5,
        "max_recent_event_ids": 5,
        "max_summary_size_bytes": 300,
    }
    (pressure_contract / "limits.json").write_text(json.dumps(pressure_limits), encoding="utf-8")

    try:
        rc, errors, runtime_root = _run_contract(
            contract_dir=pressure_contract, keep=True, timeout=60
        )
        assert rc == 0, "\n".join(errors)
        run_dir = _find_run_dir(runtime_root)
        assert run_dir
        summary_path = run_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary_path.stat().st_size <= pressure_limits["max_summary_size_bytes"]
        # The sidecar had to drop at least the last_event to fit the tiny bound.
        assert summary["last_event"] is None
        # Bounded maps/arrays that can grow without bound should be empty after trimming.
        assert summary["tools"] == {}
        assert summary["profiles"] == {}
        assert summary["consumed_event_ids"] == []
        assert summary["total_events"] >= 1
        schema_path = TESTKIT / "expected" / "summary.schema.json"
        assert not schema_validator.validate_file(summary, schema_path)
    finally:
        shutil.rmtree(pressure_contract, ignore_errors=True)
        if "runtime_root" in locals():
            shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_sidecar_rejects_malformed_spool_files():
    """Malformed event files must not crash the sidecar or be rescanned forever."""
    from native_launcher.sidecar import Sidecar

    runtime_dir = Path(tempfile.mkdtemp(prefix="goal-devin-sidecar-malformed-"))
    events_dir = runtime_dir / "events"
    events_dir.mkdir(parents=True)
    shutil.copyfile(TESTKIT / "expected" / "event.schema.json", runtime_dir / "event.schema.json")
    shutil.copyfile(TESTKIT / "expected" / "limits.schema.json", runtime_dir / "limits.schema.json")
    shutil.copyfile(TESTKIT / "limits.json", runtime_dir / "limits.json")

    try:
        limits = json.loads((TESTKIT / "limits.json").read_text(encoding="utf-8"))
        valid_event = {
            "schema_version": 1,
            "event": "PostToolUse",
            "tool_name": "run_subagent",
            "profile": "goal-devin-worker-abc",
            "is_background": False,
            "success": True,
            "observed_at": "2024-01-01T00:00:00+00:00",
        }
        (events_dir / "valid.json").write_text(json.dumps(valid_event), encoding="utf-8")

        (events_dir / "bad-utf8.json").write_bytes(b"\xff\xfe\xff\xfe")
        (events_dir / "not-object.json").write_text(json.dumps([]), encoding="utf-8")
        (events_dir / "truncated.json").write_text('{"schema_version": 1', encoding="utf-8")
        oversized = events_dir / "oversized.json"
        oversized.write_bytes(b"x" * (limits["max_event_json_bytes"] + 1))
        unreadable = events_dir / "unreadable.json"
        unreadable.write_text(json.dumps(valid_event), encoding="utf-8")
        os.chmod(unreadable, 0o000)

        sidecar = Sidecar(runtime_dir)
        sidecar.events_dir = events_dir
        before_total = sidecar.total_events
        sidecar._drain()
        assert sidecar.total_events == before_total + 1
        assert (events_dir / "valid.json").exists()
        assert not (events_dir / "bad-utf8.json").exists()
        assert not (events_dir / "not-object.json").exists()
        assert not (events_dir / "truncated.json").exists()
        assert not oversized.exists()
        assert not unreadable.exists()

        # A second drain must be a no-op; the malformed files are not rescanned.
        second_total = sidecar.total_events
        sidecar._drain()
        assert sidecar.total_events == second_total
    finally:
        shutil.rmtree(runtime_dir, ignore_errors=True)


def test_tty_timeout_reaps_descendants():
    """A TTY candidate that hangs must be killed and the sidecar/child reaped."""
    start = time.monotonic()
    rc, errors, runtime_root = _run_contract(
        tty=True,
        timeout=2,
        keep=True,
        extra_env={"GOAL_DEVIN_FAKE_HANG": "1"},
    )
    elapsed = time.monotonic() - start
    try:
        assert rc != 0
        assert elapsed < 8, f"runner did not enforce timeout ({elapsed:.1f}s)"
        run_dir = _find_run_dir(runtime_root)
        assert run_dir, f"No run directory found in {runtime_root}"
        for name in ("supervisor.pid", "sidecar.pid", "child.pid"):
            pid_path = run_dir / name
            assert pid_path.exists(), f"{name} missing"
            pid = int(pid_path.read_text(encoding="utf-8").strip().split()[0])
            assert not _is_alive(pid), f"{name} {pid} is still alive after timeout"
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _no_process_with(name: str) -> bool:
    result = subprocess.run(
        ["pgrep", "-f", name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode != 0


def test_hang_no_rundir_reaps_process():
    """A candidate that hangs without creating a run directory must be killed
    within the timeout and no candidate process may survive."""
    start = time.monotonic()
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "hang-no-rundir-candidate.py",
        timeout=2,
    )
    elapsed = time.monotonic() - start
    assert rc != 0
    assert elapsed < 8, f"runner did not fail within the timeout bound ({elapsed:.1f}s)"
    # Give the runner a moment to finish reaping after the timeout return.
    time.sleep(0.5)
    assert _no_process_with("hang-no-rundir-candidate.py")


def test_overlap_missing_pid_rejected():
    """A candidate that creates a run directory but never writes PID files must
    be killed and rejected."""
    start = time.monotonic()
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "overlap-missing-pid-candidate.py",
        process_overlap=True,
        timeout=2,
    )
    elapsed = time.monotonic() - start
    assert rc != 0
    assert any("pid" in e.lower() for e in errors), errors
    assert elapsed < 8, f"runner did not fail within the timeout bound ({elapsed:.1f}s)"
    time.sleep(0.5)
    assert _no_process_with("overlap-missing-pid-candidate.py")


def test_modify_sentinel_rejected():
    rc, errors, runtime_root = _run_contract(
        candidate=TESTKIT / "fixtures" / "modify-sentinel-candidate.py",
        sentinel=True,
        keep=True,
    )
    try:
        assert rc != 0
        assert any("digest changed" in e.lower() or "changed" in e.lower() for e in errors), errors
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_delete_sentinel_rejected():
    rc, errors, runtime_root = _run_contract(
        candidate=TESTKIT / "fixtures" / "delete-sentinel-candidate.py",
        sentinel=True,
        keep=True,
    )
    try:
        assert rc != 0
        assert any("deleted" in e.lower() for e in errors), errors
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_leave_profile_rejected():
    rc, errors, runtime_root = _run_contract(
        candidate=TESTKIT / "fixtures" / "leave-profile-candidate.py",
        keep=True,
    )
    try:
        assert rc != 0
        assert any("profile directory was not removed" in e.lower() for e in errors), errors
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_leave_new_hook_rejected():
    rc, errors, runtime_root = _run_contract(
        candidate=TESTKIT / "fixtures" / "leave-new-hook-candidate.py",
        keep=True,
    )
    try:
        assert rc != 0
        assert any("run-created .devin/hooks.v1.json" in e.lower() for e in errors), errors
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_modify_existing_hook_rejected():
    original = EXISTING_HOOKS.read_bytes()
    rc, errors, runtime_root = _run_contract(
        candidate=TESTKIT / "fixtures" / "modify-existing-hook-candidate.py",
        existing_hooks=True,
        keep=True,
    )
    try:
        assert rc != 0
        assert any(
            "not restored byte-for-byte" in e.lower() or "changed" in e.lower() for e in errors
        ), errors
        canary = runtime_root / "canary"
        hooks_file = canary / ".devin" / "hooks.v1.json"
        assert hooks_file.read_bytes() != original
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_empty_generated_ancestors_removed():
    """Run-created .devin and .devin/agents directories must be removed if empty."""
    rc, errors, runtime_root = _run_contract(keep=True)
    assert rc == 0, "\n".join(errors)
    try:
        run_dir = _find_run_dir(runtime_root)
        assert run_dir
        manifest = json.loads((run_dir / "manifest.json").read_text())
        canary = Path(manifest["canary"])
        assert canary.exists()
        # The fixture canary has no .devin directory; the candidate must not leave one.
        assert not (canary / ".devin").exists(), "run-created .devin directory was not removed"
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_profile_directory_collision_avoids_overwrite(monkeypatch):
    """A pre-existing goal-devin-worker-* directory must not be overwritten; the
    supervisor must retry with a new profile_id."""
    from native_launcher import supervisor as supervisor_module

    runtime_root = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-collision-runtime-"))
    canary = runtime_root / "canary"
    canary.mkdir(parents=True)
    (canary / "fib.py").write_text("# fixture\n", encoding="utf-8")
    agents = canary / ".devin" / "agents"
    agents.mkdir(parents=True)
    existing_profile = agents / "goal-devin-worker-deadbeef"
    existing_profile.mkdir()
    sentinel = existing_profile / "AGENT.md"
    sentinel.write_text("---\nname: existing\n---\n", encoding="utf-8")

    existing_id = existing_profile.name
    new_id = "goal-devin-worker-newface00"
    profile_ids = iter([existing_id, new_id])

    args = types.SimpleNamespace(
        model="swe-1-7",
        permission_mode="accept-edits",
        devin_bin=str(FAKE_DEVIN),
        contract_dir=str(TESTKIT),
        runtime_root=str(runtime_root),
        canary=str(canary),
        existing_hooks=None,
        keep_canary=False,
    )

    monkeypatch.setattr(supervisor_module, "make_profile_id", lambda: next(profile_ids))
    monkeypatch.setattr(supervisor_module.Supervisor, "_start_sidecar", lambda self: None)
    monkeypatch.setattr(
        supervisor_module.Supervisor,
        "_run_devin",
        lambda self: setattr(self, "devin_returncode", 0),
    )

    try:
        supervisor = supervisor_module.Supervisor(args)
        rc = supervisor.run()
        assert rc == 0
        manifest = json.loads(supervisor.manifest_path.read_text())
        assert manifest["profile_id"] == new_id
        assert manifest["profile_id"] != existing_id
        assert sentinel.read_text(encoding="utf-8") == "---\nname: existing\n---\n"
        # The pre-existing directory is not claimed as owned.
        owned_dirs = {Path(p).resolve() for p in manifest["owned_dirs"]}
        assert existing_profile.resolve() not in owned_dirs
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_manifest_records_owned_dirs():
    """The manifest must record exact directories created by this run."""
    rc, errors, runtime_root = _run_contract(keep=True)
    assert rc == 0, "\n".join(errors)
    try:
        run_dir = _find_run_dir(runtime_root)
        assert run_dir
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert "owned_dirs" in manifest
        owned_dirs = {Path(p).resolve() for p in manifest["owned_dirs"]}
        profile_path = Path(manifest["profile_path"]).resolve()
        assert profile_path.parent in owned_dirs
        # The .devin directory created by hook installation is owned by this run.
        canary = Path(manifest["canary"]).resolve()
        assert (canary / ".devin").resolve() in owned_dirs
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_supplied_canary_created_and_removed():
    """A supplied --canary path that does not pre-exist is treated as run-owned
    and removed after the run."""
    from native_launcher import supervisor as supervisor_module

    runtime_root = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-supplied-canary-"))
    supplied_canary = runtime_root / "my-canary"
    assert not supplied_canary.exists()

    args = types.SimpleNamespace(
        model="swe-1-7",
        permission_mode="accept-edits",
        devin_bin=str(FAKE_DEVIN),
        contract_dir=str(TESTKIT),
        runtime_root=str(runtime_root),
        canary=str(supplied_canary),
        existing_hooks=None,
        keep_canary=False,
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(supervisor_module.Supervisor, "_start_sidecar", lambda self: None)
    monkeypatch.setattr(
        supervisor_module.Supervisor,
        "_run_devin",
        lambda self: setattr(self, "devin_returncode", 0),
    )
    try:
        supervisor = supervisor_module.Supervisor(args)
        rc = supervisor.run()
        assert rc == 0
        # The supplied canary must be treated as run-created and removed.
        assert supervisor.canary_created is True
        owned_dirs = {Path(p).resolve() for p in supervisor.owned_dirs}
        assert supplied_canary.resolve() in owned_dirs
        assert not supplied_canary.exists()
    finally:
        monkeypatch.undo()
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_vacuous_limits_schema_rejected_before_runtime():
    """A limits.schema.json of {} must be rejected as an invalid closed schema."""
    bad_contract = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-vacuous-limits-schema-"))
    (bad_contract / "expected").mkdir(parents=True)
    for name in ("event.schema.json", "summary.schema.json", "manifest.schema.json"):
        shutil.copyfile(TESTKIT / "expected" / name, bad_contract / "expected" / name)
    (bad_contract / "expected" / "limits.schema.json").write_text("{}", encoding="utf-8")
    shutil.copyfile(TESTKIT / "limits.json", bad_contract / "limits.json")
    try:
        rc, errors, _ = _run_contract(contract_dir=bad_contract)
        assert rc != 0
        assert any("limits schema" in e.lower() or "schema" in e.lower() for e in errors), errors
    finally:
        shutil.rmtree(bad_contract, ignore_errors=True)


def test_minimal_impossible_limits_rejected_before_runtime():
    """Limits that are schema-valid but cannot physically fit a valid event/summary
    must be rejected before the candidate runs."""
    bad_contract = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-impossible-limits-"))
    (bad_contract / "expected").mkdir(parents=True)
    for name in (
        "event.schema.json",
        "summary.schema.json",
        "manifest.schema.json",
        "limits.schema.json",
    ):
        shutil.copyfile(TESTKIT / "expected" / name, bad_contract / "expected" / name)
    impossible = {
        key: 1 for key in json.loads((TESTKIT / "limits.json").read_text(encoding="utf-8"))
    }
    (bad_contract / "limits.json").write_text(json.dumps(impossible), encoding="utf-8")
    try:
        rc, errors, _ = _run_contract(contract_dir=bad_contract)
        assert rc != 0
        assert any(
            "max_event_json_bytes" in e.lower() or "max_summary_size_bytes" in e.lower()
            for e in errors
        ), errors
    finally:
        shutil.rmtree(bad_contract, ignore_errors=True)


def test_no_event_candidate_rejected():
    """A candidate that forges a valid-looking summary with total_events:1 but never
    publishes an event must be rejected.
    """
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "no-event-candidate.py",
    )
    assert rc != 0
    assert any("event" in e.lower() for e in errors), errors


def test_canary_root_unowned_file_rejected():
    """A candidate that leaves a new unowned file at the canary root must be rejected."""
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "canary-root-unowned-file-candidate.py",
    )
    assert rc != 0
    assert any("unowned" in e.lower() or "canary" in e.lower() for e in errors), errors


def test_canary_corrupt_then_exit_rejected():
    """A candidate that mutates the canary and exits nonzero before producing a manifest
    must still have its canary integrity violation caught.
    """
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "canary-corrupt-then-exit-candidate.py",
    )
    assert rc != 0
    assert any(
        "unowned" in e.lower() or "canary" in e.lower() or "exited" in e.lower() for e in errors
    ), errors


def test_sentinel_pid_rejected_without_killing_sentinel():
    """A bogus child PID pointing at an unrelated process must be rejected and the
    runner must not signal that process.
    """
    sentinel = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        rc, errors, _ = _run_contract(
            candidate=TESTKIT / "fixtures" / "sentinel-pid-candidate.py",
            process_overlap=True,
            extra_env={"GOAL_DEVIN_SENTINEL_PID": str(sentinel.pid)},
        )
        assert rc != 0
        assert any(
            "process tree" in e.lower() or "not in candidate" in e.lower() for e in errors
        ), errors
        assert sentinel.poll() is None, "sentinel was killed"
    finally:
        sentinel.terminate()
        try:
            sentinel.wait(timeout=2)
        except subprocess.TimeoutExpired:
            sentinel.kill()
            sentinel.wait()


def test_delete_preexisting_success_candidate_rejected():
    """A candidate that deletes a pre-existing canary file during a successful run
    must be rejected for canary integrity.
    """
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "delete-preexisting-success-candidate.py",
    )
    assert rc != 0
    assert any("deleted" in e.lower() for e in errors), errors


def test_delete_preexisting_error_candidate_rejected():
    """A candidate that deletes a pre-existing canary file and exits nonzero must still
    have the deletion detected.
    """
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "delete-preexisting-error-candidate.py",
    )
    assert rc != 0
    assert any("deleted" in e.lower() for e in errors), errors


def test_normal_timeout_reaps_sidecar():
    """A normal-mode candidate whose fake-devin hangs must be killed and the detached
    sidecar reaped.
    """
    start = time.monotonic()
    rc, errors, runtime_root = _run_contract(
        timeout=2,
        keep=True,
        extra_env={"GOAL_DEVIN_FAKE_HANG": "1"},
    )
    elapsed = time.monotonic() - start
    try:
        assert rc != 0
        assert elapsed < 8, f"runner did not enforce timeout ({elapsed:.1f}s)"
        run_dir = _find_run_dir(runtime_root)
        assert run_dir, f"No run directory found in {runtime_root}"
        sidecar_pid_path = run_dir / "sidecar.pid"
        assert sidecar_pid_path.exists(), "sidecar.pid missing"
        sidecar_pid = int(sidecar_pid_path.read_text(encoding="utf-8").strip().split()[0])
        assert not _is_alive(sidecar_pid), f"sidecar {sidecar_pid} is still alive after timeout"
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_partial_pid_rejected_and_sidecar_killed():
    """A candidate that writes a valid sidecar.pid but no child.pid must be rejected,
    and the valid sidecar must still be reaped.
    """
    start = time.monotonic()
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "partial-pid-candidate.py",
        process_overlap=True,
        timeout=2,
    )
    elapsed = time.monotonic() - start
    assert rc != 0
    assert any("pid" in e.lower() for e in errors), errors
    assert elapsed < 8, f"runner did not fail within the timeout bound ({elapsed:.1f}s)"
    time.sleep(0.5)
    assert _no_process_with("partial-pid-candidate.py")


def test_adversarial_limits_tiny_field_caps_rejected():
    """A schema-valid limits file with large byte caps but tiny field caps must be
    rejected before the candidate runs because the canonical event cannot be represented.
    """
    bad_contract = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-adversarial-limits-"))
    (bad_contract / "expected").mkdir(parents=True)
    for name in (
        "event.schema.json",
        "summary.schema.json",
        "manifest.schema.json",
        "limits.schema.json",
    ):
        shutil.copyfile(TESTKIT / "expected" / name, bad_contract / "expected" / name)
    adversarial = {
        "max_tool_name_length": 5,
        "max_profile_length": 5,
        "max_event_value_length": 5,
        "max_event_json_bytes": 65536,
        "max_total_spool_bytes": 65536,
        "max_retained_event_files": 100,
        "max_distinct_tools": 5,
        "max_distinct_profiles": 5,
        "max_recent_event_ids": 5,
        "max_summary_size_bytes": 65536,
    }
    (bad_contract / "limits.json").write_text(json.dumps(adversarial), encoding="utf-8")
    try:
        rc, errors, _ = _run_contract(contract_dir=bad_contract)
        assert rc != 0
        assert any(
            "max_tool_name_length" in e.lower()
            or "max_profile_length" in e.lower()
            or "max_event_value_length" in e.lower()
            for e in errors
        ), errors
    finally:
        shutil.rmtree(bad_contract, ignore_errors=True)


def test_canonical_flood_respects_spool_bounds():
    """Emit more canonical events than the retained-file limit and assert that
    the sidecar keeps exactly the bounded number of files, the total spool size
    stays within limits, and provenance (a PostToolUse/run_subagent event) is still
    retained.
    """
    custom_contract = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-canonical-flood-"))
    (custom_contract / "expected").mkdir(parents=True)
    for name in (
        "event.schema.json",
        "summary.schema.json",
        "manifest.schema.json",
        "limits.schema.json",
    ):
        shutil.copyfile(TESTKIT / "expected" / name, custom_contract / "expected" / name)
    flood_limits = {
        "max_tool_name_length": 12,
        "max_profile_length": 34,
        "max_event_value_length": 34,
        "max_event_json_bytes": 256,
        "max_total_spool_bytes": 5000,
        "max_retained_event_files": 5,
        "max_distinct_tools": 5,
        "max_distinct_profiles": 5,
        "max_recent_event_ids": 5,
        "max_summary_size_bytes": 300,
    }
    (custom_contract / "limits.json").write_text(json.dumps(flood_limits), encoding="utf-8")

    try:
        rc, errors, runtime_root = _run_contract(
            contract_dir=custom_contract,
            stress=True,
            keep=True,
            extra_env={"GOAL_DEVIN_FAKE_CANONICAL_FLOOD": "20"},
        )
        assert rc == 0, "\n".join(errors)
        run_dir = _find_run_dir(runtime_root)
        assert run_dir, f"No run directory found in {runtime_root}"
        events_dir = run_dir / "events"
        json_files = list(events_dir.glob("*.json"))
        assert len(json_files) <= flood_limits["max_retained_event_files"]
        total_size = sum(p.stat().st_size for p in json_files)
        assert total_size <= flood_limits["max_total_spool_bytes"]

        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        profile_id = manifest["profile_id"]
        provenance_seen = False
        for p in json_files:
            event = json.loads(p.read_text(encoding="utf-8"))
            if (
                event.get("event") == "PostToolUse"
                and event.get("tool_name") == "run_subagent"
                and event.get("profile") == profile_id
            ):
                provenance_seen = True
                break
        assert provenance_seen, "No canonical PostToolUse/run_subagent event retained"

        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["total_events"] > flood_limits["max_retained_event_files"]
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_sessionstart_forged_fields_rejected():
    """A SessionStart event with forged tool_name/profile must not satisfy canonical
    event provenance.
    """
    rc, errors, _ = _run_contract(
        extra_env={"GOAL_DEVIN_FAKE_SESSIONSTART_FORGED": "1"},
    )
    assert rc != 0
    assert any(
        "provenance" in e.lower()
        or "posttooluse" in e.lower()
        or ("run_subagent" in e.lower() and "success" in e.lower())
        for e in errors
    ), errors


def test_malformed_manifest_rejected_and_cleanup_runs():
    """A candidate that writes malformed manifest.json must be rejected without
    crashing the runner, and cleanup/integrity checks must still run.
    """
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "malformed-manifest-candidate.py",
    )
    assert rc != 0
    assert any("manifest.json" in e.lower() and "json" in e.lower() for e in errors), errors


def test_malformed_summary_rejected_and_cleanup_runs():
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "malformed-summary-candidate.py",
    )
    assert rc != 0
    assert any("summary.json" in e.lower() and "json" in e.lower() for e in errors), errors


def test_malformed_record_rejected_and_cleanup_runs():
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "malformed-record-candidate.py",
    )
    assert rc != 0
    assert any("fake-devin.record.json" in e.lower() and "json" in e.lower() for e in errors), (
        errors
    )


def test_missing_schema_rejected_before_runtime():
    """A contract directory missing an authoritative schema must be rejected before
    the candidate is launched.
    """
    bad_contract = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-missing-schema-"))
    (bad_contract / "expected").mkdir(parents=True)
    for name in ("event.schema.json", "manifest.schema.json", "limits.schema.json"):
        shutil.copyfile(TESTKIT / "expected" / name, bad_contract / "expected" / name)
    shutil.copyfile(TESTKIT / "limits.json", bad_contract / "limits.json")
    try:
        rc, errors, _ = _run_contract(contract_dir=bad_contract)
        assert rc != 0
        assert any("summary.schema.json" in e.lower() or "missing" in e.lower() for e in errors), (
            errors
        )
    finally:
        shutil.rmtree(bad_contract, ignore_errors=True)


def test_delayed_sidecar_pid_reaped_on_timeout():
    """A candidate that writes sidecar.pid after the first discovery window must still
    have the sidecar discovered and killed on timeout.
    """
    start = time.monotonic()
    rc, errors, runtime_root = _run_contract(
        candidate=TESTKIT / "fixtures" / "delayed-sidecar-pid-candidate.py",
        timeout=5,
        keep=True,
    )
    elapsed = time.monotonic() - start
    try:
        assert rc != 0
        assert elapsed < 12, f"runner did not enforce timeout ({elapsed:.1f}s)"
        run_dir = _find_run_dir(runtime_root)
        assert run_dir, f"No run directory found in {runtime_root}"
        sidecar_pid_path = run_dir / "sidecar.pid"
        assert sidecar_pid_path.exists(), "sidecar.pid missing"
        sidecar_pid = int(sidecar_pid_path.read_text(encoding="utf-8").strip().split()[0])
        assert not _is_alive(sidecar_pid), f"sidecar {sidecar_pid} is still alive after timeout"
    finally:
        shutil.rmtree(runtime_root.parent, ignore_errors=True)


def test_canary_preexisting_symlink_preserved():
    """A harmless pre-existing symlink in the canary fixture must remain unchanged
    and not be flagged as an unowned new path.
    """
    rc, errors, _ = _run_contract()
    assert rc == 0, "\n".join(errors)


def test_canary_new_symlink_to_owned_runtime_rejected():
    """A candidate that creates a canary symlink pointing to an owned runtime file
    must be rejected because the symlink entry itself is not declared.
    """
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "canary-symlink-to-owned-candidate.py",
    )
    assert rc != 0
    assert any(
        "symlink" in e.lower()
        and ("not owned" in e.lower() or "boundary" in e.lower() or "escapes" in e.lower())
        for e in errors
    ), errors


def test_runtime_broken_symlink_rejected():
    """A candidate that creates a broken symlink in the runtime directory must be
    rejected as an unowned entry or as escaping the permitted boundary.
    """
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "runtime-broken-symlink-candidate.py",
    )
    assert rc != 0
    assert any(
        "symlink" in e.lower()
        and ("not owned" in e.lower() or "boundary" in e.lower() or "escapes" in e.lower())
        for e in errors
    ), errors


def test_canary_intermediate_symlink_escape_rejected():
    """A canary symlink whose effective target escapes through a pre-existing
    intermediate symlink must be rejected.
    """
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "canary-intermediate-symlink-escape-candidate.py",
    )
    assert rc != 0
    assert any(
        "symlink" in e.lower() and ("boundary" in e.lower() or "escapes" in e.lower())
        for e in errors
    ), errors


def test_runtime_intermediate_symlink_escape_rejected():
    """A runtime symlink whose lexical target is inside runtime/ but whose effective
    target escapes through an intermediate symlink must be rejected.
    """
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "runtime-intermediate-symlink-escape-candidate.py",
    )
    assert rc != 0
    assert any(
        "symlink" in e.lower() and ("boundary" in e.lower() or "escapes" in e.lower())
        for e in errors
    ), errors


def test_sentinel_pid_not_killed_on_timeout():
    """A candidate that writes a non-descendant sentinel PID into child.pid must be
    rejected, and the sentinel process must survive timeout cleanup.
    """
    sentinel = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        rc, errors, _ = _run_contract(
            candidate=TESTKIT / "fixtures" / "sentinel-pid-timeout-candidate.py",
            timeout=3,
            extra_env={"GOAL_DEVIN_SENTINEL_PID": str(sentinel.pid)},
        )
        assert rc != 0
        assert sentinel.poll() is None, "sentinel was killed during timeout cleanup"
    finally:
        sentinel.terminate()
        try:
            sentinel.wait(timeout=2)
        except subprocess.TimeoutExpired:
            sentinel.kill()
            sentinel.wait()


def test_fork_bomb_reaped_on_timeout():
    """A candidate that forks a small tree of child processes must have every
    descendant reaped by the timeout cleanup.
    """
    rc, errors, _ = _run_contract(
        candidate=TESTKIT / "fixtures" / "fork-bomb-candidate.py",
        timeout=3,
    )
    assert rc != 0
    time.sleep(0.5)
    assert _no_process_with("fork-bomb-candidate.py")
