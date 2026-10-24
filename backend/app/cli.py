import typer

from app.collectors.youtube import collect_youtube
from app.config import get_settings
from app.db import SessionLocal, init_db, reset_db
from app.discovery.discover import discover_youtube
from app.discovery.keywords import seed_keywords
from app.discovery.location import update_locations
from app.httpclient import make_client

cli = typer.Typer(help="Competitor Content Intelligence commands.", no_args_is_help=True)


@cli.command("init-db")
def init_db_command() -> None:
    """Create the database tables if they do not exist."""
    init_db()
    typer.echo("Database ready.")


@cli.command("reset-db")
def reset_db_command(
    yes: bool = typer.Option(False, "--yes", help="Required: confirms deleting all data."),
) -> None:
    """Delete all data and recreate empty tables."""
    if not yes:
        typer.echo("This deletes all data. Run again with --yes to confirm.")
        raise typer.Exit(code=1)
    reset_db()
    typer.echo("Database reset.")


@cli.command("seed")
def seed_command() -> None:
    """Add the default discovery keywords (safe to run more than once)."""
    with SessionLocal() as session:
        added = seed_keywords(session)
    typer.echo(f"Added {added} keywords.")


def _youtube_ready(platform: str | None) -> bool:
    """True when this command should run YouTube. Explains why when it should not."""
    if platform not in (None, "youtube"):
        typer.echo(f"Platform '{platform}' is not available yet.")
        return False
    if not get_settings().youtube_api_key:
        typer.echo("YOUTUBE_API_KEY is empty, so YouTube is skipped.")
        return False
    return True


def _report(run) -> None:
    typer.echo(
        f"{run.kind} {run.platform}: {run.status} "
        f"({run.items_ok} ok, {run.items_failed} failed, {run.quota_used} quota units). "
        f"{run.message}"
    )


@cli.command("discover")
def discover_command(platform: str | None = typer.Option(None, help="youtube")) -> None:
    """Find agent and agency accounts and pick the active competitors."""
    if not _youtube_ready(platform):
        raise typer.Exit(code=1 if platform not in (None, "youtube") else 0)
    with SessionLocal() as session, make_client() as client:
        _report(discover_youtube(session, client, get_settings()))


@cli.command("collect")
def collect_command(platform: str | None = typer.Option(None, help="youtube")) -> None:
    """Collect recent posts of the active competitors."""
    if not _youtube_ready(platform):
        raise typer.Exit(code=1 if platform not in (None, "youtube") else 0)
    with SessionLocal() as session, make_client() as client:
        _report(collect_youtube(session, client, get_settings()))
        # Posts are now in the database, so accounts without a country can be checked.
        counts = update_locations(session)
    typer.echo("locations: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    cli()
