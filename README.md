# Sales KPI & Bonus – Synthetic Portfolio (Poland)

> **Disclaimer**
> This project uses **fully synthetic data**. The business logic is **inspired by my real-world work** in enterprise sales analytics, but **no proprietary data, company names, or exact internal formulas** are disclosed. The repo is for learning and portfolio purposes only.

## Scope (TL;DR)
- **Hierarchy:** Country → 2 Areas → 10 Salespeople (major Polish cities) → Accounts (Tier 1/3/5).
- **Mechanics:** annual KPI with **quarterly advances**, year-end **true-up** and **carryover**; **Windfall/Shortfall** anomaly handling; **tenure bonus** (pp) for payout only; **YoY planning** (uplifts on accounts).
- **Tech:** Python (ETL + W/S + planning) + Power BI (DAX for KPI/payout/advances, interactive views).

## Project Plan
1) **Business rules** (this repo: `/docs/Business-Rules.md`)  
2) **Config CSVs** (AOB, payout ladder, planning, W/S, date dim)  
3) **Synthetic data generator** (org, accounts, LY/Plan/Actual, seasonality, NEW)  
4) **W/S + attribution** in Python → `Actual_adj`  
5) **Power BI model & measures** (Country/Area/Sales/Why)  
6) **Planning YoY** on accounts in Python → `target_reco.csv` (Planning view)  
7) **Portfolio polish**: README, GIF, 1-pager, tests

## Repo Layout (planned)
```
/data/ # CSV configs & facts (synthetic)
/src/ # Python (generator, W/S, planning)
/notebooks/ # 01_data_quality, 02_windfall_shortfall, 03_planning_yoy
/powerbi/ # Sales_KPI_Bonus.pbix
/docs/ # Business-Rules.md
README.md

```
## Repro
- Deterministic generator with `random_state = 1337`.
- All thresholds and bands controlled by CSV configs (no magic numbers in code/DAX).