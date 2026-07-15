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
    keep: bool = False,
    extra_env: dict | None = None,
    contract_dir: Path | None = None,
) -> tuple[int, list[str], Path]:
    """Run the shared contract and return (rc, error_lines, runtime_root)."""
    base_dir = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-test-"))
    runtime_root = base_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    chosen_candidate = candidate or CANDIDATE
    chosen_canary = canary_fixture or CANARY_FIXTURE
    chosen_contract_dir = contract_dir or TESTKIT
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
        str(FAKE_DEVIN),
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
    return result.returncode, errors, runtime_root


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
    """Run the shared schema conformance corpus through both validators."""
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
            assert shared == runtime, (
                f"{case['name']} valid mismatch for {value!r}: {shared} vs {runtime}"
            )
        for value in case["invalid"]:
            shared = schema_validator.validate(value, schema)
            runtime = runtime_validate(value, schema)
            assert shared == runtime, (
                f"{case['name']} invalid mismatch for {value!r}: {shared} vs {runtime}"
            )
            assert shared, f"{case['name']} should reject {value!r}"


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


def _make_canary_fixture_with_symlink(link_name: str, target: Path) -> Path:
    """Return a temporary canary fixture where *link_name* is a symlink to *target*."""
    fixture = Path(tempfile.mkdtemp(prefix="goal-devin-r1a1-symlink-fixture-"))
    canary = fixture / "canary"
    canary.mkdir(parents=True)
    for item in CANARY_FIXTURE.iterdir():
        if item.is_dir():
            shutil.copytree(item, canary / item.name)
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
    shutil.copytree(CANARY_FIXTURE, canary_fixture)
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
    assert any("distinct" in e.lower() or "supervisor.pid" in e.lower() for e in errors)


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
    shutil.copytree(CANARY_FIXTURE, fixture, dirs_exist_ok=True)
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
