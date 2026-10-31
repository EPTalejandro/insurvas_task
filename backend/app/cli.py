import typer

from app.config import get_settings
from app.db import SessionLocal, init_db, reset_db
from app.discovery.discover import discover_youtube
from app.httpclient import make_client
from app.labeling.service import label_posts
from app.pipeline import (
    collect_step,
    enabled_platforms,
    pick_labeler,
    pick_reviewer,
    refresh,
)
from app.ranking.service import rank_all

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
    quota = f", {run.quota_used} quota units" if run.quota_used else ""
    typer.echo(
        f"{run.kind} {run.platform or 'all'}: {run.status} "
        f"({run.items_ok} ok, {run.items_failed} failed{quota}). {run.message}"
    )


@cli.command("discover")
def discover_command(platform: str | None = typer.Option(None, help="youtube")) -> None:
    """Find agent and agency accounts and pick the active competitors."""
    if not _youtube_ready(platform):
        raise typer.Exit(code=1 if platform not in (None, "youtube") else 0)
    with SessionLocal() as session, make_client() as client:
        settings = get_settings()
        run = discover_youtube(session, client, settings, reviewer=pick_reviewer(settings))
        _report(run)


@cli.command("collect")
def collect_command(
    platform: str | None = typer.Option(None, help="youtube or instagram (default: all enabled)"),
) -> None:
    """Collect recent posts: competitors' videos and Instagram hashtag top posts."""
    if platform not in (None, "youtube", "instagram"):
        typer.echo(f"Platform '{platform}' is not available.")
        raise typer.Exit(code=1)
    settings = get_settings()
    enabled = enabled_platforms(settings)
    wanted = [platform] if platform else enabled
    for name in wanted:
        if name not in enabled:
            typer.echo(f"{name} has no keys in .env, so it is skipped.")
    wanted = [name for name in wanted if name in enabled]
    if not wanted:
        if platform is None:
            typer.echo("No platform has keys in .env, so nothing was collected.")
        raise typer.Exit(code=0 if platform is None else 1)
    with SessionLocal() as session, make_client() as client:
        result = collect_step(
            session, client, settings, platforms=wanted, reviewer=pick_reviewer(settings)
        )
    for run in result.runs:
        _report(run)
    if result.creator_locations:
        counts = ", ".join(f"{k}={v}" for k, v in sorted(result.creator_locations.items()))
        typer.echo(f"account locations: {counts}")
    if result.post_locations:
        counts = ", ".join(f"{k}={v}" for k, v in sorted(result.post_locations.items()))
        typer.echo(f"hashtag post locations: {counts}")


def _labeler_note() -> None:
    settings = get_settings()
    if settings.labeler == "gemini" and not settings.gemini_api_key:
        typer.echo("LABELER=gemini but GEMINI_API_KEY is empty, so the rules labeler is used.")


@cli.command("label")
def label_command(
    force: bool = typer.Option(False, "--force", help="Relabel every post, even unchanged ones."),
    limit: int | None = typer.Option(None, help="Label at most this many posts (best first)."),
) -> None:
    """Label new or changed posts (with Gemini when a key is set, otherwise with the rules)."""
    _labeler_note()
    settings = get_settings()
    labeler = pick_labeler(settings)
    if labeler.name == "gemini":
        typer.echo(
            f"Labeling with Gemini ({settings.gemini_model}): 10 posts per request, "
            f"at most {settings.gemini_rpm} requests a minute. Posts that fail use the rules."
        )

    def show_progress(done: int, total: int) -> None:
        typer.echo(f"  {done}/{total} posts labeled")

    with SessionLocal() as session:
        _report(label_posts(session, labeler, force=force, limit=limit, progress=show_progress))


@cli.command("rank")
def rank_command() -> None:
    """Recompute post and competitor scores for every window."""
    with SessionLocal() as session:
        _report(rank_all(session))


@cli.command("refresh")
def refresh_command(
    discover: bool = typer.Option(False, "--discover", help="Also run discovery first."),
) -> None:
    """Run collect, label and rank in order."""
    _labeler_note()
    settings = get_settings()
    if not enabled_platforms(settings):
        typer.echo("No platform has keys in .env, so collecting is skipped.")
    with SessionLocal() as session, make_client() as client:
        for run in refresh(session, client, settings, discover=discover):
            _report(run)


if __name__ == "__main__":
    cli()
