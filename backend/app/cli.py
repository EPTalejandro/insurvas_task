import typer

from app.db import SessionLocal, init_db, reset_db
from app.discovery.keywords import seed_keywords

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


if __name__ == "__main__":
    cli()
