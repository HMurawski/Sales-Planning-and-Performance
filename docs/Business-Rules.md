# Business Rules & Definitions

## 0) Glossary
- **Plan** – monthly target revenue (this year).
- **Actual** – monthly realized revenue (this year).
- **LY** – last year’s same-month revenue.
- **Efficiency** – `Actual / Plan` (YTD or full-year).
- **Actual_adj** – Actual after Windfall/Shortfall adjustments (rules below).
- **AOB** – area band defining **base annual bonus** (not efficiency).
- **Advance** – quarterly payout based on YTD entitlement delta.
- **True-up** – year-end reconciliation vs. total entitlement.
- **Carryover** – next-year opening negative balance if overpaid.
- **NEW** – account created in the current year (LY=0, Plan=0).

## 1) Organization & Data Grain
- **Hierarchy:** 1 Country Manager → **2 Area Managers** → **10 Salespeople**  
  Cities and AOB (area band):
  - HIGH: Warsaw, Krakow, Wroclaw
  - MED: Lodz, Poznan, Gdansk
  - LOW: Szczecin, Lublin, Bydgoszcz, Bialystok
- **Accounts per salesperson:** Tier5 only in HIGH cities (3–10), Tier3 (5–20), Tier1 (40–70).
- **Time:** monthly grain, **12 months**. Quarters:
  - Q1: Jan 1–Mar 31, Q2: Apr 1–Jun 30, Q3: Jul 1–Sep 30, Q4: Oct 1–Dec 31.
- **Date dimension:** include `IsQuarterEnd`, `IsYearEnd`.

## 2) AOB (Base Annual Bonus, PLN)
- LOW = **36,000**; MED = **48,000**; HIGH = **60,000**.  
AOB affects **base annual bonus only**, not efficiency.

## 3) Tenure Bonus (payout-only)
- **+1 percentage point (pp)** per **full 3 years** of service.  
- **Cap = 5 pp** (15 years).  
- Applied to payout efficiency **only**.  
- Tenure increases **every Jan 1** for employees present the prior full year.

**Formulas**
- eff_raw = SUM(Actual_adj) / SUM(Plan)
- tenure_pp = MIN( floor(tenure_years / 3), 5 ) / 100
- eff_payout = eff_raw + tenure_pp

## 4) Payout Ladder (Option A with precise 120%)
Map `eff_payout` (YTD or full-year) to a **payout factor** of AOB:

| Efficiency range      | Payout factor of AOB |
|-----------------------|----------------------|
| 0.0 – 0.899           | 0.00                 |
| 0.900 – 0.949         | 0.65                 |
| 0.950 – 0.999         | 0.80                 |
| 1.000 – 1.049         | 1.00                 |
| 1.050 – 1.099         | 1.15                 |
| 1.100 – 1.199         | 1.30                 |
| **≥ 1.200**           | **1.50 (cap)**       |

> **Boundary rule:** 1.200+ is always 1.50 (no 1.40 band).

## 5) Quarterly Advances & Year-End True-Up
- **Entitled_YTD** = `BaseAOB * PayoutFactor(eff_payout_YTD)`.
- **Advance_Q** = `max(0, Entitled_YTD(Q_end) − Entitled_YTD(prev_Q_end))`.
- **Year-end (Q4):**  
  `Final_Entitled_Year = BaseAOB * PayoutFactor(eff_payout_full_year)`  
  `Carryover = Advances_Paid_Year − Final_Entitled_Year`  
  If positive, the salesperson starts next year with **negative opening balance** (e.g., −5,000 PLN).

**Next year repayment logic:**  
Let `OpeningCarryover < 0` denote owed amount `Outstanding = abs(OpeningCarryover)`.  
Then for each quarter:
- NetEntitled_YTD = max(0, Entitled_YTD - Outstanding)
- Advance_Q = max(0, NetEntitled_YTD - Advances_Paid_YTD)

Advances first **repay carryover**, then pay new entitlement. Base AOB is unchanged.

## 6) Windfall / Shortfall (W/S)

### 6.1 Detection (per account, monthly)
- If `Actual_{t-1} = 0` and the account is **not NEW** → **do not flag** in month `t`.  
- Otherwise:
- delta_mom = (Actual_t - Actual_{t-1}) / Actual_{t-1}
- Windfall if delta_mom ≥ +10%
- Shortfall if delta_mom ≤ −10%

### 6.2 Attribution (synthetic, random by Tier)
When a W/S event is detected, set `sales_driven ∈ {True, False}` with:
- Tier5 → **80%** True
- Tier3 → **65%** True
- Tier1 → **50%** True

**NEW accounts:** first month with revenue is treated as **Sales-driven** (no W/S).

### 6.3 “Healthy account” for Shortfall protection
- Compute `healthy_prev3 = avg_{t-1..t-3}(Actual_adj / Plan)`.  
- **Healthy** if `healthy_prev3 ≥ 95%` (0.95).

### 6.4 Adjusted Actual (Actual_adj)
- **Windfall (delta ≥ +10%)**
  - `sales_driven = True` → **no change**: `Actual_adj = Actual`.
  - `sales_driven = False` → **cap to Plan without rescuing**: `Actual_adj = min(Actual, Plan)`  
    (If below 100% anyway, keep Actual; we do not “help lost cases”.)

- **Shortfall (delta ≤ −10%)**
  - `sales_driven = True` → **no change**.
  - `sales_driven = False` → **rescue only healthy accounts**:  
    If `healthy_prev3` → `Actual_adj = max(Actual, Plan)` (effectively = Plan).  
    Else **no change** (do not help chronic underperformance).

**Note:** W/S adjustments are **per account, per month**. Aggregation to salesperson uses `Actual_adj`.

## 7) Manager KPIs (Area/Country)
Efficiency computed on **sums**, never average of %:
- eff_area = SUM(Actual_adj) / SUM(Plan)
- eff_country = SUM(Actual_adj) / SUM(Plan)

## 8) Planning YoY (on **Accounts**)
- Each account receives an uplift based on the **highest band reached** (0..5) by **its salesperson’s `eff_raw` for the year**?  
  **Final rule (agreed):** uplift is assigned **per account**, based on the **account’s own annual eff_raw**.

- **Bands → uplift**: **+2 percentage points per band** (0..5)  
  e.g., band 0 → +2%, band 5 → +12%.

**Formulas**
- eff_raw_account_year = SUM_Y(Actual_adj) / SUM_Y(Plan)
- band = 0 if eff<0.90; 1 if 0.90–0.949; 2 if 0.95–0.999; 3 if 1.00–1.049; 4 if 1.05–1.099; 5 if 1.10–1.199 or ≥1.20
- uplift = 0.02 * band
- Plan_next_year_account = Plan_year * (1 + uplift)
Portfolio growth is the **sum of accounts’ new plans**.

**NEW accounts:** for next year, set  
`Plan_next = avg_monthly_revenue_current_year * 12`.

## 9) Rounding & Currency
- Efficiency rounding: **0.1 pp** (e.g., 98.3%).  
- Amounts rounding: **10 PLN**.  
- Currency: **PLN** everywhere.

## 10) Data Model (CSV Inputs/Outputs)

### 10.1 Config (inputs)
- `aob_config.csv` → columns: `aob_band` ∈ {LOW, MED, HIGH}, `base_bonus_year_pln` ∈ {36000,48000,60000}
- `payout_rules.csv` → ladder as in §4 (explicit lower/upper bounds)
- `planning_rules.csv` → bands 0..5 → uplifts {0.02, 0.04, …, 0.12}
- `ws_config.csv` → `ws_threshold=0.10`, `p_sales_driven_tier5=0.80`, `tier3=0.65`, `tier1=0.50`
- `date_dim.csv` → calendar with `IsQuarterEnd`, `IsYearEnd`

### 10.2 Dimensions (inputs)
- `org_hierarchy.csv` → `country_id`, `area_id`, `area_name`, `aob_band`, `salesperson_id`, `city`, `tenure_years`
- `accounts_dim.csv` → `account_id`, `account_name`, `tier`, `city`, `is_new` (0/1)

### 10.3 Fact (generated)
- `sales_monthly.csv` →  
  `date, year, month, quarter, country_id, area_id, salesperson_id, account_id, tier,`  
  `plan_revenue, actual_revenue, last_year_revenue,`  
  `windfall_flag, shortfall_flag, sales_driven (0/1), healthy_prev3 (0/1),`  
  `actual_adj`

### 10.4 Planning outputs (generated)
- `target_reco.csv` → per account: `plan_year`, `band`, `uplift`, `plan_next_year`
- `portfolio_actions.csv` (optional) → per salesperson: suggested actions
- `payouts_quarterly.csv` (optional) → per salesperson: YTD eff, entitled, advances, carryover

## 11) Power BI Measures (essentials)
- `ActualAdj_YTD`, `Plan_YTD`
- `Eff_YTD_Raw = DIVIDE(ActualAdj_YTD, Plan_YTD)`
- `TenurePP` (min cap 5 pp), `Eff_YTD_Payout = Eff_YTD_Raw + TenurePP`
- `PayoutFactor` (SWITCH with exact boundaries per §4)
- `BaseBonusYear` (from AOB band)
- `Entitled_YTD = BaseBonusYear * PayoutFactor`
- `Advance_Q = MAX(0, Entitled_YTD_at_QEnd - Entitled_YTD_at_PrevQEnd)`
- `Final_Entitled_Year` (at YearEnd)
- `Advances_Paid_Year = SUMX(QuarterEnds, Advance_Q)`
- `Carryover_NextYear = Advances_Paid_Year - Final_Entitled_Year`

## 12) Repro & Seed
- Synthetic generator uses `random_state = 1337` for deterministic runs.

## 13) Ethics
- All data is **synthetic**. Any resemblance to real entities is coincidental.
- Business logic is generalized to avoid revealing confidential processes.