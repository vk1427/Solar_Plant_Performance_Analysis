"""
make_dashboard.py

Reads the CSV results written by run_analysis.py and draws:
  images/dashboard.png          (KPI tiles + 4 panels, for the LinkedIn Featured section)
  images/01_monthly_pr.png, 02_inverter_gap.png, 03_weekly_heatmap.png, 04_energy_loss.png
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch, Rectangle

ROOT = Path(__file__).parent
OUT = ROOT / "outputs"
IMG = ROOT / "images"
IMG.mkdir(exist_ok=True)

# ---- Palette (validated categorical / sequential / diverging steps) ----------
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
BLUE, BLUE_LIGHT, BLUE_DARK, ORANGE = "#2a78d6", "#86b6ef", "#184f95", "#eb6834"
RED, NEUTRAL = "#e34948", "#f0efec"
DIVERGING = LinearSegmentedColormap.from_list("div", [RED, NEUTRAL, BLUE])

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})

REF_PR = 80.0
HEATMAP_LABELS = {          # short diagnosis shown next to the inverters the analysis flagged
    "INV-02": "INV-02  DC trips",
    "INV-04": "INV-04  string fault",
    "INV-09": "INV-09  soiling",
    "INV-11": "INV-11  outage",
}

findings = json.loads((OUT / "findings.json").read_text())
monthly = pd.read_csv(OUT / "03_monthly_pr.csv")
ranking = pd.read_csv(OUT / "04_inverter_ranking.csv")
loss = pd.read_csv(OUT / "05_loss_by_inverter.csv")
weekly = pd.read_csv(OUT / "08_weekly_deviation.csv")


def style(ax, grid="y"):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelcolor=INK2, labelsize=9, length=3)
    if grid:
        ax.grid(axis=grid, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def title(ax, text):
    ax.set_title(text, loc="left", fontsize=11.5, fontweight="bold", color=INK, pad=12)


# ---- Panels ---------------------------------------------------------------
def panel_monthly(ax):
    x = np.arange(len(monthly))
    y = monthly["plant_pr_pct"].to_numpy()
    labels = pd.to_datetime(monthly["month"]).dt.strftime("%b")
    ax.axhline(REF_PR, color=MUTED, lw=1, ls="--")
    ax.text(len(x) - 1, REF_PR + 0.35, f"Reference {REF_PR:.0f}%", ha="right", va="bottom",
            fontsize=8.5, color=INK2)
    ax.plot(x, y, color=BLUE, lw=2, marker="o", ms=6, mfc=BLUE, mec=SURFACE, mew=1.5, zorder=3)
    for i, off in ((int(y.argmin()), -16), (int(y.argmax()), 9)):
        ax.annotate(f"{y[i]:.1f}%", (x[i], y[i]), xytext=(0, off), textcoords="offset points",
                    ha="center", fontsize=9, fontweight="bold", color=INK)
    ax.set_xticks(x, labels)
    ax.set_ylim(np.floor(y.min() - 3), np.ceil(y.max() + 3))
    ax.set_ylabel("PR (%)", color=INK2, fontsize=9)
    style(ax, "y")
    title(ax, "Plant performance ratio by month")


def panel_gap(ax):
    d = ranking.sort_values("gap_vs_median_pct", ascending=False).reset_index(drop=True)
    colors = d["status"].map({"OK": BLUE_LIGHT, "WATCH": BLUE, "ACTION": BLUE_DARK})
    y = np.arange(len(d))
    ax.barh(y, d["gap_vs_median_pct"], color=colors, height=0.62)
    ax.axvline(0, color=BASELINE, lw=1.4)
    ax.set_yticks(y, d["inverter_id"])
    ax.invert_yaxis()
    for yi, (gap, status) in enumerate(zip(d["gap_vs_median_pct"], d["status"])):
        if status != "OK":
            ax.text(gap - 0.12, yi, f"{gap:+.1f}%", ha="right", va="center",
                    fontsize=9, fontweight="bold", color=INK)
    lo = min(d["gap_vs_median_pct"].min() - 1.6, -3)
    ax.set_xlim(lo, max(d["gap_vs_median_pct"].max() + 0.6, 1.5))
    ax.set_xlabel("Annual PR vs fleet median (%)", color=INK2, fontsize=9)
    ax.legend(handles=[Patch(color=BLUE_LIGHT, label="OK"),
                       Patch(color=BLUE, label="Watch (1-3% below)"),
                       Patch(color=BLUE_DARK, label="Action (>3% below)")],
              loc="upper left", frameon=False, fontsize=8.5, labelcolor=INK2)
    style(ax, "x")
    title(ax, "Inverter performance vs fleet median")


def panel_heatmap(ax, fig):
    pivot = weekly.pivot(index="inverter_id", columns="week", values="deviation_pct").sort_index()
    data = np.ma.masked_invalid(pivot.to_numpy())
    n_inv, n_wk = pivot.shape
    mesh = ax.pcolormesh(np.arange(n_wk + 1), np.arange(n_inv + 1), data, cmap=DIVERGING,
                         vmin=-10, vmax=10, edgecolors=SURFACE, linewidth=0.6)
    ax.set_yticks(np.arange(n_inv) + 0.5,
                  [HEATMAP_LABELS.get(i, i) for i in pivot.index])
    for tick, inv in zip(ax.get_yticklabels(), pivot.index):
        if inv in HEATMAP_LABELS:
            tick.set_fontweight("bold")
            tick.set_color(INK)
    month_weeks = [int(pd.Timestamp(2025, m, 1).strftime("%W")) for m in range(1, 13)]
    ax.set_xticks(np.array(month_weeks) + 0.5, [pd.Timestamp(2025, m, 1).strftime("%b") for m in range(1, 13)])
    ax.invert_yaxis()
    ax.set_xlim(0, n_wk)
    style(ax, None)
    ax.tick_params(length=0, labelsize=8.5)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(False)
    cbar = fig.colorbar(mesh, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Weekly output vs fleet median (%)", color=INK2, fontsize=8.5)
    cbar.ax.tick_params(colors=MUTED, labelcolor=INK2, labelsize=8.5, length=2)
    cbar.outline.set_visible(False)
    title(ax, "Weekly deviation by inverter (red = below fleet)")


def panel_loss(ax):
    d = loss[loss["total_loss_mwh"] > 0].head(5).iloc[::-1].reset_index(drop=True)
    under = d["underperformance_loss_mwh"].clip(lower=0)
    down = d["downtime_loss_mwh"].clip(lower=0)
    y = np.arange(len(d))
    ax.barh(y, under, color=BLUE, height=0.6, edgecolor=SURFACE, linewidth=1.5)
    ax.barh(y, down, left=under, color=ORANGE, height=0.6, edgecolor=SURFACE, linewidth=1.5)
    ax.set_yticks(y, d["inverter_id"])
    for yi, (u, dn) in enumerate(zip(under, down)):
        ax.text(u + dn + 0.4, yi, f"{u + dn:.1f} MWh", va="center", fontsize=9,
                fontweight="bold", color=INK)
    ax.set_xlim(0, (under + down).max() * 1.22)
    ax.set_xlabel("Estimated energy shortfall vs fleet median (MWh)", color=INK2, fontsize=9)
    ax.legend(handles=[Patch(color=BLUE, label="Underperformance (running, lower output)"),
                       Patch(color=ORANGE, label="Downtime (unit off)")],
              loc="lower right", frameon=False, fontsize=8.5, labelcolor=INK2)
    style(ax, "x")
    title(ax, "Where the energy was lost (top 5 inverters)")


# ---- Combined dashboard ---------------------------------------------------
def kpi_tile(ax, label, value, sub):
    ax.set_axis_off()
    ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, facecolor=SURFACE,
                           edgecolor=GRID, linewidth=1.2))
    ax.text(0.06, 0.74, label, transform=ax.transAxes, fontsize=9.5, color=INK2)
    ax.text(0.06, 0.36, value, transform=ax.transAxes, fontsize=21, color=INK, fontweight="bold")
    ax.text(0.06, 0.1, sub, transform=ax.transAxes, fontsize=8.5, color=MUTED)


fig = plt.figure(figsize=(16, 11), dpi=150)
gs = fig.add_gridspec(3, 2, height_ratios=[0.3, 1, 1], hspace=0.5, wspace=0.34,
                      left=0.125, right=0.975, top=0.875, bottom=0.075)

fig.text(0.04, 0.955, "Solar Plant Performance Dashboard", fontsize=21, fontweight="bold", color=INK)
fig.text(0.04, 0.922,"3 MWp plant  |  12 inverters x 250 kWp  |  Jan-Dec 2025  |  "
         "SIMULATED SCADA-style data (not real plant data)", fontsize=10.5, color=INK2)

tiles = gs[0, :].subgridspec(1, 4, wspace=0.08)
kpi_tile(fig.add_subplot(tiles[0]), "Plant performance ratio", f"{findings['plant_pr_pct']:.1f}%",
         f"{findings['specific_yield_kwh_per_kwp']:,.0f} kWh/kWp specific yield")
kpi_tile(fig.add_subplot(tiles[1]), "Energy generated", f"{findings['generation_mwh']:,.0f} MWh", "full year, all inverters")
kpi_tile(fig.add_subplot(tiles[2]), "Estimated energy shortfall", f"{findings['total_loss_mwh']:,.0f} MWh",
         f"about Rs {findings['total_loss_inr_lakh']:.1f} lakh at Rs {findings['tariff_inr_per_kwh']:.2f}/kWh (assumed)")
kpi_tile(fig.add_subplot(tiles[3]), "Average availability", f"{findings['avg_availability_pct']:.1f}%",
         f"{findings['total_alarms']:,} alarms logged")

panel_monthly(fig.add_subplot(gs[1, 0]))
panel_gap(fig.add_subplot(gs[1, 1]))
panel_heatmap(fig.add_subplot(gs[2, 0]), fig)
panel_loss(fig.add_subplot(gs[2, 1]))

fig.text(0.04, 0.025, "PR = AC energy / (kWp x irradiation).  Benchmark = daily median PR across inverters.  "
         "Availability window = 10 daylight hours.  Tariff is an assumption.  Tools: Python, SQL (SQLite), pandas, matplotlib.",
         fontsize=8.5, color=MUTED)
fig.savefig(IMG / "dashboard.png")
plt.close(fig)

# ---- Individual panels ----------------------------------------------------
for fname, fn, size in (("01_monthly_pr.png", panel_monthly, (8, 5)),
                        ("02_inverter_gap.png", panel_gap, (8, 5.5)),
                        ("04_energy_loss.png", panel_loss, (8, 5))):
    f, a = plt.subplots(figsize=size, dpi=150)
    f.subplots_adjust(left=0.13, right=0.96, top=0.88, bottom=0.14)
    fn(a)
    f.savefig(IMG / fname)
    plt.close(f)

f, a = plt.subplots(figsize=(10, 5.5), dpi=150)
f.subplots_adjust(left=0.2, right=0.94, top=0.88, bottom=0.1)
panel_heatmap(a, f)
f.savefig(IMG / "03_weekly_heatmap.png")
plt.close(f)

print("Saved images ->", IMG)
