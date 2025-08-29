"""
generate_synthetic_data.py
Synthetic generator for Sales KPI & Bonus (year=2024).
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict

DATA_DIR = Path("data")
SEED = 1337
rng = np.random.default_rng(SEED)

# === PARAMS ===
YEAR = 2024
CITIES_AOB = {
    "Warsaw": "HIGH", "Krakow": "HIGH", "Wroclaw": "HIGH",
    "Lodz": "MED", "Poznan": "MED", "Gdansk": "MED",
    "Szczecin": "LOW", "Lublin": "LOW", "Bydgoszcz": "LOW", "Bialystok": "LOW",
}
SALESPEOPLE = [
    ("SP_WAW_001", "Warsaw"), ("SP_KRK_001","Krakow"), ("SP_WRO_001","Wroclaw"),
    ("SP_LOD_001","Lodz"), ("SP_POZ_001","Poznan"), ("SP_GDA_001","Gdansk"),
    ("SP_SZC_001","Szczecin"), ("SP_LBL_001","Lublin"), ("SP_BYD_001","Bydgoszcz"), ("SP_BIA_001","Bialystok"),
]
# 2 Areas / 2 Area Managers
AREA_MAP = {
    "North":  ["Gdansk","Szczecin","Bydgoszcz","Bialystok","Poznan"],
    "South":  ["Krakow","Wroclaw","Lodz","Lublin","Warsaw"],
}
AREA_IDS = {"North":"PL_N","South":"PL_S"}
AM_IDS = {"North":"AM_N_001","South":"AM_S_001"}
COUNTRY_ID = "PL"; COUNTRY_MANAGER_ID = "CM_PL_001"

# Accounts per tier per salesperson (min,max)
TIER_COUNTS = {1:(40,70), 3:(5,20), 5:(3,10)}  # Tier5 only for HIGH cities
# LY monthly baseline ranges by tier (PLN)
LY_MONTHLY_BOUNDS = {1:(3000,10000), 3:(10000,40000), 5:(40000,150000)}
# Growth to Plan 2024 vs LY (by tier) – widened for variance
GROWTH_RANGE = {1:(0.02,0.08), 3:(0.03,0.10), 5:(0.04,0.12)}
# Seasonality profile (12 values sum ~1.0)
SEASONALITY = np.array([0.07,0.07,0.08,0.08,0.08,0.09,0.09,0.09,0.09,0.09,0.09,0.08])
# Noise (relative) for Actual vs Plan – increased
ACTUAL_NOISE_SD = {1:0.12, 3:0.10, 5:0.08}
# W/S params
P_WS_EVENT = 0.10
WS_THRESHOLD = 0.10  # ±10%
# sales_driven probabilities (by tier) when W/S occurs – increased
P_SALES_DRIVEN = {5:0.90, 3:0.75, 1:0.60}

# === Load configs ===
def load_config() -> Dict[str, pd.DataFrame]:
    cfg = {}
    cfg["aob"] = pd.read_csv(DATA_DIR/"aob_config.csv")
    cfg["payout"] = pd.read_csv(DATA_DIR/"payout_rules.csv")
    cfg["planning"] = pd.read_csv(DATA_DIR/"planning_rules.csv")
    cfg["ws"] = pd.read_csv(DATA_DIR/"ws_config.csv")
    date_dim = pd.read_csv(DATA_DIR/"date_dim.csv", parse_dates=["date"])
    # filter by YEAR using the parsed date to avoid type issues
    date_dim["year"] = date_dim["date"].dt.year
    date_dim["month"] = date_dim["date"].dt.month
    cfg["date"] = date_dim[date_dim["year"]==YEAR].copy().reset_index(drop=True)
    assert len(cfg["date"])==12, "date_dim must contain 12 rows for the selected year."
    return cfg

# === Build org & accounts ===
def build_org_accounts(cfg):
    # org_hierarchy
    rows = []
    for sp_id, city in SALESPEOPLE:
        area_name = next(a for a, cities in AREA_MAP.items() if city in cities)
        rows.append(dict(
            country_id=COUNTRY_ID, country_manager_id=COUNTRY_MANAGER_ID,
            area_id=AREA_IDS[area_name], area_manager_id=AM_IDS[area_name], area_name=area_name,
            aob_band=CITIES_AOB[city], salesperson_id=sp_id, city=city, tenure_years=int(rng.integers(0,16))
        ))
    org = pd.DataFrame(rows)

    # accounts_dim
    acc_rows = []
    for sp_id, city in SALESPEOPLE:
        aob = CITIES_AOB[city]
        t1 = int(rng.integers(*TIER_COUNTS[1]))
        t3 = int(rng.integers(*TIER_COUNTS[3]))
        t5 = int(rng.integers(*TIER_COUNTS[5])) if aob=="HIGH" else 0
        def make_ids(prefix, n):
            return [f"{prefix}_{i:04d}" for i in range(1, n+1)]
        for acc_id in make_ids(f"ACC_T1_{sp_id}", t1):
            acc_rows.append(dict(account_id=acc_id, account_name=acc_id, tier=1, city=city, salesperson_id=sp_id, is_new=0))
        for acc_id in make_ids(f"ACC_T3_{sp_id}", t3):
            acc_rows.append(dict(account_id=acc_id, account_name=acc_id, tier=3, city=city, salesperson_id=sp_id, is_new=0))
        for acc_id in make_ids(f"ACC_T5_{sp_id}", t5):
            acc_rows.append(dict(account_id=acc_id, account_name=acc_id, tier=5, city=city, salesperson_id=sp_id, is_new=0))

    accounts = pd.DataFrame(acc_rows)
    return org, accounts

# === Generate LY (2023), Plan (2024), Actual (2024) with correlated multipliers ===
def generate_fact(cfg, org, accounts) -> pd.DataFrame:
    dd = cfg["date"][["date","year","month","quarter"]].copy()

    # NEW accounts in 2024 (plan=0, LY=0)
    accounts = accounts.copy()
    new_rate = {1:0.08, 3:0.05, 5:0.02}
    accounts["is_new"] = accounts["tier"].apply(lambda t: int(rng.random() < new_rate[t]))

    # --- correlated multipliers ---
    sp_ids = org["salesperson_id"].tolist()

    # Plan tightness (affects PLAN only) – always >= 1.00
    plan_tightness_sp = {sp: float(np.clip(rng.normal(1.06, 0.04), 1.00, 1.18)) for sp in sp_ids}

    # Salesperson efficiency (affects ACTUAL)
    eff_sp = {sp: float(np.clip(rng.normal(1.00, 0.06), 0.85, 1.20)) for sp in sp_ids}

    # Per-account stickiness (affects ACTUAL)
    eff_acc = {acc_id: float(np.clip(rng.normal(1.00, 0.04), 0.85, 1.20)) for acc_id in accounts["account_id"]}

    # Per-salesperson quarterly shocks (affects ACTUAL)
    q_list = ["Q1","Q2","Q3","Q4"]
    q_shock_spq = {sp: {q: float(np.clip(rng.normal(1.00, 0.05), 0.85, 1.20)) for q in q_list} for sp in sp_ids}
    # --------------------------------

    # Precompute LY monthly per account (start from annual LY per tier and split by seasonality)
    fact_rows = []
    for _, acc in accounts.iterrows():
        tier = int(acc.tier)
        sp_id = acc.salesperson_id

        # Draw annual LY base by tier, then split by seasonality
        ly_min, ly_max = LY_MONTHLY_BOUNDS[tier]
        mean_month = float(rng.uniform(ly_min, ly_max))  # average monthly LY
        ly_months = (SEASONALITY * (mean_month * 12.0)).astype(float)

        # Growth for Plan 2024
        g_lo, g_hi = GROWTH_RANGE[tier]
        growth = float(rng.uniform(g_lo, g_hi))

        for i, row in dd.iterrows():
            # PLAN: LY * (1+growth) * plan tightness (unless NEW)
            plan_base = 0.0 if acc.is_new==1 else ly_months[i] * (1.0 + growth)
            plan = plan_base * plan_tightness_sp[sp_id]

            # LY for reporting
            ly = 0.0 if acc.is_new==1 else ly_months[i]

            # ACTUAL:
            q = row["quarter"]
            if plan == 0.0:  # NEW account: organic ramp + multipliers
                ramp = (i+1)/12.0
                base = mean_month * float(rng.uniform(0.4, 0.8)) * ramp
                # light noise on new accounts + multipliers
                actual = base * eff_sp[sp_id] * eff_acc[acc.account_id] * q_shock_spq[sp_id][q] * float(rng.normal(1.0, 0.08))
            else:
                sd = ACTUAL_NOISE_SD[tier]
                noise = float(rng.normal(1.0, sd))
                actual = plan * eff_sp[sp_id] * eff_acc[acc.account_id] * q_shock_spq[sp_id][q] * noise

            fact_rows.append(dict(
                date=row["date"], year=int(row["year"]), month=int(row["month"]), quarter=row["quarter"],
                country_id=COUNTRY_ID,
                area_id=org.loc[org.salesperson_id==sp_id, "area_id"].iloc[0],
                salesperson_id=sp_id, account_id=acc.account_id, tier=tier,
                plan_revenue=max(0.0, plan),
                actual_revenue=max(0.0, actual),
                last_year_revenue=max(0.0, ly),
                windfall_flag=0, shortfall_flag=0, sales_driven=0, healthy_prev3=0,
                actual_adj=0.0
            ))

    fact = pd.DataFrame(fact_rows).sort_values(["account_id","date"]).reset_index(drop=True)
    return fact

# === W/S detection, attribution, and Actual_adj ===
def apply_ws_adjustments(cfg, fact: pd.DataFrame, accounts: pd.DataFrame) -> pd.DataFrame:
    ws_thr = WS_THRESHOLD
    p_sd = P_SALES_DRIVEN

    fact = fact.sort_values(["account_id","date"]).copy()
    fact["actual_adj"] = fact["actual_revenue"].astype(float)
    fact["windfall_flag"] = 0; fact["shortfall_flag"] = 0
    fact["sales_driven"] = 0; fact["healthy_prev3"] = 0

    for acc_id, grp in fact.groupby("account_id", sort=False):
        grp = grp.copy().reset_index()
        is_new = int(accounts.loc[accounts.account_id==acc_id, "is_new"].iloc[0]) == 1
        first_nonzero_seen = False

        for t in range(len(grp)):
            if t == 0:
                continue

            prev_actual = grp.loc[t-1,"actual_revenue"]
            # skip W/S when previous actual is zero for non-new accounts
            if prev_actual == 0 and not is_new:
                continue

            # NEW: first non-zero actual month is treated as sales-driven (no W/S)
            if is_new and not first_nonzero_seen and grp.loc[t,"actual_revenue"] > 0:
                first_nonzero_seen = True
                continue

            # healthy_prev3: avg of (Actual_adj/Plan) over previous up to 3 months
            start = max(0, t-3)
            window = grp.iloc[start:t]
            ratios = []
            for _, r in window.iterrows():
                pr = r["plan_revenue"]
                if pr > 0:
                    ratios.append(r["actual_adj"]/pr)
            healthy = (np.nanmean(ratios) if len(ratios)>0 else 0.0) >= 0.95
            grp.loc[t,"healthy_prev3"] = int(healthy)

            # MoM delta
            prev = prev_actual if prev_actual != 0 else 1.0
            delta = (grp.loc[t,"actual_revenue"] - prev_actual) / prev
            is_wind = delta >= ws_thr
            is_short = delta <= -ws_thr
            if not (is_wind or is_short):
                continue

            tier = int(grp.loc[t,"tier"])
            sales_driven = rng.random() < p_sd[tier]
            grp.loc[t,"sales_driven"] = int(sales_driven)

            plan_t = grp.loc[t,"plan_revenue"]
            actual_t = grp.loc[t,"actual_revenue"]

            if is_wind:
                grp.loc[t,"windfall_flag"] = 1
                if not sales_driven:
                    # cap to Plan but don't "help" if under Plan
                    grp.loc[t,"actual_adj"] = min(actual_t, plan_t) if plan_t>0 else actual_t
            else:  # shortfall
                grp.loc[t,"shortfall_flag"] = 1
                if not sales_driven and healthy and plan_t>0:
                    # rescue to Plan
                    grp.loc[t,"actual_adj"] = max(actual_t, plan_t)

        fact.loc[grp["index"], ["windfall_flag","shortfall_flag","sales_driven","healthy_prev3","actual_adj"]] = \
            grp[["windfall_flag","shortfall_flag","sales_driven","healthy_prev3","actual_adj"]].values

    # cast
    fact["sales_driven"] = fact["sales_driven"].fillna(0).astype(int)
    fact["healthy_prev3"] = fact["healthy_prev3"].fillna(0).astype(int)
    fact["windfall_flag"] = fact["windfall_flag"].astype(int)
    fact["shortfall_flag"] = fact["shortfall_flag"].astype(int)
    fact["actual_adj"] = fact["actual_adj"].astype(float)

    return fact

def main():
    cfg = load_config()
    org, accounts = build_org_accounts(cfg)
    fact = generate_fact(cfg, org, accounts)
    fact = apply_ws_adjustments(cfg, fact, accounts)

    # Save outputs
    org_out = DATA_DIR/"org_hierarchy.csv"
    acc_out = DATA_DIR/"accounts_dim.csv"
    fact_out = DATA_DIR/"sales_monthly.csv"
    org.to_csv(org_out, index=False)
    accounts.to_csv(acc_out, index=False)
    fact.to_csv(fact_out, index=False)
    print(f"Saved: {org_out}, {acc_out}, {fact_out}")

if __name__ == "__main__":
    main()
