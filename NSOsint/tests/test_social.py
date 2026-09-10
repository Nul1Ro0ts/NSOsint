# --- tests/test_social.py ---
from unittest.mock import AsyncMock, patch

import pytest

from nsoint import make_session
from nsoint.core import Result
from nsoint.modules.social import _is_hit, scan_username


def test_is_hit_rejects_404():
    assert _is_hit("github", 404, "whatever") is False


def test_is_hit_rejects_github_not_found():
    assert _is_hit("github", 200, "Not Found — this page does not exist") is False


def test_is_hit_rejects_captcha_page():
    assert _is_hit("github", 200, "Please complete the CAPTCHA to continue") is False


def test_is_hit_rejects_cloudflare():
    assert _is_hit("github", 200, "Just a moment... checking your browser") is False


def test_is_hit_accepts_clean_200():
    assert _is_hit("github", 200, "<html>profile page</html>") is True


@pytest.mark.asyncio
async def test_scan_username_returns_result():
    async with make_session() as s:
        with patch(
            "nsoint.modules.social.safe_fetch",
            new=AsyncMock(return_value=(404, "")),
        ):
            r = await scan_username(s, "definitelynotarealuser9999")
            assert isinstance(r, Result)
            assert r.module == "social.username"
            assert r.found is False
            assert r.degraded == []


@pytest.mark.asyncio
async def test_scan_username_records_degraded_on_429():
    async with make_session() as s:
        with patch(
            "nsoint.modules.social.safe_fetch",
            new=AsyncMock(return_value=(429, "rate limited")),
        ):
            r = await scan_username(s, "someone")
            assert r.found is False
            assert any(d.get("detail") == "429" for d in r.degraded)
