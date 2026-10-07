"""
generate_data.py

Creates a SIMULATED daily SCADA-style dataset for a 3 MWp solar plant
(12 inverters x 250 kWp, calendar year 2025).

*** This is NOT real plant data. ***  A fixed random seed makes it fully reproducible.

Known issues injected into the data (the "answer key" the analysis should rediscover):
  INV-04  string fault: ~10% output loss from 15 Mar to 10 Oct 2025, then repaired
  INV-09  dusty block: soils ~3x faster than the rest -> saw-tooth loss, reset by cleaning / rain
  INV-11  6-day inverter outage, 8-13 Jul 2025
  INV-02  repeated DC over-voltage trips (short downtime, voltage spikes)
  Plant   random grid trips and comm-loss alarms, plus 10 missing SCADA energy readings
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N_INV = 12
CAP_KWP = 250.0          # DC capacity per inverter
BASE_PR = 0.88           # PR before temperature / soiling / fault losses
DAYLIGHT_H = 10.0        # hours per day in which downtime is counted
TEMP_COEFF = 0.0035      # power loss per deg C above 25 C

rng = np.random.default_rng(SEED)

dates = pd.date_range("2025-01-01", "2025-12-31", freq="D")
n = len(dates)
doy = dates.dayofyear.to_numpy()

# ---- Plant-level weather ---------------------------------------------------
season = np.sin(2 * np.pi * (doy - 80) / 365)          # ~ +1 late June, ~ -1 late Dec
monsoon = (doy >= 182) & (doy <= 273)                   # Jul - Sep
winter_haze = (doy <= 40) | (doy >= 335)

clear_sky = 4.7 + 1.5 * season                          # kWh/m2/day, ~3.2 .. 6.2
cloud_mean = np.where(monsoon, 0.62, np.where(winter_haze, 0.86, 0.92))
cloud_sd = np.where(monsoon, 0.14, 0.07)
cloud = np.clip(cloud_mean + rng.normal(0, cloud_sd), 0.25, 1.0)
irradiation = np.clip(clear_sky * cloud, 0.6, 7.2)      # plane-of-array, kWh/m2/day
rain_day = monsoon & (cloud < 0.55)                     # very cloudy monsoon days wash the panels
clean_day = (doy % 30 == 0)                             # scheduled panel cleaning every 30 days

ambient = 24 + 10 * season - 3 * monsoon + rng.normal(0, 1.5, n)
module_temp = ambient + 12 + 12 * (irradiation / 7.0)
temp_loss = TEMP_COEFF * np.clip(module_temp - 25, 0, None)

# ---- Inverter-level parameters --------------------------------------------
inv_ids = [f"INV-{i:02d}" for i in range(1, N_INV + 1)]
bias = rng.normal(1.0, 0.006, N_INV)                    # small permanent unit-to-unit differences
soil_rate = np.clip(rng.normal(0.0012, 0.0002, N_INV), 0.0007, None)   # soiling loss per dry day
soil_rate[8] = 0.0035                                   # INV-09 (index 8) is the dusty block

IDX_INV02, IDX_INV04, IDX_INV09, IDX_INV11 = 1, 3, 8, 10

fault_start, fault_end = pd.Timestamp("2025-03-15"), pd.Timestamp("2025-10-10")
outage_start, outage_end = pd.Timestamp("2025-07-08"), pd.Timestamp("2025-07-13")
overvoltage_days = set(rng.choice(n, size=14, replace=False).tolist())   # INV-02 trip days

soil = np.zeros(N_INV)
rows = []

for d in range(n):
    date = dates[d]

    # soiling build-up / reset
    if clean_day[d]:
        soil[:] = 0.0
    elif rain_day[d]:
        soil *= 0.2
    else:
        soil = np.minimum(soil + soil_rate, 0.14)

    downtime = np.zeros(N_INV)
    alarms = np.zeros(N_INV, dtype=int)
    alarm_type = ["None"] * N_INV
    v_spike = np.zeros(N_INV, dtype=bool)

    for i in range(N_INV):
        r = rng.random()
        if r < 0.012:                                   # short grid trip
            downtime[i] += rng.uniform(0.5, 1.5)
            alarms[i] += int(rng.integers(1, 3))
            alarm_type[i] = "Grid trip"
        elif r < 0.032:                                 # communication loss, no energy impact
            alarms[i] += 1
            alarm_type[i] = "Comm loss"

    if d in overvoltage_days:                           # INV-02 DC over-voltage trip
        downtime[IDX_INV02] = rng.uniform(1.0, 3.0)
        alarms[IDX_INV02] = int(rng.integers(2, 7))
        alarm_type[IDX_INV02] = "DC overvoltage"
        v_spike[IDX_INV02] = True

    if outage_start <= date <= outage_end:              # INV-11 hardware outage
        downtime[IDX_INV11] = DAYLIGHT_H
        alarms[IDX_INV11] = int(rng.integers(8, 15))
        alarm_type[IDX_INV11] = "Inverter fault"

    downtime = np.minimum(downtime, DAYLIGHT_H)
    availability = 1.0 - downtime / DAYLIGHT_H

    fault = np.zeros(N_INV)
    if fault_start <= date <= fault_end:
        fault[IDX_INV04] = 0.10                         # two failed strings on INV-04

    pr_eff = (BASE_PR * (1 - temp_loss[d]) * (1 - soil) * (1 - fault)
              * bias * (1 + rng.normal(0, 0.01, N_INV)))
    ac_energy = CAP_KWP * irradiation[d] * pr_eff * availability

    v_avg = 780 - 2.0 * (module_temp[d] - 25) + rng.normal(0, 4, N_INV)
    v_max = v_avg + np.abs(rng.normal(30, 8, N_INV))
    v_max[v_spike] = 1010 + rng.uniform(0, 40, v_spike.sum())
    v_avg[availability == 0] = np.nan
    v_max[availability == 0] = np.nan

    for i in range(N_INV):
        rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "inverter_id": inv_ids[i],
            "dc_capacity_kwp": CAP_KWP,
            "irradiation_kwh_m2": round(float(irradiation[d]), 2),
            "module_temp_c": round(float(module_temp[d]), 1),
            "dc_voltage_avg_v": None if np.isnan(v_avg[i]) else round(float(v_avg[i]), 1),
            "dc_voltage_max_v": None if np.isnan(v_max[i]) else round(float(v_max[i]), 1),
            "ac_energy_kwh": round(float(ac_energy[i]), 1),
            "downtime_hours": round(float(downtime[i]), 2),
            "availability_pct": round(float(availability[i] * 100), 1),
            "alarm_count": int(alarms[i]),
            "main_alarm": alarm_type[i],
        })

df = pd.DataFrame(rows)

# SCADA communication gaps: a few energy readings are missing
missing_idx = rng.choice(len(df), size=10, replace=False)
df.loc[missing_idx, "ac_energy_kwh"] = np.nan

out = Path(__file__).parent / "data"
out.mkdir(exist_ok=True)
df.to_csv(out / "solar_scada_daily.csv", index=False)

print(f"Wrote {len(df):,} rows ({df['inverter_id'].nunique()} inverters x {n} days) "
      f"-> {out / 'solar_scada_daily.csv'}")
