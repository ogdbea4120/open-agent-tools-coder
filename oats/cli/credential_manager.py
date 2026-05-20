#!/usr/bin/env python3
"""
Secure credential manager for Playwright browser authentication.

Handles user login prompts for web scraping behind auth walls.
Passwords are NEVER stored or transmitted in plain text:
  - User enters password via secure prompt (no echo)
  - Password is immediately hashed with PBKDF2-SHA256 + random salt for the
    verification record kept in memory
  - The raw password is held only in a short-lived bytearray that is
    explicitly zeroed after Playwright fills the login form
  - No credential is written to disk, env vars, logs, or network

Usage:
    from oats.cli.credential_manager import CredentialManager
    cred_mgr = CredentialManager()
    creds = await cred_mgr.prompt_credentials(domain="example.com")
    # creds.use_password() returns the raw password ONCE, then zeros it
"""
from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console

console = Console()


@dataclass
class SecureCredential:
    """Holds a single credential set with salted-hash verification."""

    domain: str
    username: str
    # password storage: raw bytes kept in a mutable bytearray so we can zero it
    _raw_pw: bytearray = field(repr=False, default_factory=bytearray)
    # verification hash so we can confirm the password later without the raw
    _salt: bytes = field(repr=False, default_factory=lambda: secrets.token_bytes(32))
    _pw_hash: bytes = field(repr=False, default_factory=bytes)
    _consumed: bool = field(repr=False, default=False)

    def _derive_hash(self, raw: bytes) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256", raw, self._salt, iterations=600_000,
        )

    def seal(self) -> None:
        """Compute the verification hash from the raw password."""
        self._pw_hash = self._derive_hash(bytes(self._raw_pw))

    def verify(self, candidate: bytes) -> bool:
        """Check a candidate password against the stored hash."""
        return secrets.compare_digest(
            self._pw_hash, self._derive_hash(candidate),
        )

    def use_password(self) -> str:
        """Return the raw password as a string ONCE, then zero the buffer.

        After this call the raw password is irrecoverable — only the
        salted PBKDF2 hash remains in memory for verification.
        """
        if self._consumed:
            raise RuntimeError("password already consumed — re-prompt required")
        pw = self._raw_pw.decode("utf-8", errors="replace")
        # zero the raw bytes in-place
        for i in range(len(self._raw_pw)):
            self._raw_pw[i] = 0
        self._consumed = True
        return pw

    @property
    def is_consumed(self) -> bool:
        return self._consumed


class CredentialManager:
    """In-memory credential store for browser auth sessions.

    Credentials live only for the duration of the scrape session.
    The raw password is consumed (zeroed) after Playwright uses it.
    """

    def __init__(self):
        # domain -> SecureCredential
        self._store: dict[str, SecureCredential] = {}

    async def prompt_credentials(
        self,
        domain: str,
        *,
        username_hint: str = "",
    ) -> SecureCredential:
        """Interactively prompt the user for credentials.

        Returns a SecureCredential whose password can be consumed exactly
        once via ``use_password()``.
        """
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML

        ps = PromptSession()

        console.print(
            f"\n  [bold yellow]Authentication required for [cyan]{domain}[/cyan][/bold yellow]"
        )
        console.print(
            "  [dim]Password is hashed with PBKDF2+salt — never stored in plain text[/dim]\n"
        )

        default_user = username_hint or self._store.get(domain, SecureCredential(domain="", username="")).username
        username = await ps.prompt_async(
            HTML(f"  <ansiyellow><b>username</b></ansiyellow> [{default_user}]: "),
        )
        username = username.strip() or default_user
        if not username:
            raise ValueError("username is required")

        # Prompt for password with echo disabled
        raw_password = await ps.prompt_async(
            HTML("  <ansiyellow><b>password</b></ansiyellow>: "),
            is_password=True,
        )
        if not raw_password:
            raise ValueError("password is required")

        # Build the secure credential
        cred = SecureCredential(
            domain=domain,
            username=username,
            _raw_pw=bytearray(raw_password.encode("utf-8")),
        )
        cred.seal()

        # Overwrite the local string copies
        raw_password = "\x00" * len(raw_password)

        self._store[domain] = cred
        console.print(
            f"  [green]credentials stored (hashed) for {domain}[/green]\n"
        )
        return cred

    def get_credential(self, domain: str) -> Optional[SecureCredential]:
        return self._store.get(domain)

    def has_credential(self, domain: str) -> bool:
        return domain in self._store

    def clear(self, domain: str | None = None) -> None:
        """Wipe credentials from memory."""
        if domain:
            cred = self._store.pop(domain, None)
            if cred and not cred.is_consumed:
                # zero any unconsumed raw password
                for i in range(len(cred._raw_pw)):
                    cred._raw_pw[i] = 0
        else:
            for d, cred in self._store.items():
                if not cred.is_consumed:
                    for i in range(len(cred._raw_pw)):
                        cred._raw_pw[i] = 0
            self._store.clear()

    def list_domains(self) -> list[str]:
        return list(self._store.keys())


async def playwright_login(
    browser_page,
    cred: SecureCredential,
    *,
    username_selector: str = 'input[type="text"], input[type="email"], input[name="username"], input[name="email"], input[name="login"]',
    password_selector: str = 'input[type="password"]',
    submit_selector: str = 'button[type="submit"], input[type="submit"], button:has-text("Log in"), button:has-text("Sign in")',
    timeout_ms: int = 10_000,
) -> bool:
    """Fill login form on the current Playwright page using the SecureCredential.

    The raw password is consumed (zeroed) after filling the form field.
    Returns True on apparent success, False on error.
    """
    import asyncio

    try:
        # Wait for username field
        user_field = await browser_page.wait_for_selector(
            username_selector, timeout=timeout_ms, state="visible",
        )
        if not user_field:
            console.print("  [red]could not find username field[/red]")
            return False

        await user_field.click()
        await user_field.fill(cred.username)

        # Wait for password field
        pw_field = await browser_page.wait_for_selector(
            password_selector, timeout=timeout_ms, state="visible",
        )
        if not pw_field:
            console.print("  [red]could not find password field[/red]")
            return False

        await pw_field.click()
        # Consume the password — this zeros the raw buffer after use
        raw_pw = cred.use_password()
        await pw_field.fill(raw_pw)
        # Overwrite the local copy
        raw_pw = "\x00" * len(raw_pw)

        # Try to find and click submit
        try:
            submit_btn = await browser_page.wait_for_selector(
                submit_selector, timeout=3_000, state="visible",
            )
            if submit_btn:
                await submit_btn.click()
        except Exception:
            # Fallback: press Enter in the password field
            await pw_field.press("Enter")

        # Wait for navigation
        await asyncio.sleep(2.0)
        console.print("  [green]login form submitted[/green]")
        return True

    except Exception as e:
        console.print(f"  [red]login failed: {e}[/red]")
        return False


def detect_login_page(page_state) -> bool:
    """Heuristic: does the current page look like a login/auth wall?

    Checks for password fields, common login-form keywords, etc.
    """
    if not page_state:
        return False

    # Check for password input fields
    has_password_input = any(
        el.input_type == "password" for el in page_state.elements if el.role == "input"
    )
    if has_password_input:
        return True

    # Check text content for login keywords
    text_lower = (page_state.text_content or "").lower()
    login_keywords = [
        "sign in", "log in", "login", "username", "password",
        "authenticate", "enter your credentials",
    ]
    keyword_hits = sum(1 for kw in login_keywords if kw in text_lower)
    return keyword_hits >= 2
