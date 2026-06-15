# Brisket Tracker — phone web version

A scaled-back web front end for the desktop tracker. It reuses the model and
CSV parser from `../brisket_tenderness.py` unchanged — paste the CHEF iQ "Copy"
text (or upload the CSV) and it returns the doneness %, texture, and a chart.

## Run locally

```
py -3 -m pip install -r ..\requirements.txt   # first time only
py -3 web\app.py
```

Then open <http://localhost:5000>. (On your phone, browse to
`http://<your-PC-IP>:5000` while on the same Wi-Fi.)

## Deploy to Railway

The app lives in `web/`, but it imports `brisket_tenderness.py` from the repo
root — so the **whole repo** must be the deploy context (do *not* set Railway's
root directory to `web/`). The repo-root `Procfile` and `requirements.txt`
drive the build:

- `requirements.txt` → `flask`, `pandas`, `numpy`, `gunicorn`
- `Procfile` → `web: gunicorn --chdir web app:app --bind 0.0.0.0:$PORT`
- Railway injects `$PORT`; the `--bind` above makes gunicorn listen on it
  (without it gunicorn defaults to `:8000` and the public URL returns 502).

### How this project is actually deployed: the Railway CLI

We use the **CLI**, not GitHub auto-deploy. Reason: the repo is owned by the
`JasonEngbrecht` GitHub account, but Railway was logged in under a different
GitHub account (`falconrobotics9` / workspace `frcfalcon5434`), and Railway
ties one Railway login to one GitHub identity — so it couldn't see this repo.
`railway up` uploads the local folder directly and sidesteps GitHub entirely.

First-time setup (in PowerShell, from the project root):

```powershell
npm i -g @railway/cli      # needs Node/npm installed
railway login              # opens browser; signs in to Railway
railway init               # creates the project (named "brisket-tracker")
railway up                 # builds + deploys; Ctrl+C after "Deploy complete"
railway domain             # generates the public URL
```

**To redeploy after changing code** (this is the "publish" button — a `git
push` does NOT deploy on the CLI path):

```powershell
railway up                 # then Ctrl+C once you see "Deploy complete"
```

`railway up` streams build/deploy logs, then sits on the running container's
log stream — it looks frozen but the deploy is already done; Ctrl+C just
detaches the log view, it does not stop the app.

- Railway project: `brisket-tracker` on workspace `frcfalcon5434's Projects`
  (https://railway.com/project/feed6b7a-5de7-437c-b3d7-8159a8f70e06)

### Alternative: GitHub auto-deploy

If you ever sign Railway in as `JasonEngbrecht`, you can instead connect the
GitHub repo (New Project → Deploy from GitHub repo → `Brisket-Tracking`) and
every push to `main` auto-deploys. Same `Procfile`/`requirements.txt` apply.

## Scope

Just the core: paste/upload one CHEF iQ CSV → % done, texture, dual-axis chart.
Multi-file stitching, saved cooks, and notes stay in the desktop app for now.
