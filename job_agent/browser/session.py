"""Playwright persistent browser profile (WhatsApp-Web style: login once, reuse session)."""

from __future__ import annotations

import fcntl
import os
import random
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Tuple

from job_agent.browser.paths import resolve_browser_user_data_dir


def _safe_close(context, pw) -> None:
    """Close browser context and playwright, each in its own try block."""
    try:
        context.close()
    except Exception:
        pass
    try:
        pw.stop()
    except Exception:
        pass


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


_DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]


def _pick_user_agent(cfg: Dict[str, Any]) -> str:
    import hashlib
    block = cfg.get("browser") if isinstance(cfg.get("browser"), dict) else {}
    explicit = (block.get("user_agent") or "").strip()
    if explicit:
        return explicit
    seed = str(block.get("user_data_dir") or "default")
    idx = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(_DEFAULT_USER_AGENTS)
    return _DEFAULT_USER_AGENTS[idx]


def _launch_persistent(cfg: Dict[str, Any], *, headless: bool, service: str = "linkedin"):
    from playwright.sync_api import sync_playwright

    block = cfg.get("browser") if isinstance(cfg.get("browser"), dict) else {}
    user_data = resolve_browser_user_data_dir(cfg, service=service)
    user_data.mkdir(parents=True, exist_ok=True)
    slow_mo = int(block.get("slow_mo_ms") or 0)
    pw = sync_playwright().start()

    vp_jitter_w = random.randint(-20, 20)
    vp_jitter_h = random.randint(-10, 10)

    extra_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]
    extra_from_cfg = block.get("extra_chromium_args")
    if isinstance(extra_from_cfg, list):
        extra_args.extend(extra_from_cfg)

    context = pw.chromium.launch_persistent_context(
        str(user_data),
        headless=headless,
        slow_mo=slow_mo,
        viewport={"width": 1280 + vp_jitter_w, "height": 900 + vp_jitter_h},
        locale=(block.get("locale") or "he-IL"),
        timezone_id=(block.get("timezone_id") or "Asia/Jerusalem"),
        user_agent=_pick_user_agent(cfg),
        color_scheme="light",
        args=extra_args,
        ignore_default_args=["--enable-automation"],
    )
    _STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['he-IL', 'he', 'en-US', 'en']});
    window.chrome = {runtime: {}};
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (params) =>
        params.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : origQuery(params);
    """
    for page in context.pages:
        page.add_init_script(_STEALTH_JS)
    context.on("page", lambda p: p.add_init_script(_STEALTH_JS))
    return pw, context


def page_is_linkedin_auth_wall(page, *, require_job_cards: bool = False) -> bool:
    """True when LinkedIn is showing login / auth wall instead of content."""
    url_low = (page.url or "").lower()
    title_low = (page.title() or "").lower()
    job_links = page.locator('a[href*="/jobs/view/"]').count()
    if "authwall" in url_low or "uas/login" in url_low:
        return True
    if (
        ("login" in url_low or "sign up" in title_low)
        and "session_redirect" not in url_low
        and job_links == 0
    ):
        return True
    if require_job_cards and "linkedin.com/jobs" in url_low and job_links == 0:
        return not _page_looks_logged_in(page)
    return False


def _page_looks_logged_in(page) -> bool:
    url = (page.url or "").lower()
    title = (page.title() or "").lower()
    if ("sign up" in title or "sign in" in title) and "jobs/search" not in url:
        if "login" in url or "signup" in url or "uas/login" in url:
            return False
    if "authwall" in url:
        return False
    if "linkedin.com/feed" in url:
        return True
    if "linkedin.com/jobs" in url and "login" not in url:
        return True
    if page.locator('a[href*="/jobs/view/"]').count() > 0:
        return True
    if page.locator('img.global-nav__me-photo, button.global-nav__primary-link-me-menu-trigger').count() > 0:
        return True
    return False


def linkedin_session_ready(cfg: Dict[str, Any], *, headless: bool = True) -> bool:
    """Quick check whether the saved browser profile can access LinkedIn jobs (not auth wall)."""
    if not playwright_available():
        return False
    pw, context = _launch_persistent(cfg, headless=headless, service="linkedin")
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(
            "https://www.linkedin.com/jobs/search/?keywords=devops&location=Israel",
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        time.sleep(2.5)
        if page_is_linkedin_auth_wall(page, require_job_cards=True):
            return False
        if page.locator('a[href*="/jobs/view/"]').count() > 0:
            return True
        return _page_looks_logged_in(page)
    except Exception:
        return False
    finally:
        _safe_close(context, pw)


def _human_scroll(page, times: int = 3) -> None:
    """Simulate human-like scrolling with random pauses."""
    for _ in range(times):
        distance = random.randint(200, 600)
        page.mouse.wheel(0, distance)
        time.sleep(random.uniform(0.8, 2.5))


def _visible_login_fields(page):
    """Visible email/password fields only (ignore hidden session_key inputs)."""
    email = page.locator(
        'input#username:visible, input[name="session_key"]:not([type="hidden"]):visible'
    )
    password = page.locator(
        'input#password:visible, input[name="session_password"]:not([type="hidden"]):visible'
    )
    return email, password


def _has_visible_login_form(page) -> bool:
    email, password = _visible_login_fields(page)
    return email.count() > 0 and password.count() > 0


def warm_linkedin_via_feed(page, target_url: str, *, via_jobs_nav: bool = False) -> bool:
    """Navigate feed → (optional Jobs) → target URL to avoid cold /jobs/search auth wall."""
    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(random.uniform(2, 4))
        if not _page_looks_logged_in(page):
            return False
        _human_scroll(page, times=random.randint(1, 3))
        if via_jobs_nav:
            try:
                jobs_nav = page.locator(
                    'a.global-nav__primary-link[href*="/jobs"], '
                    'a[href="https://www.linkedin.com/jobs/"], '
                    'a[href="/jobs/"]'
                )
                if jobs_nav.count() > 0:
                    jobs_nav.first.click(timeout=10_000)
                    time.sleep(random.uniform(2, 5))
                else:
                    page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded", timeout=60_000)
                    time.sleep(random.uniform(2, 4))
            except Exception:
                page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded", timeout=60_000)
                time.sleep(random.uniform(2, 4))
            _human_scroll(page, times=random.randint(1, 2))
        page.goto(target_url, wait_until="domcontentloaded", timeout=90_000)
        time.sleep(random.uniform(3, 6))
        _human_scroll(page, times=random.randint(1, 2))
        if via_jobs_nav:
            return page.locator('a[href*="/jobs/view/"]').count() > 0
        return _page_looks_logged_in(page) and not page_is_linkedin_auth_wall(page)
    except Exception as exc:
        print(f"linkedin warm navigation: {exc}", file=sys.stderr)
        return False


def warm_linkedin_for_jobs_search(page, search_url: str) -> bool:
    """Warm session via feed → Jobs before hitting /jobs/search."""
    if page.locator('a[href*="/jobs/view/"]').count() > 0:
        return True
    return warm_linkedin_via_feed(page, search_url, via_jobs_nav=True)


def _human_browse_feed(page) -> None:
    """Simulate realistic browsing: scroll feed, maybe click a post, wait."""
    time.sleep(random.uniform(2, 4))
    _human_scroll(page, times=random.randint(2, 5))

    try:
        links = page.locator("a[href*='/posts/'], a[href*='/pulse/'], span.feed-shared-actor__name")
        count = links.count()
        if count > 2:
            idx = random.randint(0, min(count - 1, 6))
            links.nth(idx).click(timeout=5000)
            time.sleep(random.uniform(4, 12))
            _human_scroll(page, times=random.randint(1, 3))
            page.go_back(timeout=15000)
            time.sleep(random.uniform(1, 3))
    except Exception:
        pass

    _human_scroll(page, times=random.randint(1, 3))


def linkedin_keepalive(cfg: Dict[str, Any], *, headless: bool = True) -> bool:
    """Visit LinkedIn feed with human-like browsing to keep session alive.

    Returns True if session is alive after the keepalive visit.
    """
    if not playwright_available():
        return False
    pw, context = _launch_persistent(cfg, headless=headless, service="linkedin")
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(
            "https://www.linkedin.com/feed/",
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        time.sleep(random.uniform(2, 4))
        if not _page_looks_logged_in(page):
            return False
        _human_browse_feed(page)
        page.goto(
            "https://www.linkedin.com/jobs/",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        time.sleep(random.uniform(2, 5))
        _human_scroll(page, times=random.randint(1, 2))
        return _page_looks_logged_in(page)
    except Exception:
        return False
    finally:
        _safe_close(context, pw)


def _linkedin_auto_login_on_page(page, cfg: Dict[str, Any]) -> bool:
    """Log in on an existing Playwright page (credentials from env)."""
    email = os.environ.get("LINKEDIN_EMAIL", "").strip()
    password = os.environ.get("LINKEDIN_PASSWORD", "").strip()
    if not email or not password:
        print("linkedin_auto_login: LINKEDIN_EMAIL/LINKEDIN_PASSWORD not set", file=sys.stderr)
        return False

    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(random.uniform(2, 3))
        if _page_looks_logged_in(page) and not page_is_linkedin_auth_wall(page):
            print("linkedin_auto_login: already logged in (feed)", file=sys.stderr)
            return True

        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(random.uniform(1.5, 3))

        if not _has_visible_login_form(page):
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60_000)
            time.sleep(random.uniform(2, 3))
            if _page_looks_logged_in(page):
                print("linkedin_auto_login: session active (no visible login form)", file=sys.stderr)
                return True
            print("linkedin_auto_login: login form not found", file=sys.stderr)
            return False

        email_field, pass_field = _visible_login_fields(page)

        email_field.first.click()
        time.sleep(random.uniform(0.3, 0.8))
        email_field.first.fill("")
        for ch in email:
            email_field.first.type(ch, delay=random.randint(30, 120))
        time.sleep(random.uniform(0.5, 1.0))

        pass_field.first.click()
        time.sleep(random.uniform(0.3, 0.8))
        for ch in password:
            pass_field.first.type(ch, delay=random.randint(30, 100))
        time.sleep(random.uniform(0.5, 1.5))

        submit = page.locator('button[type="submit"], button[data-litms-control-urn*="login-submit"]')
        if submit.count() > 0:
            submit.first.click()
        else:
            pass_field.first.press("Enter")
        time.sleep(random.uniform(4, 7))

        url_low = (page.url or "").lower()
        if "challenge" in url_low or "checkpoint" in url_low or "verification" in url_low:
            print(
                "linkedin_auto_login: 2FA/verification required — manual login needed",
                file=sys.stderr,
            )
            return False

        if _page_looks_logged_in(page):
            _human_browse_feed(page)
            print("linkedin_auto_login: login successful", file=sys.stderr)
            return True

        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30_000)
        time.sleep(3)
        if _page_looks_logged_in(page):
            print("linkedin_auto_login: login successful (redirect)", file=sys.stderr)
            return True

        print(f"linkedin_auto_login: login failed (url={page.url})", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"linkedin_auto_login: error: {exc}", file=sys.stderr)
        return False


def recover_linkedin_session_on_page(
    page,
    cfg: Dict[str, Any],
    *,
    search_url: str | None = None,
    need_job_cards: bool = False,
) -> bool:
    """Recover on the current page: warm jobs nav, then credential login if needed."""
    if page.locator('a[href*="/jobs/view/"]').count() > 0:
        return True

    if need_job_cards and search_url and _page_looks_logged_in(page):
        print("LinkedIn: warming jobs session (logged in, no job cards)...", file=sys.stderr)
        if warm_linkedin_for_jobs_search(page, search_url):
            return True

    if _page_looks_logged_in(page) and not need_job_cards and not page_is_linkedin_auth_wall(page):
        return True

    if page_is_linkedin_auth_wall(page) or need_job_cards:
        print("LinkedIn: in-session recovery...", file=sys.stderr)
        if _linkedin_auto_login_on_page(page, cfg):
            if need_job_cards and search_url:
                return warm_linkedin_for_jobs_search(page, search_url)
            return _page_looks_logged_in(page) and not page_is_linkedin_auth_wall(page)

        if need_job_cards and search_url and _page_looks_logged_in(page):
            return warm_linkedin_for_jobs_search(page, search_url)

    return page.locator('a[href*="/jobs/view/"]').count() > 0


def linkedin_auto_login(cfg: Dict[str, Any], *, headless: bool = True) -> bool:
    """Attempt automated login using stored credentials.

    Reads LINKEDIN_EMAIL and LINKEDIN_PASSWORD from env or .env.
    Returns True if login succeeded, False if 2FA or other block.
    """
    if not playwright_available():
        return False

    pw, context = _launch_persistent(cfg, headless=headless, service="linkedin")
    try:
        page = context.pages[0] if context.pages else context.new_page()
        return _linkedin_auto_login_on_page(page, cfg)
    finally:
        _safe_close(context, pw)


def ensure_linkedin_session(cfg: Dict[str, Any], *, headless: bool = True) -> bool:
    """Check session, try keepalive, then auto-login if needed.

    Returns True if LinkedIn is accessible after recovery attempts.
    """
    if linkedin_session_ready(cfg, headless=headless):
        return True
    print("LinkedIn session expired — attempting keepalive...", file=sys.stderr)
    if linkedin_keepalive(cfg, headless=headless):
        print("LinkedIn session restored via keepalive", file=sys.stderr)
        return True
    print("Keepalive failed — attempting auto-login...", file=sys.stderr)
    if linkedin_auto_login(cfg, headless=headless):
        return True
    _send_linkedin_alert(cfg)
    return False


def _send_linkedin_alert(cfg: Dict[str, Any]) -> None:
    """Send alert email to admin when LinkedIn login fails."""
    try:
        from job_agent.settings import get_setting
        admin_email = (
            os.environ.get("ORCHESTRATOR_ADMIN_EMAIL")
            or get_setting("EMAIL_TO", "GMAIL_RECIPIENT").strip()
        )
        if not admin_email:
            return
        email_user = get_setting("EMAIL_USER", "GMAIL_EMAIL").strip()
        email_pass = get_setting("EMAIL_PASS", "GMAIL_PASSWORD").strip()
        if not email_user or not email_pass:
            return
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"] = "Job Agent: LinkedIn login required"
        msg["From"] = email_user
        msg["To"] = admin_email
        msg.set_content(
            "LinkedIn session expired and auto-login failed.\n"
            "Manual re-login needed:\n\n"
            "  ssh -X azureuser@VM\n"
            "  cd ~/apps/devops-job-agent\n"
            "  python3 run.py --linkedin-login\n"
        )
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(email_user, email_pass)
            s.send_message(msg)
        print(f"LinkedIn alert sent to {admin_email}", file=sys.stderr)
    except Exception as exc:
        print(f"Failed to send LinkedIn alert: {exc}", file=sys.stderr)


def open_linkedin_login(cfg: Dict[str, Any], *, wait_minutes: int = 10) -> bool:
    """Open a visible browser; wait until login is detected or timeout. Returns True if logged in."""
    if not playwright_available():
        print(
            "Playwright is not installed.\n"
            "  pip install playwright\n"
            "  playwright install chromium",
            file=sys.stderr,
        )
        raise SystemExit(1)

    user_data = resolve_browser_user_data_dir(cfg, service="linkedin")
    print(f"LinkedIn browser profile: {user_data}")
    print("A Chromium window will open — log in to LinkedIn in that window.")
    print(f"Waiting up to {wait_minutes} min for login (or press Enter when done)…\n")

    pw, context = _launch_persistent(cfg, headless=False, service="linkedin")
    logged_in = False
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60_000)
        deadline = time.time() + max(1, wait_minutes) * 60
        while time.time() < deadline:
            if _page_looks_logged_in(page):
                logged_in = True
                print("Login detected — saving session…")
                break
            time.sleep(2)
        if not logged_in:
            print("Still waiting — press Enter after you finish logging in…")
            try:
                import select

                if select.select([sys.stdin], [], [], 0)[0]:
                    sys.stdin.readline()
                else:
                    input()
            except EOFError:
                pass
            page.goto(
                "https://www.linkedin.com/jobs/search/?location=Israel",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            time.sleep(2)
            logged_in = _page_looks_logged_in(page)
        if logged_in:
            print("Session saved. You can run: python3 run.py")
        else:
            print(
                "Could not confirm login. Try again: python3 run.py --linkedin-login",
                file=sys.stderr,
            )
    finally:
        _safe_close(context, pw)
    return logged_in


def _browser_lock_path(service: str) -> Path:
    lock_dir = Path(os.getenv("ORCHESTRATOR_DATA_DIR", str(Path.home() / "orchestrator-data")))
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / f".browser-{service}.lock"


@contextmanager
def _browser_lock(service: str) -> Generator[None, None, None]:
    """Cross-process file lock to serialize browser access for a given service."""
    lock_path = _browser_lock_path(service)
    lf = open(lock_path, "w")
    try:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lf.close()


@contextmanager
def with_linkedin_context(cfg: Dict[str, Any], *, headless: bool | None = None) -> Generator[Tuple, None, None]:
    """Context manager yielding (playwright, browser_context). Closes both on exit.
    Acquires a cross-process lock to prevent concurrent LinkedIn sessions."""
    block = cfg.get("browser") if isinstance(cfg.get("browser"), dict) else {}
    if headless is None:
        headless = bool(block.get("headless", True))
    with _browser_lock("linkedin"):
        pw, context = _launch_persistent(cfg, headless=headless, service="linkedin")
        try:
            yield pw, context
        finally:
            _safe_close(context, pw)


def _page_looks_google_ok(page) -> bool:
    url = (page.url or "").lower()
    if "sorry" in url and "google" in url:
        return False
    if _page_has_google_captcha_text(page):
        return False
    return "google." in url


def _page_has_google_captcha_text(page) -> bool:
    try:
        body = (page.locator("body").inner_text(timeout=4000) or "").lower()
    except Exception:
        return False
    return "unusual traffic" in body or "not a robot" in body


def open_google_login(cfg: Dict[str, Any], *, wait_minutes: int = 10) -> bool:
    """Open visible Google in the google browser profile; confirm search works."""
    if not playwright_available():
        print(
            "Playwright is not installed.\n"
            "  pip install playwright\n"
            "  playwright install chromium",
            file=sys.stderr,
        )
        raise SystemExit(1)

    user_data = resolve_browser_user_data_dir(cfg, service="google")
    print(f"Google browser profile: {user_data}")
    print("Log in to Google if prompted (account helps avoid CAPTCHAs).")
    print(f"Waiting up to {wait_minutes} min…\n")

    pw, context = _launch_persistent(cfg, headless=False, service="google")
    ok = False
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.google.co.il", wait_until="domcontentloaded", timeout=60_000)
        deadline = time.time() + max(1, wait_minutes) * 60
        while time.time() < deadline:
            if _page_looks_google_ok(page) and not _page_has_google_captcha_text(page):
                ok = True
                break
            time.sleep(2)
        if not ok:
            print("Press Enter after you can use Google search normally…")
            try:
                input()
            except EOFError:
                pass
            page.goto(
                "https://www.google.co.il/search?q=devops+manager+israel",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            time.sleep(2)
            ok = _page_looks_google_ok(page) and not _page_has_google_captcha_text(page)
        if ok:
            print("Google session saved. Run: python3 run.py")
        else:
            print("Could not confirm Google — try: python3 run.py --google-login", file=sys.stderr)
    finally:
        _safe_close(context, pw)
    return ok


@contextmanager
def with_google_context(cfg: Dict[str, Any], *, headless: bool | None = None) -> Generator[Tuple, None, None]:
    """Context manager yielding (playwright, browser_context) for Google Web.
    Acquires a cross-process lock to prevent concurrent Google sessions."""
    block = cfg.get("browser") if isinstance(cfg.get("browser"), dict) else {}
    gblock = cfg.get("google_web_browser") if isinstance(cfg.get("google_web_browser"), dict) else {}
    if headless is None:
        headless = bool(gblock.get("headless", block.get("headless", True)))
    with _browser_lock("google"):
        pw, context = _launch_persistent(cfg, headless=headless, service="google")
        try:
            yield pw, context
        finally:
            _safe_close(context, pw)
