"""List skills installed on this machine."""

from typing import TypedDict

from rich.console import Console
from rich.table import Table

from dhub.cli.output import is_json, print_json
from dhub.core import install


class _InstalledSkill(TypedDict):
    ref: str
    version: str | None
    agents: list[str]


def installed_command() -> None:
    """List locally installed skills, recorded versions, and linked agents."""
    skills: list[_InstalledSkill] = []
    for org, name in install.list_installed_skills():
        recorded = install.get_installed_version(org, name)
        skills.append(
            {
                "ref": f"{org}/{name}",
                "version": recorded.version if recorded else None,
                "agents": install.list_linked_agents(org, name),
            }
        )

    if is_json():
        print_json(skills)
        return

    console = Console(markup=False)
    if not skills:
        console.print("No skills installed.")
        return

    table = Table(title="Installed skills")
    table.add_column("Skill", style="cyan")
    table.add_column("Version")
    table.add_column("Linked agents")
    for skill in skills:
        table.add_row(skill["ref"], skill["version"] or "unknown", ", ".join(skill["agents"]) or "none")
    console.print(table)
