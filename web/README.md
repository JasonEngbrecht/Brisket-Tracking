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
handle the rest:

- `requirements.txt` → `flask`, `pandas`, `numpy`, `gunicorn`
- `Procfile` → `web: gunicorn --chdir web app:app`
- Railway injects `$PORT`; gunicorn binds it automatically.

Point Railway at the GitHub repo, deploy, and open the generated URL on your
phone (optionally "Add to Home Screen").

## Scope

Just the core: paste/upload one CHEF iQ CSV → % done, texture, dual-axis chart.
Multi-file stitching, saved cooks, and notes stay in the desktop app for now.
