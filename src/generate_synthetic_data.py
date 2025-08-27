"""
generate_synthetic_data.py
Synthetic generator for Sales KPI & Bonus (year=2024).
- Builds org & accounts
- Creates LY (2023), Plan & Actual (2024)
- Flags Windfall/Shortfall (+/-10% MoM), samples sales_driven by Tier
- Applies Actual_adj per Business-Rules (incl. healthy_prev3 >=95%)
- Outputs /data/sales_monthly.csv (+ updates dims if needed)
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict

DATA_DIR = Path("data")
SEED = 1337
rng = np.random.default_rng(SEED)

# === PARAMS  ===
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
AREA_MAP = { # 2 Areas/2 Area Menagers
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
# Growth to Plan 2024 vs LY (by tier)
GROWTH_RANGE = {1:(0.02,0.06), 3:(0.03,0.08), 5:(0.04,0.10)}
# Seasonality profile (12 values sum ~1.0)
SEASONALITY = np.array([0.07,0.07,0.08,0.08,0.08,0.09,0.09,0.09,0.09,0.09,0.09,0.08])
# Noise (relative) for Actual vs Plan
ACTUAL_NOISE_SD = {1:0.07, 3:0.06, 5:0.05}
# Probability of a W/S event in a given month (per account)
P_WS_EVENT = 0.10
WS_THRESHOLD = 0.10  # ±10%
# sales_driven probabilities (by tier) when W/S occurs
P_SALES_DRIVEN = {5:0.80, 3:0.65, 1:0.50}

# === Load configs ===
def load_config() -> Dict[str, pd.DataFrame]:
    cfg = {}
    cfg["aob"] = pd.read_csv(DATA_DIR/"aob_config.csv")
    cfg["payout"] = pd.read_csv(DATA_DIR/"payout_rules.csv")
    cfg["planning"] = pd.read_csv(DATA_DIR/"planning_rules.csv")
    cfg["ws"] = pd.read_csv(DATA_DIR/"ws_config.csv")
    date_dim = pd.read_csv(DATA_DIR/"date_dim.csv", parse_dates=["date"])
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
            aob_band=CITIES_AOB[city], salesperson_id=sp_id, city=city, tenure_years=rng.integers(0,16)
        ))
    org = pd.DataFrame(rows)

    # accounts_dim
    acc_rows = []
    for sp_id, city in SALESPEOPLE:
        aob = CITIES_AOB[city]
        # decide tier counts
        t1 = rng.integers(*TIER_COUNTS[1])
        t3 = rng.integers(*TIER_COUNTS[3])
        t5 = rng.integers(*TIER_COUNTS[5]) if aob=="HIGH" else 0
        # create ids
        def make_ids(prefix, n):
            return [f"{prefix}_{i:04d}" for i in range(1, n+1)]
        for acc_id in make_ids(f"ACC_T1_{sp_id}", t1):
            acc_rows.append(dict(account_id=acc_id, account_name=f"{acc_id}", tier=1, city=city, salesperson_id=sp_id, is_new=0))
        for acc_id in make_ids(f"ACC_T3_{sp_id}", t3):
            acc_rows.append(dict(account_id=acc_id, account_name=f"{acc_id}", tier=3, city=city, salesperson_id=sp_id, is_new=0))
        for acc_id in make_ids(f"ACC_T5_{sp_id}", t5):
            acc_rows.append(dict(account_id=acc_id, account_name=f"{acc_id}", tier=5, city=city, salesperson_id=sp_id, is_new=0))

    accounts = pd.DataFrame(acc_rows)
    return org, accounts

# === Generate LY (2023), Plan (2024), Actual (2024) ===
def generate_fact(cfg, org, accounts) -> pd.DataFrame:
    dd = cfg["date"][["date","year","month","quarter"]].copy()
    # some NEW accounts in 2024 (plan=0, LY=0)
    accounts = accounts.copy()
    # NEW rate: small fraction by tier
    new_rate = {1:0.08, 3:0.05, 5:0.02}
    accounts["is_new"] = accounts["tier"].apply(lambda t: int(rng.random() < new_rate[t]))

    # Precompute LY monthly per account (start from annual LY per tier and split by seasonality)
    fact_rows = []
    for _, acc in accounts.iterrows():
        tier = int(acc.tier)
        sp_id = acc.salesperson_id
        city = acc.city

        # Draw annual LY base by tier, then split by seasonality
        ly_min, ly_max = LY_MONTHLY_BOUNDS[tier]
        # Annual LY as mean_month * 12
        mean_month = rng.uniform(ly_min, ly_max)
        ly_months = (SEASONALITY * (mean_month * 12)).astype(float)

        # Growth for Plan 2024
        g_lo, g_hi = GROWTH_RANGE[tier]
        growth = rng.uniform(g_lo, g_hi)

        # Build 12 rows for 2024
        for i, row in cfg["date"].iterrows():
            plan = 0.0 if acc.is_new==1 else ly_months[i] * (1.0 + growth)
            ly   = 0.0 if acc.is_new==1 else ly_months[i]
            # Actual: around Plan with noise
            if plan == 0.0:  # NEW account: generate actual as organic revenue
                # Draw a small ramp-up pattern
                ramp = (i+1)/12.0
                base = mean_month * rng.uniform(0.4, 0.8) * ramp
                actual = base
            else:
                sd = ACTUAL_NOISE_SD[tier]
                actual = plan * rng.normal(1.0, sd)

            fact_rows.append(dict(
                date=row["date"], year=row["year"], month=int(row["month"]), quarter=row["quarter"],
                country_id=COUNTRY_ID,
                area_id=org.loc[org.salesperson_id==sp_id, "area_id"].iloc[0],
                salesperson_id=sp_id, account_id=acc.account_id, tier=tier,
                plan_revenue=max(0.0, plan), actual_revenue=max(0.0, actual), last_year_revenue=max(0.0, ly),
                windfall_flag=0, shortfall_flag=0, sales_driven=None, healthy_prev3=None,
                actual_adj=None
            ))
    fact = pd.DataFrame(fact_rows).sort_values(["account_id","date"]).reset_index(drop=True)
    return fact

# === W/S detection, attribution, and Actual_adj ===
def apply_ws_adjustments(cfg, fact: pd.DataFrame, accounts: pd.DataFrame) -> pd.DataFrame:
    ws_thr = WS_THRESHOLD
    # Map tier->p(sales_driven)
    p_sd = P_SALES_DRIVEN

    fact = fact.sort_values(["account_id","date"]).copy()
    fact["actual_adj"] = fact["actual_revenue"].astype(float)
    fact["windfall_flag"] = 0; fact["shortfall_flag"] = 0
    fact["sales_driven"] = 0

    # helper to compute healthy_prev3 ratio
    fact["plan_eps"] = fact["plan_revenue"].replace(0, np.nan)  # avoid 0-div in ratio; handled by rules below

    for acc_id, grp in fact.groupby("account_id", sort=False):
        grp = grp.copy().reset_index(drop=True)
        # NEW: if LY=0 & Plan=0 in first nonzero actual month, treat as sales-driven (no W/S)
        # We'll still run generic W/S for consistency, but rules below will not "rescue" lost cases improperly.

        for t in range(len(grp)):
            if t==0:
                prev_actual = grp.loc[t,"actual_revenue"]
                prev_plan = grp.loc[t,"plan_revenue"]
                # no W/S on first month unless there is meaningful prev (we skip by design)
                grp.loc[t,"healthy_prev3"] = 0
                continue

            prev_actual = grp.loc[t-1,"actual_revenue"]
            if prev_actual==0 and grp.loc[t-1,"last_year_revenue"]==0:
                # non-NEW with zero prev actual: skip W/S to avoid infinite delta
                grp.loc[t,"healthy_prev3"] = 0
                continue

            delta = (grp.loc[t,"actual_revenue"] - prev_actual) / (prev_actual if prev_actual!=0 else 1.0)

            # healthy_prev3: avg of (Actual_adj/Plan) over t-1..t-3
            start = max(0, t-3)
            window = grp.iloc[start:t]
            if len(window)>0:
                ratios = []
                for _, r in window.iterrows():
                    if r["plan_revenue"]>0:
                        ratios.append(r["actual_adj"]/r["plan_revenue"])
                healthy = (np.nanmean(ratios) if len(ratios)>0 else 0.0) >= 0.95
            else:
                healthy = False
            grp.loc[t,"healthy_prev3"] = int(healthy)

            is_wind = delta >= ws_thr
            is_short = delta <= -ws_thr
            if not (is_wind or is_short):
                continue

            # Attribution
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

        fact.loc[grp.index, :] = grp

    # fill NaNs
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
