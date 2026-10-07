-- Solar plant performance analysis (SQLite)
-- Each "-- name:" line starts one query; run_analysis.py runs them in order and saves each result to outputs/<name>.csv
--
-- Definitions
--   PR (performance ratio)  = AC energy / (DC capacity kWp x irradiation kWh/m2)   (availability losses included)
--   Fleet benchmark         = median PR of all inverters on that day (robust to a few faulty units)
--   Availability            = 1 - downtime hours / 10 daylight hours

-- name: 00_setup
DROP VIEW IF EXISTS daily_benchmark;
DROP VIEW IF EXISTS clean;

-- Rows with a valid energy reading, plus daily PR per inverter
CREATE VIEW clean AS
SELECT *,
       ac_energy_kwh / (dc_capacity_kwp * irradiation_kwh_m2) AS pr
FROM scada_daily
WHERE ac_energy_kwh IS NOT NULL
  AND irradiation_kwh_m2 > 0;

-- Median PR across inverters for every day (window functions)
CREATE VIEW daily_benchmark AS
WITH ranked AS (
    SELECT date, pr,
           ROW_NUMBER() OVER (PARTITION BY date ORDER BY pr) AS rn,
           COUNT(*)     OVER (PARTITION BY date)             AS n
    FROM clean
)
SELECT date, AVG(pr) AS median_pr
FROM ranked
WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
GROUP BY date;

-- name: 01_data_quality
SELECT COUNT(*)                              AS total_rows,
       COUNT(DISTINCT inverter_id)           AS inverters,
       MIN(date)                             AS first_day,
       MAX(date)                             AS last_day,
       SUM(ac_energy_kwh IS NULL)            AS missing_energy_readings,
       SUM(dc_voltage_avg_v IS NULL)         AS missing_voltage_readings,
       SUM(ac_energy_kwh < 0)                AS negative_energy_values,
       (SELECT COUNT(*) FROM (SELECT 1 FROM scada_daily
                              GROUP BY date, inverter_id HAVING COUNT(*) > 1)) AS duplicate_keys
FROM scada_daily;

-- name: 02_plant_kpis
SELECT ROUND(SUM(ac_energy_kwh) / 1000.0, 1)                                              AS generation_mwh,
       ROUND(100.0 * SUM(ac_energy_kwh) / SUM(dc_capacity_kwp * irradiation_kwh_m2), 2)   AS plant_pr_pct,
       ROUND(SUM(ac_energy_kwh) / (SUM(dc_capacity_kwp) / COUNT(DISTINCT date)), 1)       AS specific_yield_kwh_per_kwp,
       ROUND(AVG(availability_pct), 2)                                                    AS avg_availability_pct,
       SUM(alarm_count)                                                                   AS total_alarms
FROM clean;

-- name: 03_monthly_pr
SELECT strftime('%Y-%m', date)                                                           AS month,
       ROUND(100.0 * SUM(ac_energy_kwh) / SUM(dc_capacity_kwp * irradiation_kwh_m2), 2)  AS plant_pr_pct,
       ROUND(SUM(ac_energy_kwh) / 1000.0, 1)                                             AS generation_mwh,
       ROUND(AVG(irradiation_kwh_m2), 2)                                                 AS avg_irradiation_kwh_m2,
       ROUND(AVG(module_temp_c), 1)                                                      AS avg_module_temp_c
FROM clean
GROUP BY month
ORDER BY month;

-- name: 04_inverter_ranking
WITH inv AS (
    SELECT inverter_id,
           SUM(ac_energy_kwh) / SUM(dc_capacity_kwp * irradiation_kwh_m2) AS pr,
           AVG(availability_pct)                                          AS avail,
           SUM(alarm_count)                                               AS alarms
    FROM clean
    GROUP BY inverter_id
), ranked AS (
    SELECT pr,
           ROW_NUMBER() OVER (ORDER BY pr) AS rn,
           COUNT(*)     OVER ()            AS n
    FROM inv
), fleet AS (
    SELECT AVG(pr) AS median_pr FROM ranked WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
)
SELECT inv.inverter_id,
       ROUND(100.0 * inv.pr, 2)                           AS pr_pct,
       ROUND(100.0 * fleet.median_pr, 2)                  AS fleet_median_pr_pct,
       ROUND(100.0 * (inv.pr / fleet.median_pr - 1), 2)   AS gap_vs_median_pct,
       ROUND(inv.avail, 2)                                AS avg_availability_pct,
       inv.alarms                                         AS alarms,
       CASE WHEN inv.pr / fleet.median_pr - 1 < -0.03 THEN 'ACTION'
            WHEN inv.pr / fleet.median_pr - 1 < -0.01 THEN 'WATCH'
            ELSE 'OK' END                                 AS status
FROM inv CROSS JOIN fleet
ORDER BY gap_vs_median_pct;

-- name: 05_loss_by_inverter
-- Expected energy = what a median-performing inverter would have produced under the same irradiation.
-- Loss is split into downtime (unit was off) and underperformance (unit was on but produced less).
WITH base AS (
    SELECT c.inverter_id,
           b.median_pr * c.dc_capacity_kwp * c.irradiation_kwh_m2 AS expected_kwh,
           c.availability_pct / 100.0                             AS avail,
           c.ac_energy_kwh                                        AS actual_kwh
    FROM clean c
    JOIN daily_benchmark b ON b.date = c.date
)
SELECT inverter_id,
       ROUND(SUM(expected_kwh) / 1000.0, 1)                        AS expected_mwh,
       ROUND(SUM(actual_kwh) / 1000.0, 1)                          AS actual_mwh,
       ROUND(SUM(expected_kwh * (1 - avail)) / 1000.0, 1)          AS downtime_loss_mwh,
       ROUND(SUM(expected_kwh * avail - actual_kwh) / 1000.0, 1)   AS underperformance_loss_mwh,
       ROUND(SUM(expected_kwh - actual_kwh) / 1000.0, 1)           AS total_loss_mwh
FROM base
GROUP BY inverter_id
ORDER BY total_loss_mwh DESC;

-- name: 06_alarm_summary
SELECT inverter_id,
       main_alarm                      AS alarm_type,
       COUNT(*)                        AS days_with_alarm,
       SUM(alarm_count)                AS total_alarms,
       ROUND(SUM(downtime_hours), 1)   AS downtime_hours
FROM scada_daily
WHERE main_alarm <> 'None'
GROUP BY inverter_id, main_alarm
ORDER BY downtime_hours DESC, total_alarms DESC;

-- name: 07_underperforming_days
-- Days an inverter was running (availability >= 99%) but produced >5% less than the fleet median
SELECT c.inverter_id,
       COUNT(*)      AS days_below_95pct_of_fleet,
       MIN(c.date)   AS first_day,
       MAX(c.date)   AS last_day
FROM clean c
JOIN daily_benchmark b ON b.date = c.date
WHERE c.availability_pct >= 99
  AND c.pr < 0.95 * b.median_pr
GROUP BY c.inverter_id
ORDER BY days_below_95pct_of_fleet DESC;

-- name: 08_weekly_deviation
SELECT CAST(strftime('%W', c.date) AS INTEGER) AS week,
       c.inverter_id,
       ROUND(100.0 * (SUM(c.ac_energy_kwh)
                      / SUM(b.median_pr * c.dc_capacity_kwp * c.irradiation_kwh_m2) - 1), 2) AS deviation_pct
FROM clean c
JOIN daily_benchmark b ON b.date = c.date
GROUP BY week, c.inverter_id
ORDER BY week, c.inverter_id;
