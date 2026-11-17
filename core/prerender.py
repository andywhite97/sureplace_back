"""Notify GitHub Pages to refresh its build-time prerendered public HTML.

GitHub Pages is static. Django remains the source of truth; this event only
starts a frontend build that regenerates listing HTML, social tags and sitemap.
No GitHub credential is ever sent to browser clients.
"""
import json
import logging
import re
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def request_prerender_refresh():
    """Schedule a best-effort refresh only after the enclosing DB transaction commits."""
    if not settings.PRERENDER_GITHUB_TOKEN:
        return
    transaction.on_commit(_dispatch_prerender_refresh, robust=True)


def _dispatch_prerender_refresh():
    token = settings.PRERENDER_GITHUB_TOKEN
    repository = settings.PRERENDER_GITHUB_REPOSITORY
    if not token:
        return False
    # The destination host is fixed and the repository path is validated.
    if not _REPOSITORY.fullmatch(repository):
        logger.error("Prerender refresh skipped: invalid configured GitHub repository.")
        return False

    key = f"sureplace:prerender-dispatch:{repository}"
    try:
        if not cache.add(key, "1", timeout=max(1, settings.PRERENDER_DISPATCH_COOLDOWN_SECONDS)):
            return False
    except Exception:
        logger.warning("Prerender refresh skipped: shared cache unavailable.")
        return False

    request = Request(
        f"https://api.github.com/repos/{repository}/dispatches",
        data=json.dumps({"event_type": "content-published"}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "SurePlace-prerender-refresh",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=max(1, settings.PRERENDER_DISPATCH_TIMEOUT_SECONDS)) as response:
            if response.status != 204:
                raise ValueError("Unexpected GitHub dispatch response")
        logger.info("Prerender refresh requested for configured frontend repository.")
        return True
    except Exception as error:
        # Do not log exception text: an HTTP client may include auth headers.
        logger.warning("Prerender refresh request failed (%s).", type(error).__name__)
        try:
            cache.delete(key)  # allow another content update to retry promptly
        except Exception:
            logger.warning("Prerender refresh throttle could not be cleared.")
        return False
