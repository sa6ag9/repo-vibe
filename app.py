"""Repo-Vibe GitHub App server (stdlib HTTP + `cryptography` for App JWT).

Endpoints
  GET  /                        health + install pitch
  GET  /badge/<owner>/<repo>   live animated SVG (uses an installation token
                                when the App is installed on that account,
                                otherwise falls back to unauthenticated public API)
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
import base64, hashlib, hmac, json, os, time, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import repo_vibe

APP_NAME = os.environ.get("REPO_VIBE_APP_NAME", "Repo-Vibe")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8080")
_cache = {}          # (owner, repo) -> svg string
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
                            f"App server is live.</p><p><a href='/setup'>Create the GitHub App (manifest flow)</a></p>")
        elif u.path == "/manifest":
            self._send(200, json.dumps(manifest(), indent=2), "application/json")
        elif u.path == "/setup":
            m = json.dumps(manifest()).replace('"', "&quot;")
            self._send(200, f"""<h1>Create Repo-Vibe on GitHub</h1>
<p>Clicking this posts the manifest to GitHub. GitHub shows you the App name and
permissions and asks <b>you</b> to confirm - that human click is required by GitHub.</p>
<form action="https://github.com/settings/apps/new" method="post">
  <input type="hidden" name="manifest" value="{m}">
  <input type="submit" value="Create Repo-Vibe GitHub App">
</form>""")
        elif u.path == "/setup/callback":
            code = (q.get("code") or [""])[0]
            if not code:
                return self._send(400, "missing ?code=")
            try:
                conv = api(f"/app-manifests/{code}/conversions", method="POST")
            except Exception as e:
                return self._send(502, f"conversion failed: {e}")
            # Never print the private key / webhook secret into logs or chat.
            safe = {k: conv.get(k) for k in ("id", "slug", "name", "html_url", "owner")}
            self._send(200, f"<h1>App created</h1><pre>{json.dumps(safe, indent=2)}</pre>"
                            "<p>GitHub returned the App id, slug, webhook secret, client "
                            "credentials and PEM private key in this one-time conversion. "
                            "Save them into your secret store NOW (the PEM is shown once), "
                            "then set GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH and "
                            "WEBHOOK_SECRET for this server and restart it.</p>")
        elif u.path.startswith("/badge/"):
            parts = u.path.strip("/").split("/")
            if len(parts) != 3:
                return self._send(400, "use /badge/<owner>/<repo>", "text/plain")
            _, owner, repo = parts
            key = (owner, repo)
            if key not in _cache:
                stats = repo_vibe.fetch_stats(owner, repo, token_for(owner))
                _cache[key] = repo_vibe.render_svg(stats)
            self._send(200, _cache[key], "image/svg+xml")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if u.path != "/webhook":
            return self._send(404, "not found", "text/plain")
        secret = os.environ.get("WEBHOOK_SECRET", "")
        sig = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(sig, expected):
            return self._send(401, "bad signature", "text/plain")
        event = self.headers.get("X-GitHub-Event", "")
        payload = json.loads(body or b"{}")
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
