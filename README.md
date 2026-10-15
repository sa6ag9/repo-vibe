# Repo-Vibe

### The vibe for your repo.

Your README is a billboard that never changes. **Repo-Vibe turns it into a live terminal.**

One line of markdown, and your profile shows a retro CRT status terminal fed by
*real* data from the GitHub REST API — not a static image, not a fake counter:

![Repo-Vibe Dashboard](https://repo-vibe.example.com/badge/YOUR-OWNER/YOUR-REPO)

- **Lines of Code Changed Today** — summed from today's actual commits
- **Current Build Status** — your latest GitHub Actions run, success or fail
- **Last Contributor Mood** — a transparent lexicon read of your last 3 commit
  messages (`LOCKED IN`, `GRINDING`, `DEBUGGING`…). No black box; the word
  lists are in the code, read them yourself
- **The Star Meter** — a bar that fills toward your next star milestone.
  Watching it grow is the whole point. Vanity, as a service.

Every number is fetched live or it doesn't ship. That's the house rule.

## Use it

Add this to any `README.md`:

```markdown
![Repo-Vibe Dashboard](https://YOUR-DEPLOYMENT/badge/OWNER/REPO)
```

Public repos work with zero setup. For private repos and push-fresh badges,
install **Repo-Vibe as a GitHub App** (read-only: contents, actions, metadata,
pull requests — it cannot write to your code).

## Run your own (it's open source)

```bash
python3 app.py            # stdlib only, plus `cryptography` for App JWT auth
# GET  /                       health
# GET  /badge/<owner>/<repo>   the SVG
# POST /webhook                push events refresh the badge (HMAC verified)
# GET  /setup                  one-click GitHub App creation (manifest flow)
```

### Create the GitHub App (manifest flow)

GitHub does **not** let an API create a GitHub App unattended — a human has to
confirm it in the browser. Repo-Vibe makes that a one-click formality:

1. Deploy/run this server with a public `PUBLIC_URL`.
2. Open `/setup`, click **Create Repo-Vibe GitHub App**. GitHub shows the name
   and read-only permissions; confirm.
3. GitHub redirects to `/setup/callback`; the server exchanges the one-time
   code and tells you exactly what to save.
4. Save the App ID, PEM private key and webhook secret into your secret store,
   set `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `WEBHOOK_SECRET`,
   restart. Done — installs now feed the badge via installation tokens.

Offline / receipt mode (render from a captured API response):

```bash
python3 repo_vibe.py --data-file demo-stats.json --out demo-badge.svg
python3 test_repo_vibe.py   # all tests
```

## Verified demo in this repo

`demo-badge.svg` was rendered from **live** Savage Forge data on 2026-10-14:
build `SUCCESS`, last-3-commit mood `LOCKED IN`, and 347,278 lines changed
across the first 30 commits of the day (v1 fetches up to 30 commits/day —
that cap is stated here, not hidden).

## Roadmap (same family, later)

- **Ghost-Writer AI** — a GitHub App bot that drafts doc updates on PRs that
  change a function signature without touching the docs.
- **Chrono-Repo** — `/chronos <date>` on an issue/PR opens an ephemeral,
  read-only snapshot of the repo as it existed that day.

## License

MIT. If Repo-Vibe makes your repo look alive, the footer links back here —
star it and the meter moves for both of us.
