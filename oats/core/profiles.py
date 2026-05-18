"""
Feature profiles for coder — configurable packaging for different device targets.

Profiles let you run coder as slim and lightweight or as fully featured.
Set via CODER_PROFILE env var or programmatically.

Built-in profiles:

    - **minimal** — Core file/code tools only. No network, no browser, no cloud.
      Ideal for air-gapped devices, embedded, or CI runners.
    - **standard** — Adds web search, S3, planning, memory, agents.
      Good default for most dev workstations.
    - **full** — Everything enabled: browser/playwright, MCP, LSP, scraping
    - **custom** — User controls each feature group via individual env vars.

Individual feature groups can always be overridden regardless of profile::

    CODER_FEATURE_BROWSER=0    disables browser even on 'full'
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FeatureProfile:
    """Declares which feature groups are enabled for a profile."""
    name: str

    # Core (always on — cannot be disabled)
    core_tools: bool = True        # read, write, edit, glob, grep, bash

    # Network & search
    web_tools: bool = True         # webfetch, websearch, playwright_search
    s3_storage: bool = False       # S3 upload/download
    database: bool = False         # PostgreSQL connections
    redis: bool = False            # Redis cache

    # Browser & scraping
    browser: bool = False          # /browse -i, -gui, playwright
    scraping: bool = False         # /browse -scrape, credential_manager

    mcp: bool = False              # MCP protocol tools

    # Advanced
    lsp: bool = False              # LSP code intelligence
    planning: bool = True          # plan enter/exit/status
    memory: bool = True            # memory read/write/delete
    agents: bool = True            # sub-agent tools


# ── Built-in profiles ───────────────────────────────────────────────

PROFILES: dict[str, FeatureProfile] = {
    "minimal": FeatureProfile(
        name="minimal",
        web_tools=False,
        planning=False,
        memory=False,
        agents=False,
    ),
    "standard": FeatureProfile(
        name="standard",
        web_tools=True,
        s3_storage=True,
        planning=True,
        memory=True,
        agents=True,
    ),
    "full": FeatureProfile(
        name="full",
        web_tools=True,
        s3_storage=True,
        database=True,
        redis=True,
        browser=True,
        scraping=True,
        mcp=True,
        lsp=True,
        planning=True,
        memory=True,
        agents=True,
    ),
}


# ── Profile resolution ──────────────────────────────────────────────

_active_profile: FeatureProfile | None = None


def _env_override(group: str) -> bool | None:
    """Check for an explicit CODER_FEATURE_<GROUP> env override.

    Returns True/False if set, None if not set (defer to profile).
    """
    val = os.getenv(f"CODER_FEATURE_{group.upper()}")
    if val is None:
        return None
    return val.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def get_profile() -> FeatureProfile:
    """Return the active feature profile (cached after first call)."""
    global _active_profile
    if _active_profile is not None:
        return _active_profile

    name = os.getenv("CODER_PROFILE", "standard").strip().lower()
    if name == "custom":
        # Build entirely from individual env vars
        _active_profile = FeatureProfile(
            name="custom",
            web_tools=_env_override("web_tools") or False,
            s3_storage=_env_override("s3_storage") or False,
            database=_env_override("database") or False,
            redis=_env_override("redis") or False,
            browser=_env_override("browser") or False,
            scraping=_env_override("scraping") or False,
            mcp=_env_override("mcp") or False,
            lsp=_env_override("lsp") or False,
            planning=_env_override("planning") if _env_override("planning") is not None else True,
            memory=_env_override("memory") if _env_override("memory") is not None else True,
            agents=_env_override("agents") if _env_override("agents") is not None else True,
        )
    else:
        base = PROFILES.get(name, PROFILES["standard"])
        _active_profile = base

    return _active_profile


def is_feature_enabled(group: str) -> bool:
    """Check if a feature group is enabled, with env override support.

    Env override always wins:
        CODER_FEATURE_BROWSER=1  → True  (even if profile is 'minimal')

    Otherwise falls back to the active profile.
    """
    override = _env_override(group)
    if override is not None:
        return override

    profile = get_profile()
    return getattr(profile, group, False)


def reset_profile() -> None:
    """Clear cached profile (for testing)."""
    global _active_profile
    _active_profile = None


def list_profiles() -> list[str]:
    """Return the names of all built-in profiles."""
    return list(PROFILES.keys())


def describe_profile(name: str | None = None) -> dict[str, bool]:
    """Return a dict of group -> enabled for a profile (or the active one)."""
    if name:
        profile = PROFILES.get(name, get_profile())
    else:
        profile = get_profile()

    groups = [
        "core_tools", "web_tools", "s3_storage", "database", "redis",
        "browser", "scraping", "mcp", "lsp", "planning",
        "memory", "agents",
    ]
    result = {}
    for g in groups:
        override = _env_override(g)
        if override is not None:
            result[g] = override
        else:
            result[g] = getattr(profile, g, False)
    return result
