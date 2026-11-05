"""Repo-Vibe GitHub App server (stdlib HTTP + `cryptography` for App JWT).

Endpoints
  GET  /                        health + install pitch
  GET  /badge/<owner>/<repo>   live animated SVG using public GitHub data only
  POST /webhook                 GitHub App webhooks (HMAC-SHA256 verified);
                                push events refresh the badge cache
  GET  /manifest                the GitHub App manifest JSON
  GET  /setup                   one-click manifest-flow page: posts the manifest
                                to github.com/settings/apps/new in YOUR browser,
                                where you confirm creation (GitHub requires a
                                human click there - no API bypass exists)
  GET  /setup/callback?code=    exchanges the manifest code for the new App's
                                credentials and tells you exactly what to save

Config (environment, never committed):
  GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, WEBHOOK_SECRET, PORT (default 8080)
"""
import base64, hashlib, hmac, json, os, re, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import repo_vibe

APP_NAME = os.environ.get("REPO_VIBE_APP_NAME", "Repo-Vibe")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8080")
_cache = {}          # (owner, repo) -> (monotonic expiry, UTC day, svg)
CACHE_TTL_SECONDS = 300
MAX_CACHE_ENTRIES = 256
MAX_WEBHOOK_BYTES = 1024 * 1024
_installations = {}  # account_login -> installation_id (learned from webhooks)

# ---------- GitHub App auth ----------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def make_jwt():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_private_key(
        open(os.environ["GITHUB_APP_PRIVATE_KEY_PATH"], "rb").read(), password=None)
    now = int(time.time())
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"iat": now - 60, "exp": now + 540,
                               "iss": os.environ["GITHUB_APP_ID"]}).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64(sig)}"

def api(path, token=None, method="GET", data=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "repo-vibe-app"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def installation_token(installation_id):
    return api(f"/app/installations/{installation_id}/access_tokens",
               token=make_jwt(), method="POST", data={})["token"]

def token_for(owner):
    if owner in _installations and os.environ.get("GITHUB_APP_ID"):
        try:
            return installation_token(_installations[owner])
        except Exception:
            pass
    return os.environ.get("GITHUB_TOKEN")  # fallback (public repos work with none)

# ---------- Manifest (GitHub App manifest flow) ----------
def manifest():
    return {
        "name": APP_NAME,
        "url": "https://github.com/sa6ag9/repo-vibe",
        "hook_attributes": {"url": f"{PUBLIC_URL}/webhook"},
        "redirect_url": f"{PUBLIC_URL}/setup/callback",
        "public": True,
        "default_permissions": {
            "contents": "read", "actions": "read",
            "metadata": "read", "pull_requests": "read",
        },
        "default_events": ["push", "installation", "installation_repositories"],
    }

# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/":
            self._send(200, f"<h1>Repo-Vibe</h1><p>The vibe for your repo. "
                            f"App server is live.</p><p>Public repository badges. Optional signed push webhook.</p>")
        elif u.path in ("/manifest", "/setup", "/setup/callback"):
            self._send(410, "Automatic GitHub App setup is unavailable. "
                       "Public badges use public repository data only. "
                       "Configure an optional signed repository webhook manually.", "text/plain")
        elif u.path.startswith("/status/"):
            parts = u.path.strip("/").split("/")
            if len(parts) != 3:
                return self._send(400, "use /status/<owner>/<repo>", "text/plain")
            _, owner, repo = parts
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repo) or repo in (".", ".."):
                return self._send(400, "invalid repository name", "text/plain")
            # Machine-readable, public-only observability. No installation
            # token or privileged cache can ever influence this endpoint.
            try:
                info = api(f"/repos/{owner}/{repo}")
                if info.get("private") is not False:
                    return self._send(404, "repository not found", "text/plain")
                stats = repo_vibe.fetch_stats(owner, repo, None)
                # Only JSON-compatible primitive fields; never expose API
                # credentials or upstream response bodies.
                if not isinstance(stats, dict):
                    return self._send(503, "stats unavailable", "text/plain")
                allowed = {"stars", "build", "lines_today", "commits_today", "activity_status"}
                result = {k: v for k, v in stats.items()
                          if k in allowed and (v is None or type(v) in (str,int,float,bool))}
                result["mood"] = repo_vibe.mood_for(stats.get("messages", []))[0]
                result["schema"] = "repo-vibe.public-status.v1"
                result["repository"] = owner + "/" + repo
                return self._send(200, json.dumps(result, sort_keys=True, allow_nan=False), "application/json")
            except urllib.error.HTTPError as exc:
                return self._send(404 if exc.code == 404 else 503, "repository unavailable", "text/plain")
            except Exception:
                return self._send(503, "repository unavailable", "text/plain")
        elif u.path.startswith("/badge/"):
            parts = u.path.strip("/").split("/")
            if len(parts) != 3:
                return self._send(400, "use /badge/<owner>/<repo>", "text/plain")
            _, owner, repo = parts
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repo) or repo in (".", ".."):
                return self._send(400, "invalid repository name", "text/plain")
            key = (owner, repo)
            # This endpoint is public: neither a privileged installation token
            # nor previously cached data may disclose a private repository.
            try:
                info = api(f"/repos/{owner}/{repo}")
                if info.get("private") is not False:
                    _cache.pop(key, None)
                    return self._send(404, "repository not found", "text/plain")
                now = time.monotonic()
                day = time.strftime("%Y-%m-%d", time.gmtime())
                cached = _cache.get(key)
                if cached is None or cached[0] <= now or cached[1] != day:
                    _cache.pop(key, None)
                    stats = repo_vibe.fetch_stats(owner, repo, None)
                    if len(_cache) >= MAX_CACHE_ENTRIES:
                        _cache.pop(next(iter(_cache)))
                    _cache[key] = (now + CACHE_TTL_SECONDS, day, repo_vibe.render_svg(stats))
            except urllib.error.HTTPError as exc:
                _cache.pop(key, None)
                status = 404 if exc.code == 404 else 503
                return self._send(status, "repository unavailable", "text/plain")
            except Exception:
                _cache.pop(key, None)
                return self._send(503, "repository unavailable", "text/plain")
            self._send(200, _cache[key][2], "image/svg+xml")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/webhook":
            return self._send(404, "not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except (TypeError, ValueError):
            return self._send(400, "invalid content length", "text/plain")
        if length < 0:
            return self._send(400, "invalid content length", "text/plain")
        if length > MAX_WEBHOOK_BYTES:
            return self._send(413, "payload too large", "text/plain")
        if self.headers.get("Transfer-Encoding"):
            return self._send(400, "unsupported transfer encoding", "text/plain")
        body = self.rfile.read(length)
        secret = os.environ.get("WEBHOOK_SECRET", "")
        sig = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(sig, expected):
            return self._send(401, "bad signature", "text/plain")
        event = self.headers.get("X-GitHub-Event", "")
        try:
            payload = json.loads(body or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("object required")
            for field in ("installation", "repository"):
                if field in payload and not isinstance(payload[field], dict):
                    raise ValueError("invalid event")
        except (ValueError, UnicodeError):
            return self._send(400, "invalid event", "text/plain")
        if event in ("installation", "installation_repositories"):
            inst = payload.get("installation", {})
            acct = (inst.get("account") or {}).get("login")
            if acct and inst.get("id"):
                _installations[acct] = inst["id"]
        if event == "push":
            repo = payload.get("repository", {})
            owner = (repo.get("owner") or {}).get("login") or (repo.get("full_name", "/").split("/")[0])
            name = repo.get("name")
            if owner and name:
                _cache.pop((owner, name), None)  # force fresh stats on next badge hit
        self._send(202, "ok", "text/plain")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"Repo-Vibe App server on :{port}  public={PUBLIC_URL}")
    HTTPServer(("0.0.0.0", port), H).serve_forever()
