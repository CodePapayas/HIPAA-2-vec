from __future__ import annotations

from datetime import date

import click

from hipaa_mcp.config import get_settings


@click.group()
def main() -> None:
    pass


@main.command()
def serve() -> None:
    """Run the MCP server over stdio."""
    from hipaa_mcp.server import mcp

    mcp.run()


@main.command()
@click.option("--date", "as_of", default=None, help="YYYY-MM-DD date for eCFR snapshot")
def reindex(as_of: str | None) -> None:
    """Download eCFR XML and rebuild indices."""
    from hipaa_mcp.ingest import reindex as _reindex

    parsed_date: date | None = None
    if as_of:
        try:
            parsed_date = date.fromisoformat(as_of)
        except ValueError:
            raise click.BadParameter(f"Expected YYYY-MM-DD, got {as_of!r}", param_hint="--date")

    _reindex(parsed_date)


@main.group()
def glossary() -> None:
    """Manage the active glossary."""
    pass


@glossary.command("list")
def glossary_list() -> None:
    """Print all glossary entries."""
    from hipaa_mcp.glossary import load_glossary

    g = load_glossary()
    if not g.entries:
        click.echo("(no entries)")
        return
    for entry in g.entries:
        line = f"{entry.term!r} -> {entry.maps_to!r} [{entry.relationship.value}]"
        if entry.notes:
            line += f"  # {entry.notes}"
        click.echo(line)


@glossary.command("path")
def glossary_path() -> None:
    """Print the path to the active glossary file."""
    click.echo(get_settings().glossary_path)
