"""User-operated UMass login for the read-only SharePoint scraper.

Run in your own terminal. Sign in and complete MFA yourself in the new browser.
This program never fills, reads, or records a password or MFA challenge.
"""

import argparse
import importlib
from datetime import UTC, datetime
from pathlib import Path

import httpx

from campus_notices.cache import atomic_json
from campus_notices.sharepoint import (
    LIST_URL,
    BrowserSessionTransport,
    _collection,
    endpoints,
    read_session,
    scoped_storage_state,
)
from campus_notices.sources import SourceError

ROOT = Path(__file__).resolve().parents[1]


def probe_items(client, prefix):
    """Check item-read permission with ONE page, even when SharePoint sends __next."""
    response = client.get(
        prefix + "/items?$select=Id&$top=1", headers={"Accept": "application/json;odata=verbose"}
    )
    if response.status_code != 200:
        raise SourceError(f"SharePoint item-access check returned HTTP {response.status_code}")
    try:
        payload = response.json()
        content = payload.get("d", payload)
        rows = content.get("results", content.get("value"))
        if not isinstance(rows, list):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise SourceError("SharePoint item-access check did not return a list") from None
    return len(rows)


def verify_and_save(context, page, playwright, destination, diagnostics):
    """Verify the open session and its saved form before replacing a working login."""
    now = datetime.now(UTC)
    spec = {"id": "umass-maintenance"}
    prefix = endpoints(spec)[1]
    # Do not gate authentication on page.url: sync Playwright's cached page state
    # may be stale while input() blocks, and sign-in can finish in a different tab.
    # This real request pumps browser events and validates the session itself.
    # The transport restricts every GET to the known UMass list, independent of tabs.
    with httpx.Client(
        transport=BrowserSessionTransport(
            context.request,
            prefix=prefix,
            diagnostics=diagnostics,
        )
    ) as client:
        fields = _collection(client, prefix + "/fields?$select=Title,InternalName", prefix)
        item_count = probe_items(client, prefix)
        if not fields:
            raise SourceError("SharePoint list metadata was empty")

    state = scoped_storage_state(context.storage_state(), now)
    pages = [tab for tab in context.pages if not tab.is_closed()]
    # The original sign-in tab may have closed after opening a new one. A blank
    # temporary tab also works for reading the browser's user agent if all are closed.
    agent_page = pages[-1] if pages else context.new_page()
    try:
        user_agent = agent_page.evaluate("navigator.userAgent")
    finally:
        if not pages:
            agent_page.close()
    # Confirm the hourly worker can use the saved state without an open browser.
    restored = playwright.request.new_context(storage_state=state, user_agent=user_agent)
    try:
        with httpx.Client(
            transport=BrowserSessionTransport(
                restored,
                prefix=prefix,
                diagnostics=diagnostics,
            )
        ) as client:
            _collection(client, prefix + "/fields?$select=Title,InternalName", prefix)
            probe_items(client, prefix)
    finally:
        restored.dispose()
    atomic_json(
        destination,
        {
            **state,
            "user_agent": user_agent,
            "version": 2,
            "saved_at": datetime.now(UTC).isoformat(),
        },
    )
    return item_count


def verification_loop(context, page, playwright, destination, *, diagnostic_path, prompt=input):
    """Keep the user's signed-in window open on failure instead of forcing a new login."""
    verifier = verify_and_save
    while True:
        answer = prompt(
            "Once the notices are visible, press Enter to verify (r reloads helper; q cancels): "
        )
        if answer.strip().lower() == "q":
            return False
        if answer.strip().lower() == "r":
            # Apply a helper fix while retaining the user's open authenticated context.
            # Reload only our known local module, never a path or code from input.
            module = importlib.reload(importlib.import_module("scripts.login_notices"))
            verifier = module.verify_and_save
            print("Updated verification code loaded; keeping the same browser session.", flush=True)
        diagnostics = []
        try:
            count = verifier(context, page, playwright, destination, diagnostics)
        except SourceError as exc:
            atomic_json(
                diagnostic_path,
                {
                    "helper_version": 5,
                    "attempted_at": datetime.now(UTC).isoformat(),
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "requests": diagnostics,
                },
            )
            print(f"Verification failed: {exc}", flush=True)
            print(
                "The browser is still open and your current login is preserved. "
                "Do not sign in repeatedly. The error above identifies the failed request.",
                flush=True,
            )
            print(f"Safe diagnostic details saved to {diagnostic_path.name}.", flush=True)
            continue
        atomic_json(
            diagnostic_path,
            {
                "helper_version": 5,
                "attempted_at": datetime.now(UTC).isoformat(),
                "status": "success",
                "sample_item_count": count,
                "requests": diagnostics,
            },
        )
        print("Sign-in verified: SharePoint list access succeeded.")
        print("Saved-session check also passed; the scraper can run without this browser.")
        print(f"Session saved: {destination.resolve()}. Do not share this file.")
        print("Next: .\\refresh-notices.cmd --rules-only")
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=("chrome", "msedge", "chromium"), default="chrome")
    args = parser.parse_args()
    print(
        "UMass login helper v5 - checks item access in both browser and saved session.", flush=True
    )
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('Install once: .\\.venv\\Scripts\\python.exe -m pip install -e ".[pipeline,scraper]"')
        raise SystemExit(1) from None

    destination = ROOT / "data/private/sharepoint-session.json"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel=None if args.browser == "chromium" else args.browser,
                headless=False,
            )
            try:
                context_options = {}
                if destination.exists():
                    try:
                        state, _ = read_session(destination, datetime.now(UTC))
                        context_options["storage_state"] = state
                    except SourceError:
                        pass
                context = browser.new_context(**context_options)
                page = context.new_page()
                print("Sign in to UMass in the new browser and complete MFA yourself.", flush=True)
                try:
                    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
                except PlaywrightTimeout:
                    print(
                        "The page is taking longer to load. Finish opening the list in the browser."
                    )
                success = verification_loop(
                    context,
                    page,
                    playwright,
                    destination,
                    diagnostic_path=ROOT / "data/private/sharepoint-login-diagnostic.json",
                )
                if not success:
                    print("Verification cancelled; previous saved session unchanged.")
                    raise SystemExit(1)
            finally:
                browser.close()
    except (KeyboardInterrupt, EOFError):
        print("Sign-in cancelled. Previous saved session unchanged.")
        raise SystemExit(1) from None
    except Exception as exc:
        if isinstance(exc, SourceError):
            print(str(exc))
        else:
            print(f"Sign-in could not be verified ({type(exc).__name__}). No session was replaced.")
            print(
                "Check your connection and Chrome. "
                "Alternatively: .\\login-notices.cmd --browser msedge"
            )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
