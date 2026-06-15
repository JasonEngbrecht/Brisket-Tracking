"""Brisket tenderness / doneness tracker.

Implements the Smoke Trails BBQ "tenderness model"
(https://smoketrailsbbq.com/brisket-holding-masterclass-and-tenderness-model/).

The model treats brisket doneness as cumulative collagen->gelatin rendering.
Each internal-meat temperature renders collagen at a rate measured in
"% per hour".  Total doneness is the time-integral of that rate across the
whole cook (and the hold):

        percent_done(t) = integral_0..t  rate( internal_temp(s) )  ds

where ~100% corresponds to ideal tenderness.

Design choices (per project requirements):
  * Rate interpolation between table points is LOG-LINEAR (the model is
    Arrhenius / exponential in temperature, so we interpolate linearly in
    ln(rate) vs temperature).
  * Out-of-range temps are CLAMPED: below 140 F renders at 0 %/hr, at/above
    210 F is capped at 75 %/hr.
  * Unequal time spacing / gaps are handled by TRAPEZOIDAL integration over
    the actual elapsed time of every interval (gaps included).

Run as a desktop GUI:
    py -3 brisket_tenderness.py [optional_data.csv]

Or headless (prints a summary, no window):
    py -3 brisket_tenderness.py data.csv --no-gui
"""

from __future__ import annotations

import io
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

# Saved-cook file format constants.
COOK_FILE_FORMAT = "brisket_cook"
COOK_FILE_VERSION = 1
COOK_FILE_EXT = ".brisketcook"

# --------------------------------------------------------------------------
# The model: rendering-rate table (internal temp in deg F -> % rendered/hour)
# --------------------------------------------------------------------------
RATE_TABLE_TEMPS = np.array(
    [140, 150, 160, 170, 180, 190, 195, 200, 205, 210], dtype=float
)
RATE_TABLE_RATES = np.array(
    [1, 2, 3, 5, 9, 18, 25, 35, 55, 75], dtype=float
)
_LN_RATES = np.log(RATE_TABLE_RATES)

# Temperature below which we treat rendering as negligible (clamp to 0).
LOW_TEMP_CUTOFF = RATE_TABLE_TEMPS[0]   # 140 F
HIGH_TEMP_CAP = RATE_TABLE_TEMPS[-1]    # 210 F  (rate capped at 75 %/hr)
MAX_RATE = RATE_TABLE_RATES[-1]         # 75 %/hr

# Doneness interpretation bands (percent -> texture description).
TEXTURE_BANDS = [
    (80.0, "Underdone - tight, needs more time"),
    (95.0, "Slightly tight but sliceable"),
    (105.0, "Ideal tenderness"),
    (120.0, "Very soft, possibly over"),
    (float("inf"), "Over-rendered - mushy risk"),
]


def rendering_rate(temp_f):
    """Collagen rendering rate (% per hour) for internal temperature(s).

    Log-linear interpolation between table points; clamped at both ends:
    below 140 F -> 0 %/hr, at/above 210 F -> 75 %/hr.

    Accepts a scalar or array-like; returns the matching type.
    """
    temp = np.asarray(temp_f, dtype=float)
    # np.interp clamps to the endpoint values outside the table range, so for
    # T >= 210 it already returns ln(75); we only need to zero out the low end.
    rate = np.exp(np.interp(temp, RATE_TABLE_TEMPS, _LN_RATES))
    rate = np.where(temp < LOW_TEMP_CUTOFF, 0.0, rate)
    if np.isscalar(temp_f) or np.asarray(temp_f).ndim == 0:
        return float(rate)
    return rate


def texture_for(percent):
    """Return the texture description for a given percent-done value."""
    for threshold, label in TEXTURE_BANDS:
        if percent < threshold:
            return label
    return TEXTURE_BANDS[-1][1]


# --------------------------------------------------------------------------
# CSV parsing (CHEF iQ probe export format)
# --------------------------------------------------------------------------
DATA_HEADER_MARKER = "Date,Time,"


def _find_internal_temp_column(columns):
    for col in columns:
        if "internal temperature" in col.lower():
            return col
    raise ValueError(
        "Could not find an 'Internal Temperature' column in the CSV. "
        f"Found columns: {list(columns)}"
    )


def _read_text(path_or_buffer):
    if hasattr(path_or_buffer, "read"):
        text = path_or_buffer.read()
        if isinstance(text, bytes):
            text = text.decode("utf-8-sig", errors="replace")
        return text
    with open(path_or_buffer, "r", encoding="utf-8-sig", errors="replace") as fh:
        return fh.read()


# CHEF iQ exports timestamps as e.g. "05/31/2026 10:56:25 AM".
CHEF_DATETIME_FORMAT = "%m/%d/%Y %I:%M:%S %p"


def _to_datetime(values):
    """Parse CHEF iQ date/time values, using the known format for speed.

    Tries the fixed CHEF iQ format first (avoids pandas' slow per-element
    dateutil fallback and its warning); if that yields nothing usable, retries
    with flexible inference so unusual exports still parse.
    """
    parsed = pd.to_datetime(values, format=CHEF_DATETIME_FORMAT, errors="coerce")
    all_failed = parsed.isna().all() if hasattr(parsed, "isna") else pd.isna(parsed)
    if all_failed:
        parsed = pd.to_datetime(values, errors="coerce")
    return parsed


def _parse_single_file(path_or_buffer, source="data"):
    """Parse one CHEF iQ-style CSV.

    Returns a DataFrame with columns:
        timestamp        : absolute wall-clock time (datetime, may be NaT)
        internal_temp_f  : internal meat temperature (deg F)
        elapsed_s_local  : seconds from this file's own start
        source           : label identifying which file the row came from

    Absolute timestamps come from the per-row Date + Time columns; if those are
    missing we fall back to the 'Created at' header time plus the local elapsed
    seconds.  Absolute time is what lets us stitch several files in real order.
    """
    text = _read_text(path_or_buffer)
    lines = text.splitlines()

    # 'Created at' header line is the fallback anchor for absolute time.
    created_at = pd.NaT
    for ln in lines:
        if ln.lower().startswith("created at:"):
            created_at = _to_datetime(ln.split(":", 1)[1].strip())
            break

    header_idx = next(
        (i for i, ln in enumerate(lines) if ln.startswith(DATA_HEADER_MARKER)),
        None,
    )
    if header_idx is None:
        header_idx = 0  # maybe a plain table without the preamble

    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
    df.columns = [c.strip() for c in df.columns]

    internal_col = _find_internal_temp_column(df.columns)
    internal = pd.to_numeric(df[internal_col], errors="coerce")

    # Local elapsed seconds: prefer the explicit 'Elapsed Time' column.
    elapsed_col = next(
        (c for c in df.columns if c.strip().lower() == "elapsed time"), None
    )
    local_s = None
    if elapsed_col is not None:
        cand = pd.to_numeric(df[elapsed_col], errors="coerce")
        if cand.notna().any():
            local_s = cand

    # Absolute timestamps from Date + Time, if present.
    ts = pd.Series(pd.NaT, index=df.index)
    if {"Date", "Time"}.issubset(df.columns):
        ts = _to_datetime(
            df["Date"].astype(str).str.strip() + " "
            + df["Time"].astype(str).str.strip()
        )

    # If no local elapsed column, derive it from the timestamps.
    if local_s is None:
        if ts.notna().any():
            local_s = (ts - ts.dropna().iloc[0]).dt.total_seconds()
        else:
            raise ValueError(
                f"{source}: no 'Elapsed Time' column and no parseable 'Date'+'Time' "
                "to build a time axis from."
            )

    # Fill any missing absolute timestamps from 'Created at' + local seconds.
    if ts.isna().all() and pd.notna(created_at):
        ts = created_at + pd.to_timedelta(local_s, unit="s")

    out = pd.DataFrame(
        {
            "timestamp": ts,
            "internal_temp_f": internal,
            "elapsed_s_local": pd.to_numeric(local_s, errors="coerce"),
            "source": source,
        }
    )
    out = out.dropna(subset=["internal_temp_f", "elapsed_s_local"]).reset_index(drop=True)
    if len(out) < 1:
        raise ValueError(f"{source}: no usable rows after parsing.")
    return out


# Thresholds for surfacing warnings about a stitched seam.
SEAM_TEMP_JUMP_WARN_F = 10.0   # internal-temp discontinuity across the seam
SEAM_GAP_WARN_MIN = 30.0       # probe-down gap longer than this
SEAM_DIFFERENT_COOK_MIN = 12 * 60.0  # gap so large the files look like separate cooks


def _finalize_single(df):
    """Build elapsed_s/elapsed_h on a parsed/stitched frame, in time order."""
    df = df.sort_values("elapsed_s_local").reset_index(drop=True)
    df["elapsed_s"] = df["elapsed_s_local"] - df["elapsed_s_local"].iloc[0]
    df["elapsed_h"] = df["elapsed_s"] / 3600.0
    if len(df) < 2:
        raise ValueError("Need at least two valid data rows to compute doneness.")
    df.attrs["seams"] = []
    df.attrs["warnings"] = []
    return df


def load_cook_data(path_or_buffer, source="data"):
    """Load a single CHEF iQ-style CSV and return a tidy DataFrame.

    Adds elapsed_s / elapsed_h (from the first sample) and an absolute
    'timestamp' column.  This is the single-file path; use load_cook_files()
    to stitch several files from a probe restart.
    """
    parsed = _parse_single_file(path_or_buffer, source=source)
    return _finalize_single(parsed)


def load_cook_files(paths):
    """Stitch several CHEF iQ CSVs (e.g. from a probe restart) into one cook.

    Files are aligned by their absolute wall-clock timestamps, so they may be
    supplied in any order.  Overlapping rows are trimmed; the down-time gap
    between segments is preserved (the doneness integrator bridges it).  Seam
    locations and any warnings are attached via df.attrs.
    """
    paths = list(paths)
    if len(paths) == 1:
        return load_cook_data(paths[0], source=os.path.basename(str(paths[0])))

    segments = []
    for p in paths:
        label = os.path.basename(str(p))
        seg = _parse_single_file(p, source=label)
        if seg["timestamp"].isna().all():
            raise ValueError(
                f"{label}: has no absolute time (Date/Time or 'Created at'), so it "
                "can't be positioned relative to the other files. Load it on its own."
            )
        seg = seg.dropna(subset=["timestamp"]).sort_values("timestamp")
        segments.append((seg["timestamp"].iloc[0], label, seg))

    # Order segments by real start time, then stitch with overlap trimming.
    segments.sort(key=lambda s: s[0])
    kept = []
    seams = []
    warnings = []
    last_t = None
    last_temp = None
    prev_label = None
    for start_t, label, seg in segments:
        if last_t is not None:
            seg = seg[seg["timestamp"] > last_t]
            if seg.empty:
                warnings.append(
                    f"'{label}' is fully contained within an earlier file's time "
                    "range; it was skipped."
                )
                continue
            first_t = seg["timestamp"].iloc[0]
            first_temp = seg["internal_temp_f"].iloc[0]
            gap_min = (first_t - last_t).total_seconds() / 60.0
            temp_jump = float(first_temp - last_temp)
            seams.append(
                {
                    "timestamp": first_t,
                    "gap_minutes": float(gap_min),
                    "temp_jump_f": temp_jump,
                    "source": label,
                }
            )
            if gap_min >= SEAM_DIFFERENT_COOK_MIN:
                warnings.append(
                    f"'{label}' starts {gap_min / 60:.1f} h after the previous file "
                    "ended - these may be different cooks."
                )
            elif gap_min >= SEAM_GAP_WARN_MIN:
                warnings.append(
                    f"{gap_min:.0f} min gap before '{label}' (probe down). The cook "
                    "time across the gap is interpolated."
                )
            if abs(temp_jump) >= SEAM_TEMP_JUMP_WARN_F:
                warnings.append(
                    f"Internal temp jumps {temp_jump:+.1f} F at the start of "
                    f"'{label}' - check the probe was reinserted to the same depth."
                )
        kept.append(seg)
        last_t = seg["timestamp"].iloc[-1]
        last_temp = seg["internal_temp_f"].iloc[-1]
        prev_label = label

    combined = pd.concat(kept, ignore_index=True).sort_values("timestamp")
    combined = combined.reset_index(drop=True)

    # Global elapsed axis from the earliest timestamp across all segments.
    t0 = combined["timestamp"].iloc[0]
    combined["elapsed_s"] = (combined["timestamp"] - t0).dt.total_seconds()
    combined["elapsed_s_local"] = combined["elapsed_s"]
    combined["elapsed_h"] = combined["elapsed_s"] / 3600.0

    # Convert seam timestamps to elapsed hours for plotting.
    for s in seams:
        s["elapsed_h"] = (s["timestamp"] - t0).total_seconds() / 3600.0
        s["timestamp"] = s["timestamp"].isoformat()

    if len(combined) < 2:
        raise ValueError("Need at least two valid data rows to compute doneness.")

    combined.attrs["seams"] = seams
    combined.attrs["warnings"] = warnings
    return combined


# --------------------------------------------------------------------------
# Doneness computation
# --------------------------------------------------------------------------
@dataclass
class DonenessResult:
    df: pd.DataFrame            # input data + 'rate' and 'cum_percent' columns
    total_percent: float       # final cumulative doneness
    total_hours: float         # total cook+hold duration
    texture: str               # interpretation of total_percent
    seams: list = field(default_factory=list)     # stitch points (probe restarts)
    warnings: list = field(default_factory=list)  # advisory messages for the user


def compute_doneness(df):
    """Integrate the rendering rate over time (trapezoidal, gaps included).

    Adds two columns to a copy of `df`:
        rate         : instantaneous rendering rate (%/hr) at each sample
        cum_percent  : cumulative percent done up to and including each sample
    """
    seams = list(df.attrs.get("seams", []))
    warnings = list(df.attrs.get("warnings", []))
    df = df.copy()
    t_h = df["elapsed_h"].to_numpy()
    temp = df["internal_temp_f"].to_numpy()
    rate = rendering_rate(temp)
    df["rate"] = rate

    dt = np.diff(t_h)                              # hours per interval
    seg = 0.5 * (rate[:-1] + rate[1:]) * dt        # trapezoidal % per interval
    cum = np.concatenate([[0.0], np.cumsum(seg)])  # cumulative % at each sample
    df["cum_percent"] = cum

    return DonenessResult(
        df=df,
        total_percent=float(cum[-1]),
        total_hours=float(t_h[-1]),
        texture=texture_for(float(cum[-1])),
        seams=seams,
        warnings=warnings,
    )


def format_duration(hours):
    total_s = int(round(hours * 3600))
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


# --------------------------------------------------------------------------
# Saving / loading a completed cook (self-contained, reopenable file)
# --------------------------------------------------------------------------
COOK_META_FIELDS = ["cook_name", "cook_date", "meat_weight", "rating", "notes"]


def _now_iso():
    try:
        return datetime.now().isoformat(timespec="seconds")
    except Exception:
        return None


def save_cook(path, result, meta=None):
    """Write a completed cook to a self-contained, reopenable JSON file.

    Stores the raw temperature track, your notes/metadata, a summary snapshot,
    and the model parameters used (so the saved number stays reproducible).
    """
    meta = meta or {}
    df = result.df
    ts = (
        df["timestamp"].apply(
            lambda v: v.isoformat() if pd.notna(v) else None
        ).tolist()
        if "timestamp" in df.columns
        else [None] * len(df)
    )
    payload = {
        "format": COOK_FILE_FORMAT,
        "version": COOK_FILE_VERSION,
        "saved_at": _now_iso(),
        "model": {
            "temps_f": RATE_TABLE_TEMPS.tolist(),
            "rates_pct_per_hr": RATE_TABLE_RATES.tolist(),
            "low_cutoff_f": float(LOW_TEMP_CUTOFF),
            "high_cap_f": float(HIGH_TEMP_CAP),
            "interpolation": "log-linear",
        },
        "meta": {k: meta.get(k, "") for k in COOK_META_FIELDS},
        "summary": {
            "total_percent": result.total_percent,
            "total_hours": result.total_hours,
            "texture": result.texture,
            "peak_internal_f": float(df["internal_temp_f"].max()),
            "n_samples": int(len(df)),
        },
        "seams": result.seams,
        "warnings": result.warnings,
        "data": {
            "timestamp": ts,
            "elapsed_h": df["elapsed_h"].tolist(),
            "internal_temp_f": df["internal_temp_f"].tolist(),
        },
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def load_cook(path):
    """Load a saved cook file.  Returns (df, meta, saved_summary).

    The returned df carries elapsed_h / internal_temp_f (and seams via attrs),
    ready to feed back into compute_doneness() so it re-renders with the
    current model.
    """
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    if payload.get("format") != COOK_FILE_FORMAT:
        raise ValueError("This file is not a saved brisket cook.")

    data = payload.get("data", {})
    df = pd.DataFrame(
        {
            "elapsed_h": data.get("elapsed_h", []),
            "internal_temp_f": data.get("internal_temp_f", []),
        }
    )
    if "timestamp" in data:
        df["timestamp"] = pd.to_datetime(pd.Series(data["timestamp"]), errors="coerce")
    if len(df) < 2:
        raise ValueError("Saved cook has too few data points.")
    df["elapsed_s"] = df["elapsed_h"] * 3600.0
    df.attrs["seams"] = payload.get("seams", [])
    df.attrs["warnings"] = payload.get("warnings", [])

    meta = payload.get("meta", {})
    return df, meta, payload.get("summary", {})


# --------------------------------------------------------------------------
# Plotting
# --------------------------------------------------------------------------
def _time_axis(total_hours):
    """Pick a sensible time unit for the x-axis."""
    if total_hours >= 2:
        return 1.0, "Elapsed time (hours)"
    if total_hours * 60 >= 2:
        return 1.0 / 60.0, "Elapsed time (minutes)"
    return 1.0 / 3600.0, "Elapsed time (seconds)"


def build_figure(result, fig=None):
    """Render the doneness chart onto a matplotlib Figure and return it."""
    import matplotlib

    if fig is None:
        from matplotlib.figure import Figure

        fig = Figure(figsize=(10, 6), dpi=100)
    else:
        fig.clear()

    df = result.df
    scale, xlabel = _time_axis(result.total_hours)
    x = df["elapsed_h"].to_numpy() / scale

    # Left axis: internal temperature.
    ax = fig.add_subplot(111)
    temp = df["internal_temp_f"].to_numpy()
    line_temp, = ax.plot(x, temp, color="tab:blue", lw=1.4, alpha=0.7,
                         zorder=2, label="Internal temp (F)")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Internal temperature (deg F)", color="tab:blue")
    ax.tick_params(axis="y", labelcolor="tab:blue")
    ax.set_xlim(x[0], x[-1] if x[-1] > x[0] else x[0] + 1)
    ax.grid(True, alpha=0.25)

    # Right axis: cumulative percent done, with ideal band + thresholds.
    ax2 = ax.twinx()
    cum = df["cum_percent"].to_numpy()
    ax2.axhspan(95, 105, color="tab:green", alpha=0.12, zorder=0)
    line_ideal = ax2.axhline(100, color="tab:green", lw=1.0, ls="--", alpha=0.8,
                             label="Ideal (100%)")
    ax2.fill_between(x, 0, cum, color="tab:red", alpha=0.10, zorder=1)
    line_done, = ax2.plot(x, cum, color="tab:red", lw=2.2, zorder=3,
                          label="% done (cumulative)")
    ax2.set_ylabel("Percent of cook done (%)", color="tab:red")
    ax2.tick_params(axis="y", labelcolor="tab:red")
    ax2.set_ylim(0, max(120, cum[-1] * 1.1))

    # Annotate the final total.
    ax2.annotate(
        f"{result.total_percent:.1f}%",
        xy=(x[-1], cum[-1]),
        xytext=(-8, 8),
        textcoords="offset points",
        ha="right",
        fontweight="bold",
        color="tab:red",
    )

    # Seam markers: where two stitched files meet (probe restarts).
    for seam in result.seams:
        sx = seam.get("elapsed_h")
        if sx is None:
            continue
        sx = sx / scale
        ax.axvline(sx, color="0.35", ls=":", lw=1.3, zorder=4)
        gap = seam.get("gap_minutes", 0.0)
        ax.annotate(
            f"probe restart  (+{gap:.0f} min gap)",
            xy=(sx, 1.0),
            xycoords=("data", "axes fraction"),
            xytext=(3, -3),
            textcoords="offset points",
            rotation=90,
            va="top",
            ha="left",
            fontsize=7,
            color="0.35",
        )

    fig.suptitle(
        f"Brisket doneness: {result.total_percent:.1f}%  -  {result.texture}\n"
        f"Total time {format_duration(result.total_hours)}",
        fontsize=12,
        fontweight="bold",
    )

    # Combined legend (drawn on the top/right axis so it sits above all lines).
    handles = [line_done, line_temp, line_ideal]
    labels = [h.get_label() for h in handles]
    ax2.legend(handles, labels, loc="upper left", framealpha=0.9)

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return fig


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
REFERENCE_URL = (
    "https://smoketrailsbbq.com/brisket-holding-masterclass-and-tenderness-model/"
)


def rendering_table_text():
    """Human-readable rendering-rate table, built from the model constants."""
    lines = [
        "Collagen rendering rate by internal temp",
        "(Smoke Trails BBQ tenderness model)",
        "",
        f"  {'Temp':>6}    {'Rate':>9}",
        f"  {'-' * 6}    {'-' * 9}",
    ]
    for t, r in zip(RATE_TABLE_TEMPS, RATE_TABLE_RATES):
        lines.append(f"  {t:5.0f}F    {r:5.0f} %/hr")
    lines.append("")
    lines.append("  Below 140F: 0 %/hr   (clamped)")
    lines.append("  At/above 210F: 75 %/hr (clamped)")
    lines.append("  Between points: log-linear interpolation")
    lines.append("")
    lines.append("  ~100% = ideal tenderness")
    lines.append(f"  Reference: {REFERENCE_URL}")
    return "\n".join(lines)


class _ToolTip:
    """A simple hover tooltip for a Tk widget (shows on enter, hides on leave)."""

    def __init__(self, widget, text):
        import tkinter as tk

        self._tk = tk
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = self._tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)       # no title bar / borders
        self.tip.wm_geometry(f"+{x}+{y}")
        self._tk.Label(
            self.tip,
            text=self.text,
            justify="left",
            font=("Consolas", 9),
            background="#ffffe0",
            foreground="#000000",
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=8,
        ).pack()

    def _hide(self, _event=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


def launch_gui(initial_csv=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox

    import matplotlib

    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import (
        FigureCanvasTkAgg,
        NavigationToolbar2Tk,
    )
    from matplotlib.figure import Figure

    root = tk.Tk()
    root.title("Brisket Tenderness Tracker")
    root.geometry("1240x760")

    state = {"result": None}

    # --- top control bar ---
    top = tk.Frame(root, padx=10, pady=8)
    top.pack(side=tk.TOP, fill=tk.X)

    open_btn = tk.Button(top, text="Open CSV(s)...", font=("Segoe UI", 10, "bold"))
    open_btn.pack(side=tk.LEFT)
    load_btn = tk.Button(top, text="Load cook...", font=("Segoe UI", 10))
    load_btn.pack(side=tk.LEFT, padx=(6, 0))
    save_btn = tk.Button(top, text="Save cook...", font=("Segoe UI", 10),
                         state=tk.DISABLED)
    save_btn.pack(side=tk.LEFT, padx=(6, 0))

    # Hover control: shows the model's rendering-rate table on mouse-over.
    info_lbl = tk.Label(
        top,
        text="ⓘ Model rendering rates",
        font=("Segoe UI", 10, "underline"),
        fg="#1f77b4",
        cursor="hand2",
    )
    info_lbl.pack(side=tk.RIGHT)
    _ToolTip(info_lbl, rendering_table_text())

    summary_var = tk.StringVar(
        value="No data loaded. Click 'Open CSV(s)...' to begin."
    )
    tk.Label(top, textvariable=summary_var, font=("Segoe UI", 10),
             justify=tk.LEFT, anchor="w").pack(side=tk.LEFT, padx=14)

    # --- right-hand notes / metadata panel ---
    side = tk.LabelFrame(root, text="Cook details & notes", padx=8, pady=8,
                         font=("Segoe UI", 10, "bold"))
    side.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=8)

    entries = {}
    for label, key in [("Cook name", "cook_name"), ("Date", "cook_date"),
                       ("Meat weight (lb)", "meat_weight"), ("Rating", "rating")]:
        row = tk.Frame(side)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text=label, width=15, anchor="w").pack(side=tk.LEFT)
        ent = tk.Entry(row, width=20)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entries[key] = ent

    tk.Label(side, text="Notes", anchor="w").pack(fill=tk.X, pady=(8, 0))
    notes_frame = tk.Frame(side)
    notes_frame.pack(fill=tk.BOTH, expand=True)
    notes_scroll = tk.Scrollbar(notes_frame)
    notes_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    notes_text = tk.Text(notes_frame, width=34, height=16, wrap=tk.WORD,
                         yscrollcommand=notes_scroll.set, font=("Segoe UI", 9))
    notes_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    notes_scroll.config(command=notes_text.yview)

    # --- figure area (center, fills remaining space) ---
    center = tk.Frame(root)
    center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    fig = Figure(figsize=(10, 6), dpi=100)
    canvas = FigureCanvasTkAgg(fig, master=center)
    toolbar = NavigationToolbar2Tk(canvas, center)
    toolbar.update()
    toolbar.pack(side=tk.BOTTOM, fill=tk.X)
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    # --- metadata helpers ---
    def collect_meta():
        meta = {k: entries[k].get().strip() for k in entries}
        meta["notes"] = notes_text.get("1.0", tk.END).strip()
        return meta

    def apply_meta(meta):
        for k, ent in entries.items():
            ent.delete(0, tk.END)
            ent.insert(0, str(meta.get(k, "") or ""))
        notes_text.delete("1.0", tk.END)
        notes_text.insert("1.0", str(meta.get("notes", "") or ""))

    def render_result(result, title):
        state["result"] = result
        build_figure(result, fig=fig)
        canvas.draw()
        save_btn.config(state=tk.NORMAL)
        summary_var.set(
            f"Total done: {result.total_percent:.1f}%   "
            f"({result.texture})        "
            f"Duration: {format_duration(result.total_hours)}        "
            f"Peak internal: {result.df['internal_temp_f'].max():.1f} F"
        )
        root.title(f"Brisket Tenderness Tracker  -  {title}")
        if result.warnings:
            messagebox.showwarning(
                "Stitched cook - please check",
                "\n\n".join(result.warnings),
            )

    # --- actions ---
    def on_open():
        paths = filedialog.askopenfilenames(
            title="Select brisket probe CSV(s) - pick several to stitch a restart",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not paths:
            return
        try:
            df = load_cook_files(list(paths))
            result = compute_doneness(df)
        except Exception as exc:
            messagebox.showerror("Could not process file(s)", str(exc))
            return
        if len(paths) == 1:
            title = paths[0]
        else:
            title = f"{len(paths)} files stitched"
        render_result(result, title)

    def on_save():
        result = state["result"]
        if result is None:
            messagebox.showinfo("Nothing to save", "Load a cook first.")
            return
        default_name = (entries["cook_name"].get().strip() or "brisket_cook")
        path = filedialog.asksaveasfilename(
            title="Save cook",
            defaultextension=COOK_FILE_EXT,
            initialfile=default_name + COOK_FILE_EXT,
            filetypes=[("Brisket cook", "*" + COOK_FILE_EXT),
                       ("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            save_cook(path, result, collect_meta())
        except Exception as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        messagebox.showinfo("Saved", f"Cook saved to:\n{path}")

    def on_load():
        path = filedialog.askopenfilename(
            title="Load a saved cook",
            filetypes=[("Brisket cook", "*" + COOK_FILE_EXT),
                       ("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            df, meta, _summary = load_cook(path)
            result = compute_doneness(df)
        except Exception as exc:
            messagebox.showerror("Could not load cook", str(exc))
            return
        apply_meta(meta)
        render_result(result, path)

    open_btn.config(command=on_open)
    save_btn.config(command=on_save)
    load_btn.config(command=on_load)

    def _load_initial(path):
        try:
            df = load_cook_data(path)
            result = compute_doneness(df)
        except Exception as exc:
            messagebox.showerror("Could not process file", str(exc))
            return
        render_result(result, path)

    if initial_csv:
        root.after(100, lambda: _load_initial(initial_csv))

    root.mainloop()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def _run_headless(paths):
    df = load_cook_files(paths) if len(paths) > 1 else load_cook_data(paths[0])
    result = compute_doneness(df)
    print(f"File(s): {', '.join(paths)}")
    print(f"Samples: {len(result.df)}")
    print(f"Duration: {format_duration(result.total_hours)} "
          f"({result.total_hours:.4f} h)")
    print(f"Peak internal temp: {result.df['internal_temp_f'].max():.2f} F")
    print(f"Total percent done: {result.total_percent:.2f}%")
    print(f"Texture: {result.texture}")
    if result.seams:
        print(f"Stitched from {len(result.seams) + 1} files; "
              f"{len(result.seams)} seam(s).")
    for w in result.warnings:
        print(f"  ! {w}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    no_gui = "--no-gui" in argv
    if no_gui:
        argv.remove("--no-gui")
    csv_paths = argv

    if no_gui:
        if not csv_paths:
            print("Usage: py -3 brisket_tenderness.py <data.csv> [more.csv ...] --no-gui")
            return 2
        _run_headless(csv_paths)
        return 0

    launch_gui(initial_csv=csv_paths[0] if csv_paths else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
