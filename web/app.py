"""Brisket Tracker - phone web version.

A scaled-back web front end for the desktop tenderness tracker. It reuses the
exact model and CSV parser from ``brisket_tenderness.py`` (the desktop file's
matplotlib/tkinter imports are lazy, so importing it here never pulls in any
GUI dependency).

Workflow: paste the CHEF iQ "Copy" text (or upload the CSV) on your phone,
POST it to /analyze, get back the doneness summary + chart series as JSON.

Run locally:
    py -3 web/app.py        # then open http://localhost:5000

Deploy (Railway): the root Procfile runs gunicorn against this module.
"""

from __future__ import annotations

import io
import os
import sys

from flask import Flask, jsonify, render_template, request

# Make the desktop module importable no matter what the working directory is
# (gunicorn --chdir web changes cwd, local `py -3 web/app.py` does not).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import brisket_tenderness as bt  # noqa: E402  (path set up above)

app = Flask(__name__)

# Cap how many points we ship to the phone's chart. The doneness number is
# always computed on the full data; only the drawn series is thinned.
MAX_CHART_POINTS = 800


def _thin(seq, n=MAX_CHART_POINTS):
    """Stride a list down to at most n points, always keeping the last sample."""
    if len(seq) <= n:
        return list(seq)
    step = (len(seq) + n - 1) // n
    out = list(seq[::step])
    if out and out[-1] != seq[-1]:
        out.append(seq[-1])
    return out


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    """Parse pasted text or an uploaded CSV and return doneness + chart series."""
    text = (request.form.get("csv_text") or "").strip()
    if not text and "csv_file" in request.files:
        upload = request.files["csv_file"]
        if upload and upload.filename:
            raw = upload.read()
            text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw

    if not text:
        return jsonify(ok=False, error="Paste the CHEF iQ data or choose a CSV file first."), 400

    try:
        df = bt.load_cook_data(io.StringIO(text), source="pasted data")
        result = bt.compute_doneness(df)
    except Exception as exc:  # surface parse/model errors to the user as-is
        return jsonify(ok=False, error=str(exc)), 400

    rdf = result.df
    elapsed_h = rdf["elapsed_h"].astype(float).tolist()
    temp = rdf["internal_temp_f"].astype(float).tolist()
    cum = rdf["cum_percent"].astype(float).tolist()

    return jsonify(
        ok=True,
        total_percent=round(result.total_percent, 1),
        texture=result.texture,
        total_hours=result.total_hours,
        duration=bt.format_duration(result.total_hours),
        peak_internal_f=round(float(rdf["internal_temp_f"].max()), 1),
        n_samples=int(len(rdf)),
        series={
            "elapsed_h": _thin(elapsed_h),
            "internal_temp_f": _thin(temp),
            "cum_percent": _thin(cum),
        },
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
