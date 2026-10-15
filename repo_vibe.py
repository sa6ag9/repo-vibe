"""Repo-Vibe core: fetch real repo stats via the GitHub REST API and render
an animated CRT-terminal SVG badge.

Stdlib only. Honest by design: every number on the badge comes from a live
API response (or a captured API response in --data-file mode). Mood is a
transparent lexicon read of the last 3 commit messages, not a black box.
"""
import json, os, re, urllib.request, urllib.error
from datetime import datetime, timezone

API = "https://api.github.com"

POS = {"add","fix","ship","verified","pass","complete","advance","launch","win",
       "fast","clean","ready","publish","release","improve","success"}
NEG = {"fail","error","bug","broken","revert","hotfix","wip","blocked","crash",
       "wrong","miss","drop","stuck"}

def _get(path, token=None):
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "repo-vibe",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def mood_for(messages):
    """Transparent sentiment: count lexicon hits across the last 3 messages."""
    text = " ".join(messages[:3]).lower()
    words = set(re.findall(r"[a-z]+", text))
    pos, neg = len(words & POS), len(words & NEG)
    if pos > neg: return "LOCKED IN", "#39ff88"
    if neg > pos: return "DEBUGGING", "#ffb347"
    if messages: return "GRINDING", "#4dc3ff"
    return "IDLE", "#888888"

def next_milestone(stars):
    for m in (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000):
        if stars < m:
            return m
    return ((stars // 10000) + 1) * 10000

def fetch_stats(owner, repo, token=None):
    """Live stats: stars, lines changed today (UTC), latest build, last messages."""
    info = _get(f"/repos/{owner}/{repo}", token)
    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    commits = _get(f"/repos/{owner}/{repo}/commits?per_page=30&since={since}", token) or []
    lines = 0
    for c in commits:
        try:
            full = _get(f"/repos/{owner}/{repo}/commits/{c['sha']}", token)
            lines += int(full.get("stats", {}).get("total", 0))
        except Exception:
            pass
    messages = [c["commit"]["message"].splitlines()[0] for c in commits[:3]]
    build = "NO CI RUNS"
    try:
        runs = _get(f"/repos/{owner}/{repo}/actions/runs?per_page=1", token)
        wr = (runs.get("workflow_runs") or [])
        if wr:
            build = (wr[0].get("conclusion") or wr[0].get("status") or "unknown").upper()
    except Exception:
        pass
    return {
        "owner": owner, "repo": repo,
        "stars": int(info.get("stargazers_count", 0)),
        "lines_today": lines,
        "commits_today": len(commits),
        "build": build,
        "messages": messages,
    }

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

def render_svg(stats, theme="neon-dark"):
    stars = stats["stars"]; goal = next_milestone(stars)
    pct = max(2, min(100, round(100 * stars / goal))) if goal else 2
    mood, mood_color = mood_for(stats.get("messages", []))
    build = stats.get("build", "UNKNOWN")
    build_color = "#39ff88" if build == "SUCCESS" else "#ffb347" if build in ("NO CI RUNS", "UNKNOWN") else "#ff5470"
    bar_w = round(3.6 * pct)  # 360px bar
    title = esc(f"{stats['owner']}/{stats['repo']}")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="480" height="200" viewBox="0 0 480 200" role="img" aria-label="Repo-Vibe for {title}">
  <defs>
    <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
      <rect width="4" height="2" fill="#000" fill-opacity="0.18"/>
    </pattern>
    <linearGradient id="glow" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#39ff88"/><stop offset="100%" stop-color="#4dc3ff"/>
    </linearGradient>
  </defs>
  <rect width="480" height="200" rx="10" fill="#0a0f0a"/>
  <rect width="480" height="200" rx="10" fill="url(#scan)"/>
  <text x="20" y="30" font-family="monospace" font-size="15" fill="#39ff88">&#9654; {title}</text>
  <text x="20" y="58" font-family="monospace" font-size="13" fill="#c8ffd8">LINES CHANGED TODAY : {stats["lines_today"]}  ({stats["commits_today"]} commits)</text>
  <text x="20" y="80" font-family="monospace" font-size="13" fill="{build_color}">BUILD STATUS        : {esc(build)}</text>
  <text x="20" y="102" font-family="monospace" font-size="13" fill="{mood_color}">LAST CONTRIBUTOR MOOD: {mood}</text>
  <text x="20" y="132" font-family="monospace" font-size="13" fill="#ffe74d">&#9733; STAR METER  {stars} / {goal}</text>
  <rect x="20" y="142" width="360" height="12" rx="6" fill="#1c2a1c"/>
  <rect x="20" y="142" width="{bar_w}" height="12" rx="6" fill="url(#glow)">
    <animate attributeName="width" from="0" to="{bar_w}" dur="1.2s" fill="freeze"/>
  </rect>
  <text x="20" y="182" font-family="monospace" font-size="11" fill="#6f8f6f">Powered by Repo-Vibe \u00b7 github.com/sa6ag9/repo-vibe</text>
  <rect x="392" y="168" width="10" height="16" fill="#39ff88">
    <animate attributeName="opacity" values="1;0;1" dur="1.1s" repeatCount="indefinite"/>
  </rect>
</svg>'''

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--owner"); p.add_argument("--repo")
    p.add_argument("--data-file", help="render from a captured stats JSON instead of the live API")
    p.add_argument("--out", default="badge.svg")
    a = p.parse_args()
    if a.data_file:
        stats = json.load(open(a.data_file))
    else:
        stats = fetch_stats(a.owner, a.repo, os.environ.get("GITHUB_TOKEN"))
    open(a.out, "w").write(render_svg(stats))
    print(f"wrote {a.out}: {stats}")
