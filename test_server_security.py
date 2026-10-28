from unittest.mock import patch
from urllib.error import HTTPError
import app


def request(owner="example", repo="project"):
    handler = object.__new__(app.H)
    handler.path = f"/badge/{owner}/{repo}"
    result = []
    handler._send = lambda status, body, ctype=None: result.append((status, body))
    handler.do_GET()
    return result[0]


def setup_function():
    app._cache.clear()


def test_public_badge_uses_only_public_data():
    with patch.object(app, "api", return_value={"private": False}), \
         patch.object(app, "token_for", return_value="synthetic-privileged-token"), \
         patch.object(app.repo_vibe, "fetch_stats", return_value={"public": True}) as fetch, \
         patch.object(app.repo_vibe, "render_svg", return_value="<svg/>"):
        assert request() == (200, "<svg/>")
        fetch.assert_called_once_with("example", "project", None)


def test_inaccessible_repository_never_returns_cached_badge():
    app._cache[("example", "project")] = "<svg>synthetic-private-data</svg>"
    denied = HTTPError("https://example.invalid", 404, "not found", {}, None)
    with patch.object(app, "api", side_effect=denied), \
         patch.object(app.repo_vibe, "fetch_stats") as fetch:
        status, body = request()
        assert status == 404
        assert "synthetic-private-data" not in body
        assert ("example", "project") not in app._cache
        fetch.assert_not_called()


def test_visibility_is_checked_on_every_cached_request():
    with patch.object(app, "api", side_effect=[{"private": False}, {"private": True}]), \
         patch.object(app.repo_vibe, "fetch_stats", return_value={"public": True}), \
         patch.object(app.repo_vibe, "render_svg", return_value="<svg/>"):
        assert request()[0] == 200
        assert request()[0] == 404
