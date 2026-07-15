"""Generate and clean up a temporary Goal Devin worker profile."""

from __future__ import annotations

from pathlib import Path

from native_launcher_python.config import AGENTS_DIR


def _render_frontmatter(
    profile_id: str,
    model: str,
    allowed_tools: list[str],
    denied_permissions: list[str],
) -> str:
    lines = [
        "---",
        f"name: {profile_id}",
        "description: Goal Devin read-only worker for the native integration trial",
        f"model: {model}",
        "allowed-tools:",
    ]
    for tool in allowed_tools:
        lines.append(f"  - {tool}")
    lines.append("permissions:")
    lines.append("  deny:")
    for perm in denied_permissions:
        lines.append(f"    - {perm}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def install_profile(
    workdir: Path,
    profile_id: str,
    model: str,
    allowed_tools: tuple[str, ...] = ("read", "grep", "glob"),
    denied_permissions: tuple[str, ...] = ("write", "edit"),
) -> Path:
    """Create a temporary custom subagent profile under .devin/agents/."""
    agents_dir = workdir / AGENTS_DIR
    agents_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = agents_dir / profile_id
    if profile_dir.exists():
        raise FileExistsError(f"Profile already exists: {profile_dir}")
    profile_dir.mkdir(mode=0o700, exist_ok=False)
    agent_md = profile_dir / "AGENT.md"
    frontmatter = _render_frontmatter(
        profile_id, model, list(allowed_tools), list(denied_permissions)
    )
    body = (
        f"\n<!-- goal-devin-generated: true; profile-id: {profile_id} -->\n\n"
        "You are a Goal Devin trial worker. Use the selected model and follow "
        "project instructions. Do not perform destructive operations outside the current task.\n"
    )
    agent_md.write_text(frontmatter + body, encoding="utf-8")
    agent_md.chmod(0o600)
    return agent_md


def remove_profile(workdir: Path, profile_id: str) -> None:
    """Remove the generated profile directory."""
    import shutil

    profile_dir = workdir / AGENTS_DIR / profile_id
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
