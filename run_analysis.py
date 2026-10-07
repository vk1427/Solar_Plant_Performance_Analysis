"""
run_analysis.py

1. Loads data/solar_scada_daily.csv into a SQLite database (outputs/solar.db)
2. Runs every query in sql/queries.sql
3. Saves each result to outputs/<query_name>.csv and key findings to outputs/findings.json
"""
import json
import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
CSV = ROOT / "data" / "solar_scada_daily.csv"
SQL_FILE = ROOT / "sql" / "queries.sql"
OUT = ROOT / "outputs"

TARIFF_INR_PER_KWH = 3.0   # ASSUMPTION used only to put a rupee value on lost energy


def parse_queries(text: str) -> dict:
    """Split queries.sql into {name: sql} using the '-- name:' markers."""
    parts = re.split(r"^-- name:\s*(\S+)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    db_path = OUT / "solar.db"
    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(db_path)
    pd.read_csv(CSV).to_sql("scada_daily", con, index=False)

    queries = parse_queries(SQL_FILE.read_text())
    con.executescript(queries.pop("00_setup"))

    results = {}
    for name, sql in queries.items():
        df = pd.read_sql_query(sql, con)
        df.to_csv(OUT / f"{name}.csv", index=False)
        results[name] = df
        print(f"\n=== {name} ({len(df)} rows) ===")
        print(df.head(12).to_string(index=False))

    con.close()

    # ---- Key findings for the README / dashboard ---------------------------
    kpi = results["02_plant_kpis"].iloc[0]
    ranking = results["04_inverter_ranking"]
    loss = results["05_loss_by_inverter"]
    monthly = results["03_monthly_pr"]
    alarms = results["06_alarm_summary"]
    low_days = results["07_underperforming_days"]

    loss_pos = loss[loss["total_loss_mwh"] > 0]
    total_loss_mwh = float(loss_pos["total_loss_mwh"].sum())
    findings = {
        "generation_mwh": float(kpi["generation_mwh"]),
        "plant_pr_pct": float(kpi["plant_pr_pct"]),
        "specific_yield_kwh_per_kwp": float(kpi["specific_yield_kwh_per_kwp"]),
        "avg_availability_pct": float(kpi["avg_availability_pct"]),
        "total_alarms": int(kpi["total_alarms"]),
        "best_month": monthly.loc[monthly["plant_pr_pct"].idxmax(), ["month", "plant_pr_pct"]].tolist(),
        "worst_month": monthly.loc[monthly["plant_pr_pct"].idxmin(), ["month", "plant_pr_pct"]].tolist(),
        "inverters_flagged": ranking[ranking["status"] != "OK"][["inverter_id", "gap_vs_median_pct", "status"]].values.tolist(),
        "total_loss_mwh": round(total_loss_mwh, 1),
        "total_loss_inr_lakh": round(total_loss_mwh * 1000 * TARIFF_INR_PER_KWH / 1e5, 1),
        "tariff_inr_per_kwh": TARIFF_INR_PER_KWH,
        "top_loss": loss.head(5)[["inverter_id", "total_loss_mwh", "downtime_loss_mwh", "underperformance_loss_mwh"]].values.tolist(),
        "alarm_downtime_top": alarms.head(5).values.tolist(),
        "underperforming_days_top": low_days.head(5).values.tolist(),
    }
    (OUT / "findings.json").write_text(json.dumps(findings, indent=2, default=str))
    print("\nSaved findings ->", OUT / "findings.json")


if __name__ == "__main__":
    main()
