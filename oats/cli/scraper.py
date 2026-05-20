#!/usr/bin/env python3
"""
Web page scraper for coder2 /browse -scrape.

Extracts structured data from a web page via Playwright, converts to
JSON and Parquet, and uploads to the task's S3 directory.

Pipeline:
    Playwright page → structured dict → JSON file → Parquet file → S3

Usage:
    from oats.cli.scraper import scrape_page, ScrapeResult
    result = await scrape_page(browser_page, session_id="abc123")
"""
from __future__ import annotations

import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import pandas as pd
import ujson as json

from rich.console import Console

console = Console()


@dataclass
class ScrapeResult:
    """Result of a single page scrape."""

    url: str
    domain: str
    title: str
    scraped_at: str
    text_content: str
    links: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    headings: list[dict] = field(default_factory=list)
    forms: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    tables: list[list[dict]] = field(default_factory=list)

    # output paths filled after export
    json_path: Optional[str] = None
    parquet_path: Optional[str] = None
    s3_json_loc: Optional[str] = None
    s3_parquet_loc: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "domain": self.domain,
            "title": self.title,
            "scraped_at": self.scraped_at,
            "text_content": self.text_content,
            "link_count": len(self.links),
            "image_count": len(self.images),
            "heading_count": len(self.headings),
            "form_count": len(self.forms),
            "table_count": len(self.tables),
            "meta": self.meta,
            "links": self.links,
            "images": self.images,
            "headings": self.headings,
            "forms": self.forms,
            "tables": self.tables,
        }


# ── JavaScript extraction snippets ─────────────────────────────────

_JS_SCRAPE_LINKS = """() => {
    return Array.from(document.querySelectorAll('a[href]')).map(a => ({
        text: (a.innerText || '').trim().substring(0, 200),
        href: a.href,
        rel: a.getAttribute('rel') || '',
    })).filter(l => l.text && l.href);
}"""

_JS_SCRAPE_IMAGES = """() => {
    return Array.from(document.querySelectorAll('img')).map(img => ({
        src: img.src || '',
        alt: (img.alt || '').substring(0, 200),
        width: img.naturalWidth || img.width || 0,
        height: img.naturalHeight || img.height || 0,
    })).filter(i => i.src);
}"""

_JS_SCRAPE_HEADINGS = """() => {
    return Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6')).map(h => ({
        level: parseInt(h.tagName.substring(1)),
        text: (h.innerText || '').trim().substring(0, 300),
    })).filter(h => h.text);
}"""

_JS_SCRAPE_META = """() => {
    const meta = {};
    document.querySelectorAll('meta').forEach(m => {
        const name = m.getAttribute('name') || m.getAttribute('property') || '';
        const content = m.getAttribute('content') || '';
        if (name && content) meta[name] = content.substring(0, 500);
    });
    meta['charset'] = document.characterSet || '';
    meta['lang'] = document.documentElement.lang || '';
    const canonical = document.querySelector('link[rel="canonical"]');
    if (canonical) meta['canonical'] = canonical.href;
    return meta;
}"""

_JS_SCRAPE_FORMS = """() => {
    return Array.from(document.querySelectorAll('form')).map(f => ({
        action: f.action || '',
        method: (f.method || 'get').toUpperCase(),
        id: f.id || '',
        name: f.name || '',
        fields: Array.from(f.querySelectorAll('input, select, textarea')).map(el => ({
            tag: el.tagName.toLowerCase(),
            type: el.type || 'text',
            name: el.name || el.id || '',
            placeholder: (el.placeholder || '').substring(0, 100),
            required: el.required || false,
        })),
    }));
}"""

_JS_SCRAPE_TABLES = """() => {
    return Array.from(document.querySelectorAll('table')).slice(0, 20).map(table => {
        const rows = [];
        table.querySelectorAll('tr').forEach(tr => {
            const cells = [];
            tr.querySelectorAll('td, th').forEach(cell => {
                cells.push({
                    text: (cell.innerText || '').trim().substring(0, 500),
                    tag: cell.tagName.toLowerCase(),
                });
            });
            if (cells.length > 0) rows.push(cells);
        });
        return rows;
    }).filter(t => t.length > 0);
}"""

_JS_FULL_TEXT = """() => {
    const clone = document.body.cloneNode(true);
    clone.querySelectorAll('script, style, noscript, svg, path').forEach(
        el => el.remove()
    );
    return clone.innerText;
}"""


async def scrape_page(
    browser_page,
    *,
    session_id: str | None = None,
    s3_prefix: str | None = None,
    upload_to_s3: bool = True,
    scroll_full_page: bool = True,
    verbose: bool = False,
) -> ScrapeResult:
    """Extract structured data from the current Playwright page.

    Returns a ScrapeResult with JSON and Parquet files written locally,
    and optionally uploaded to S3.
    """
    url = browser_page.url
    parsed = urlparse(url)
    domain = parsed.netloc
    title = await browser_page.title() or ""
    scraped_at = datetime.now(timezone.utc).isoformat()

    console.print(f"  [dim]scraping {url} ...[/dim]")

    # Optionally scroll to bottom to trigger lazy-loaded content
    if scroll_full_page:
        try:
            await browser_page.evaluate(
                "window.scrollTo(0, document.documentElement.scrollHeight)"
            )
            import asyncio
            await asyncio.sleep(1.5)
            await browser_page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    # Extract all data in parallel-ish fashion
    text_content = ""
    links = []
    images = []
    headings = []
    meta = {}
    forms = []
    tables = []

    try:
        text_content = await browser_page.evaluate(_JS_FULL_TEXT) or ""
    except Exception as e:
        console.print(f"  [yellow]text extraction warning: {e}[/yellow]")

    try:
        links = await browser_page.evaluate(_JS_SCRAPE_LINKS) or []
    except Exception:
        pass

    try:
        images = await browser_page.evaluate(_JS_SCRAPE_IMAGES) or []
    except Exception:
        pass

    try:
        headings = await browser_page.evaluate(_JS_SCRAPE_HEADINGS) or []
    except Exception:
        pass

    try:
        meta = await browser_page.evaluate(_JS_SCRAPE_META) or {}
    except Exception:
        pass

    try:
        forms = await browser_page.evaluate(_JS_SCRAPE_FORMS) or []
    except Exception:
        pass

    try:
        tables = await browser_page.evaluate(_JS_SCRAPE_TABLES) or []
    except Exception:
        pass

    result = ScrapeResult(
        url=url,
        domain=domain,
        title=title,
        scraped_at=scraped_at,
        text_content=text_content,
        links=links,
        images=images,
        headings=headings,
        forms=forms,
        meta=meta,
        tables=tables,
    )

    console.print(
        f"  [green]scraped:[/green] {len(links)} links, {len(images)} images, "
        f"{len(headings)} headings, {len(forms)} forms, {len(tables)} tables, "
        f"{len(text_content)} chars text"
    )

    # ── Export to JSON + Parquet ─────────────────────────────────────
    safe_domain = re.sub(r'[^a-zA-Z0-9._-]', '_', domain)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base_name = f"scrape-{safe_domain}-{ts}"

    tmp_dir = tempfile.mkdtemp(prefix="cdr_scrape_")
    json_path = os.path.join(tmp_dir, f"{base_name}.json")
    parquet_path = os.path.join(tmp_dir, f"{base_name}.pq")

    # Write JSON
    scrape_dict = result.to_dict()
    with open(json_path, "w") as f:
        json.dump(scrape_dict, f, ensure_ascii=True)
    result.json_path = json_path
    console.print(f"  [green]json:[/green] {json_path}")

    # Write Parquet — flatten the top-level data into a single-row DataFrame
    # plus a separate links DataFrame for tabular consumption
    try:
        # Main metadata row
        meta_row = {
            "url": url,
            "domain": domain,
            "title": title,
            "scraped_at": scraped_at,
            "text_length": len(text_content),
            "link_count": len(links),
            "image_count": len(images),
            "heading_count": len(headings),
            "form_count": len(forms),
            "table_count": len(tables),
            "text_content": text_content[:50_000],  # cap for parquet cell size
        }
        # Add meta tags as columns
        for mk, mv in meta.items():
            col_name = f"meta_{re.sub(r'[^a-zA-Z0-9_]', '_', mk)}"
            meta_row[col_name] = str(mv)[:500]

        df_meta = pd.DataFrame([meta_row])
        df_meta.to_parquet(parquet_path, engine="pyarrow")
        result.parquet_path = parquet_path
        console.print(f"  [green]parquet:[/green] {parquet_path}")

        # Also write a links parquet if there are links
        if links:
            links_pq = os.path.join(tmp_dir, f"{base_name}-links.pq")
            df_links = pd.DataFrame(links)
            df_links["source_url"] = url
            df_links["source_domain"] = domain
            df_links["scraped_at"] = scraped_at
            df_links.to_parquet(links_pq, engine="pyarrow")
            console.print(f"  [green]links parquet:[/green] {links_pq}")

    except Exception as e:
        console.print(f"  [yellow]parquet export warning: {e}[/yellow]")

    # ── Upload to S3 ────────────────────────────────────────────────
    if upload_to_s3:
        if os.getenv('CODER_S3_DISABLED', '0') == '0':
            if verbose:
                console.print('s3 upload disabled')
        else:
            try:
                _upload_scrape_to_s3(result, s3_prefix=s3_prefix, session_id=session_id, verbose=verbose)
            except Exception as e:
                console.print(f"  [yellow]s3 upload skipped: {e}[/yellow]")

    return result


def _upload_scrape_to_s3(
    result: ScrapeResult,
    s3_prefix: str | None = None,
    session_id: str | None = None,
    verbose: bool = False,
) -> None:
    """Upload scrape artifacts (JSON + Parquet) to S3."""
    from oats.s3.upload_file import upload_file

    if s3_prefix is None:
        bucket = os.getenv("CODER_S3_BUCKET", "tasks1")
        date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
        sid = session_id or "nosession"
        s3_prefix = f"s3://{bucket}/data/scrapes/{date_prefix}/{sid}"

    if result.json_path and os.path.exists(result.json_path):
        json_key = f"{s3_prefix}/{os.path.basename(result.json_path)}"
        ok, loc = upload_file(local_path=result.json_path, s3_loc=json_key, verbose=verbose)
        if ok:
            result.s3_json_loc = loc
            console.print(f"  [green]s3 json:[/green] {loc}")

    if result.parquet_path and os.path.exists(result.parquet_path):
        pq_key = f"{s3_prefix}/{os.path.basename(result.parquet_path)}"
        ok, loc = upload_file(local_path=result.parquet_path, s3_loc=pq_key, verbose=verbose)
        if ok:
            result.s3_parquet_loc = loc
            console.print(f"  [green]s3 parquet:[/green] {loc}")

    # Upload links parquet if it exists
    if result.parquet_path:
        links_pq = result.parquet_path.replace(".pq", "-links.pq")
        if os.path.exists(links_pq):
            links_key = f"{s3_prefix}/{os.path.basename(links_pq)}"
            ok, loc = upload_file(local_path=links_pq, s3_loc=links_key, verbose=verbose)
            if ok:
                console.print(f"  [green]s3 links:[/green] {loc}")


async def run_scrape_browser(
    start_url: str,
    *,
    session_id: str | None = None,
    s3_prefix: str | None = None,
    with_auth: bool = False,
) -> Optional[ScrapeResult]:
    """One-shot scrape: launch browser, optionally authenticate, scrape, close.

    This is the main entry point for ``/browse -scrape <url>``.
    """
    import asyncio

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        console.print("  [red]playwright is not installed[/red]")
        console.print("  [dim]install: pip install playwright && playwright install chromium[/dim]")
        return None

    console.print(f"\n  [bold blue]Starting scrape of {start_url}...[/bold blue]")

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=2,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()

        if not start_url.startswith(("http://", "https://")):
            start_url = "https://" + start_url

        await page.goto(start_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(1.5)

        # Check for auth wall
        if with_auth:
            from oats.cli.credential_manager import (
                CredentialManager, detect_login_page, playwright_login,
            )
            from oats.cli.browser import TerminalBrowser

            # Quick snapshot to check for login page
            tb = TerminalBrowser()
            tb._page = page
            state = await tb._snapshot()

            if detect_login_page(state):
                console.print("  [yellow]login page detected — prompting for credentials[/yellow]")
                cred_mgr = CredentialManager()
                domain = urlparse(start_url).netloc
                cred = await cred_mgr.prompt_credentials(domain=domain)
                login_ok = await playwright_login(page, cred)
                if login_ok:
                    console.print("  [green]authenticated — continuing scrape[/green]")
                    await asyncio.sleep(2.0)
                else:
                    console.print("  [red]login may have failed — scraping anyway[/red]")
            # Clean up the temp TerminalBrowser reference
            tb._page = None

        # Scrape
        result = await scrape_page(
            page,
            session_id=session_id,
            s3_prefix=s3_prefix,
        )

        console.print(f"\n  [bold green]Scrape complete![/bold green]")
        console.print(f"  [dim]url: {result.url}[/dim]")
        console.print(f"  [dim]title: {result.title}[/dim]")
        if result.json_path:
            console.print(f"  [dim]json: {result.json_path}[/dim]")
        if result.parquet_path:
            console.print(f"  [dim]parquet: {result.parquet_path}[/dim]")
        if result.s3_json_loc:
            console.print(f"  [dim]s3 json: {result.s3_json_loc}[/dim]")
        if result.s3_parquet_loc:
            console.print(f"  [dim]s3 parquet: {result.s3_parquet_loc}[/dim]")

        return result

    except Exception as e:
        console.print(f"  [red]scrape failed: {e}[/red]")
        return None
    finally:
        try:
            await browser.close()
            await pw.stop()
        except Exception:
            pass
