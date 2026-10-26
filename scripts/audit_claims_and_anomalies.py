import csv
import json
import os
import datetime
from collections import defaultdict

def audit_missing_dates():
    print("=== Gaps & Missing Dates Analysis ===")
    with open('data/clean/daily_demand_india.csv', 'r') as f:
        r = csv.DictReader(f)
        dates = [datetime.datetime.strptime(row['date'], '%Y-%m-%d').date() for row in r]
    
    dates_set = set(dates)
    d_start = min(dates)
    d_end = max(dates)
    
    gaps = []
    curr_gap = []
    cur = d_start
    while cur <= d_end:
        if cur not in dates_set:
            curr_gap.append(cur)
        else:
            if curr_gap:
                gaps.append((curr_gap[0], curr_gap[-1], len(curr_gap)))
                curr_gap = []
        cur += datetime.timedelta(days=1)
    if curr_gap:
        gaps.append((curr_gap[0], curr_gap[-1], len(curr_gap)))
        
    print(f"Total missing days: {sum(g[2] for g in gaps)} in {len(gaps)} discrete gap clusters:")
    for g in sorted(gaps, key=lambda x: x[2], reverse=True)[:10]:
        print(f"  {g[0]} to {g[1]}: {g[2]} consecutive days missing")
        
    # Check days per year
    by_year = defaultdict(int)
    for d in dates:
        by_year[d.year] += 1
    print("\nRecorded Days per Year:")
    for yr in sorted(by_year.keys()):
        leap = 366 if (yr % 4 == 0 and (yr % 100 != 0 or yr % 400 == 0)) else 365
        if yr == 2024: leap = 119 # up to Apr 28
        print(f"  {yr}: {by_year[yr]} days recorded (Expected: {leap}, Missing: {leap - by_year[yr]})")

def audit_negative_unmet():
    print("\n=== Negative Unmet Peak Demand Anomaly ===")
    with open('data/clean/daily_demand_india.csv', 'r') as f:
        r = csv.DictReader(f)
        neg_rows = [row for row in r if float(row['peak_unmet_mw']) < 0]
    print(f"Found {len(neg_rows)} rows with negative peak_unmet_mw:")
    for r in neg_rows[:5]:
        print(f"  Date: {r['date']}, Peak Met: {r['peak_met_mw']}, Peak Unmet: {r['peak_unmet_mw']}, Total: {r['total_peak_demand_mw']}")

def audit_claims():
    print("\n=== Audit of Report Claims ===")
    with open('data/clean/insights_analytics.json', 'r') as f:
        ins = json.load(f)
    print("Reported Insights JSON:")
    print(json.dumps(ins, indent=2))
    
    # 1. CAGR Claim: 8.27%
    # Report states: 2013 total = 716799.6 MU, 2023 total = 1586382.8 MU
    # Let's check 2013 recorded days: in 2013, how many days were recorded?
    with open('data/clean/daily_demand_india.csv', 'r') as f:
        r = list(csv.DictReader(f))
    
    r_2013 = [x for x in r if x['year'] == '2013']
    r_2023 = [x for x in r if x['year'] == '2023']
    sum_2013 = sum(float(x['energy_met_mu']) for x in r_2013)
    sum_2023 = sum(float(x['energy_met_mu']) for x in r_2023)
    print(f"\nCAGR Check:")
    print(f"  2013 rows: {len(r_2013)} days, Sum: {sum_2013:.1f} MU, Daily Avg: {sum_2013/len(r_2013):.1f} MU")
    print(f"  2023 rows: {len(r_2023)} days, Sum: {sum_2023:.1f} MU, Daily Avg: {sum_2023/len(r_2023):.1f} MU")
    print(f"  Reported 2013 sum: {ins['growth_10yr_cagr']['total_mu_2013']}")
    print(f"  Notice 2013 has only {len(r_2013)} days recorded (missing {365 - len(r_2013)} days)!")
    
    # Daily average annualized:
    ann_2013 = (sum_2013 / len(r_2013)) * 365
    ann_2023 = (sum_2023 / len(r_2023)) * 365
    cagr_raw_sums = ((sum_2023 / sum_2013) ** (1/10) - 1) * 100
    cagr_daily_avg = (((sum_2023/len(r_2023)) / (sum_2013/len(r_2013))) ** (1/10) - 1) * 100
    print(f"  CAGR using unadjusted sums (formula in script): {cagr_raw_sums:.2f}%")
    print(f"  CAGR using daily average (correct annualized): {cagr_daily_avg:.2f}%")
    
    # 2. Deficit reduction: 5685.6 MW to 383.0 MW (-93.3%)
    avg_def_2013 = sum(float(x['peak_unmet_mw']) for x in r_2013) / len(r_2013)
    avg_def_2023 = sum(float(x['peak_unmet_mw']) for x in r_2023) / len(r_2023)
    red_pct = ((avg_def_2013 - avg_def_2023) / avg_def_2013) * 100
    print(f"\nDeficit Reduction Check:")
    print(f"  2013 avg unmet: {avg_def_2013:.1f} MW")
    print(f"  2023 avg unmet: {avg_def_2023:.1f} MW")
    print(f"  Calculated reduction: {red_pct:.2f}% (Report: {ins['grid_reliability_progress']['deficit_reduction_pct']}%)")
    
    # 3. Thermal sensitivity: 199.7 MW/deg C with Pearson r = 0.059
    print(f"\nThermal Sensitivity Check:")
    print(f"  Reported Pearson correlation: {ins['climate_demand_sensitivity']['pearson_correlation']}")
    print(f"  Reported Slope: {ins['climate_demand_sensitivity']['heat_sensitivity_mw_per_celsius']} MW/°C")
    print(f"  Methodological flaw: Naive bivariate OLS across 2013-2020 confounded by +8% annual load growth, no detrending, no seasonal controls.")

    # 4. Clean energy share peak: 35.74% in '2025-07-01'
    with open('data/clean/monthly_generation_india.csv', 'r') as f:
        gen = list(csv.DictReader(f))
    clean_shares = [(x['date'], float(x['clean_share_pct'])) for x in gen]
    clean_shares.sort(key=lambda x: x[1], reverse=True)
    print(f"\nClean Energy Share Peaks:")
    for dt, sh in clean_shares[:5]:
        print(f"  Date: {dt}, Clean Share: {sh:.2f}%")

if __name__ == '__main__':
    audit_missing_dates()
    audit_negative_unmet()
    audit_claims()
