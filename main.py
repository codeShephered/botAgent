"""
main.py — LinkedIn Leather Goods Bot Orchestrator
Run: python main.py [--dry-run] [--region india] [--keyword "leather bags"]
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Load environment variables
load_dotenv(".env")

# Resolve template variables from env
def _resolve_env(value):
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        key = value[2:-1]
        return os.getenv(key, "")
    return value

def load_config(path: str = "config/config.yaml") -> dict:
    """Load and resolve YAML configuration."""
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    # Resolve env variables recursively
    def resolve(obj):
        if isinstance(obj, dict):
            return {k: resolve(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [resolve(i) for i in obj]
        else:
            return _resolve_env(obj)

    return resolve(raw)


console = Console()


def print_banner():
    console.print(Panel.fit(
        "[bold white]🧳 LinkedIn Leather Goods Bot[/bold white]\n"
        "[dim]Automated Outreach System — Compliant with LinkedIn ToS[/dim]",
        border_style="brown",
        padding=(1, 4),
    ))


def run_bot(config: dict, dry_run: bool = False,
            region_filter: str = None, keyword_filter: str = None):
    """Main bot execution pipeline."""

    from modules.crawler        import LinkedInCrawler
    from modules.email_generator import EmailGenerator, EmailSender
    from modules.logger         import ActivityLogger
    from modules.database       import init_db, LeatherRequirement, OptOutList

    # ── Init systems ────────────────────────────────────────────
    engine, Session = init_db(config["database"]["sqlite_path"])
    activity_log    = ActivityLogger(config)
    crawler         = LinkedInCrawler(config)
    email_gen       = EmailGenerator(config)
    email_sender    = EmailSender(config)
    db              = Session()

    session_stats = {
        "started_at":    datetime.utcnow().isoformat(),
        "dry_run":       dry_run,
        "posts_found":   0,
        "emails_sent":   0,
        "skipped_opted_out": 0,
        "skipped_no_email":  0,
        "errors":        0,
    }

    # ── Load opt-out list ────────────────────────────────────────
    opted_out_emails = {
        r.email for r in db.query(OptOutList).all()
    }

    # ── Determine keywords & countries to crawl ─────────────────
    keywords = (
        [keyword_filter] if keyword_filter
        else config["search"]["keywords"]
    )

    all_regions = config["regions"]
    if region_filter:
        regions_to_crawl = {
            region_filter: all_regions.get(region_filter, [])
        }
    else:
        regions_to_crawl = all_regions

    all_country_codes = []
    for region_countries in regions_to_crawl.values():
        all_country_codes.extend(region_countries)

    console.print(f"\n[bold]🔍 Keywords:[/bold] {', '.join(keywords)}")
    console.print(f"[bold]🌍 Countries:[/bold] {len(all_country_codes)} countries")
    console.print(f"[bold]🧪 Dry Run:[/bold] {'YES — no emails will be sent' if dry_run else 'NO'}\n")

    seen_post_ids = set()

    # ── Crawl + Process Loop ────────────────────────────────────
    for keyword in keywords:
        console.rule(f"[bold brown]Keyword: {keyword}[/bold brown]")

        for post in crawler.search_posts(
            keyword=keyword,
            country_codes=all_country_codes,
            days_back=config["search"]["date_range_days"]
        ):
            # Deduplicate
            if post.post_id in seen_post_ids:
                continue
            seen_post_ids.add(post.post_id)
            session_stats["posts_found"] += 1

            console.print(
                f"  📌 [cyan]{post.company_name or 'Unknown'}[/cyan] "
                f"| {post.region} ({post.country_code}) "
                f"| Email: {'✅' if post.email_valid else '❌'}"
            )

            # Check opt-out
            if post.contact_email in opted_out_emails:
                console.print(
                    f"     [yellow]⚠ Opted out — skipping[/yellow]"
                )
                session_stats["skipped_opted_out"] += 1
                continue

            # Store in DB (skip duplicate post_urls)
            existing = db.query(LeatherRequirement).filter_by(
                post_url=post.post_url
            ).first()
            if not existing:
                record = LeatherRequirement(
                    post_id=post.post_id,
                    post_url=post.post_url,
                    content=post.content,
                    company_name=post.company_name,
                    poster_name=post.poster_name,
                    location=post.location,
                    region=post.region,
                    country_code=post.country_code,
                    date_posted=post.date_posted,
                    keyword_match=post.keyword_match,
                    contact_email=post.contact_email,
                    linkedin_profile=post.linkedin_profile,
                    company_website=post.company_website,
                    email_valid=post.email_valid,
                )
                db.add(record)
                db.commit()

            # Send email if valid email found
            if not post.email_valid:
                session_stats["skipped_no_email"] += 1
                continue

            subject, html_body, text_body = email_gen.render(post)

            if dry_run:
                console.print(
                    f"     [dim]📧 DRY RUN — would send to: "
                    f"{post.contact_email}[/dim]"
                )
                console.print(f"     [dim]Subject: {subject}[/dim]")
                activity_log.log_post(post, email_sent=False)
                continue

            success, msg_id = email_sender.send(
                to_email=post.contact_email,
                to_name=post.poster_name or "Sir/Madam",
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )

            sent_at = datetime.utcnow() if success else None

            if success:
                session_stats["emails_sent"] += 1
                console.print(
                    f"     [green]✅ Email sent to {post.contact_email}[/green]"
                )
                # Update DB record
                if existing:
                    existing.email_sent = True
                    existing.email_sent_at = sent_at
                    db.commit()
            else:
                session_stats["errors"] += 1
                console.print(
                    f"     [red]❌ Email failed: {msg_id}[/red]"
                )

            activity_log.log_post(
                post,
                email_sent=success,
                email_sent_at=sent_at,
                error="" if success else msg_id
            )

    db.close()

    # ── Session Summary ─────────────────────────────────────────
    session_stats["completed_at"] = datetime.utcnow().isoformat()
    activity_log.log_session(session_stats)

    table = Table(title="📊 Session Summary", border_style="brown")
    table.add_column("Metric",  style="bold")
    table.add_column("Count",   justify="right", style="cyan")
    table.add_row("Posts Found",       str(session_stats["posts_found"]))
    table.add_row("Emails Sent",       str(session_stats["emails_sent"]))
    table.add_row("Skipped (Opted Out)", str(session_stats["skipped_opted_out"]))
    table.add_row("Skipped (No Email)", str(session_stats["skipped_no_email"]))
    table.add_row("Errors",            str(session_stats["errors"]))
    console.print("\n")
    console.print(table)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="LinkedIn Leather Goods Outreach Bot"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run without sending any emails"
    )
    parser.add_argument(
        "--region", type=str, default=None,
        help="Filter to specific region (europe, india, east_asia, americas, australia)"
    )
    parser.add_argument(
        "--keyword", type=str, default=None,
        help="Run for a single keyword only"
    )
    parser.add_argument(
        "--config", type=str, default="config/config.yaml",
        help="Path to configuration file"
    )
    args = parser.parse_args()

    #print_banner()

    config = load_config(args.config)
    run_bot(
        config=config,
        dry_run=args.dry_run,
        region_filter=args.region,
        keyword_filter=args.keyword,
    )
