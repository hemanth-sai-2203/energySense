import csv
import json
import os
import sqlite3
import datetime

def audit_csv(path, date_col='date'):
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return
    
    with open(path, 'r', encoding='utf-8') as f:
        r = csv.reader(f)
        header = next(r)
        rows = list(r)
    
    col_count = len(header)
    row_count = len(rows)
    null_counts = {col: 0 for col in header}
    dates = []
    
    for row in rows:
        for idx, col in enumerate(header):
            val = row[idx].strip() if idx < len(row) else ''
            if val == '' or val.lower() == 'null' or val.lower() == 'none':
                null_counts[col] += 1
        if date_col in header:
            d_idx = header.index(date_col)
            if d_idx < len(row) and row[d_idx].strip():
                dates.append(row[d_idx].strip())
                
    dates_sorted = sorted(dates)
    unique_dates = set(dates)
    dup_dates = len(dates) - len(unique_dates)
    
    print(f"File: {path}")
    print(f"  Rows: {row_count}, Columns: {col_count}")
    print(f"  Header: {header[:8]} ... (total {col_count})")
    print(f"  Earliest Date: {dates_sorted[0] if dates_sorted else 'N/A'}")
    print(f"  Latest Date:   {dates_sorted[-1] if dates_sorted else 'N/A'}")
    print(f"  Unique Dates:  {len(unique_dates)}, Duplicates: {dup_dates}")
    
    if dates_sorted and len(dates_sorted) == len(unique_dates):
        try:
            d_start = datetime.datetime.strptime(dates_sorted[0], '%Y-%m-%d').date()
            d_end = datetime.datetime.strptime(dates_sorted[-1], '%Y-%m-%d').date()
            expected_days = (d_end - d_start).days + 1
            missing_days = expected_days - len(dates_sorted)
            print(f"  Expected Calendar Days: {expected_days}, Missing Days: {missing_days}")
            if missing_days > 0:
                all_exp = {d_start + datetime.timedelta(days=i) for i in range(expected_days)}
                act_set = {datetime.datetime.strptime(d, '%Y-%m-%d').date() for d in dates_sorted}
                missing_set = sorted(list(all_exp - act_set))
                print(f"  First 10 Missing Dates: {[str(d) for d in missing_set[:10]]}")
        except Exception as e:
            print(f"  Date continuity check error: {e}")
            
    print("  Null Counts:")
    has_nulls = False
    for col, cnt in null_counts.items():
        if cnt > 0:
            has_nulls = True
            pct = (cnt / row_count) * 100
            print(f"    {col}: {cnt} nulls ({pct:.2f}%)")
    if not has_nulls:
        print("    None (0 nulls)")
    print()

def audit_sqlite():
    db_path = 'data/clean/energysense.db'
    if not os.path.exists(db_path):
        print("SQLite DB not found!")
        return
    print(f"=== SQLite DB Audit: {db_path} ({os.path.getsize(db_path)/(1024*1024):.2f} MB) ===")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    for t in tables:
        tname = t[0]
        cnt = cur.execute(f"SELECT count(*) FROM {tname}").fetchone()[0]
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info({tname})").fetchall()]
        indexes = cur.execute(f"PRAGMA index_list({tname})").fetchall()
        idx_names = [i[1] for i in indexes]
        print(f"  Table: {tname:<25} Rows: {cnt:<8} Columns: {len(cols):<4} Indexes: {idx_names}")
    conn.close()
    print()

def audit_target_semantics():
    print("=== Target Semantics & Statistical Bounds ===")
    with open('data/clean/daily_demand_india.csv', 'r') as f:
        r = csv.DictReader(f)
        rows = list(r)
    
    e_vals = [float(row['energy_met_mu']) for row in rows if row['energy_met_mu']]
    p_vals = [float(row['peak_met_mw']) for row in rows if row['peak_met_mw']]
    u_vals = [float(row['peak_unmet_mw']) for row in rows if row['peak_unmet_mw']]
    tot_vals = [float(row['total_peak_demand_mw']) for row in rows if row['total_peak_demand_mw']]
    utci_vals = [float(row['utci_celsius']) for row in rows if row['utci_celsius']]

    print(f"Daily Demand Records Analyzed: {len(rows)}")
    print(f"  Energy Met (MU): min={min(e_vals):.1f}, max={max(e_vals):.1f}, avg={sum(e_vals)/len(e_vals):.1f}, zeros={sum(1 for v in e_vals if v <= 0)}")
    print(f"  Peak Met (MW):   min={min(p_vals):.1f}, max={max(p_vals):.1f}, avg={sum(p_vals)/len(p_vals):.1f}, zeros={sum(1 for v in p_vals if v <= 0)}")
    print(f"  Peak Unmet (MW): min={min(u_vals):.1f}, max={max(u_vals):.1f}, avg={sum(u_vals)/len(u_vals):.1f}, zeros={sum(1 for v in u_vals if v <= 0)}")
    print(f"  Total Peak (MW): min={min(tot_vals):.1f}, max={max(tot_vals):.1f}, avg={sum(tot_vals)/len(tot_vals):.1f}")
    print(f"  UTCI (°C):       count={len(utci_vals)}, min={min(utci_vals):.1f}, max={max(utci_vals):.1f}, avg={sum(utci_vals)/len(utci_vals):.1f}")
    print(f"  Missing UTCI:    {len(rows) - len(utci_vals)} rows ({((len(rows) - len(utci_vals))/len(rows))*100:.1f}%)")
    print()

def audit_monthly_gen():
    print("=== Monthly Generation Semantics ===")
    with open('data/clean/monthly_generation_india.csv', 'r') as f:
        r = csv.DictReader(f)
        rows = list(r)
    print(f"Monthly Records: {len(rows)}")
    dates = [row['date'] for row in rows]
    print(f"Earliest Month: {dates[0]}, Latest Month: {dates[-1]}")
    fuels = ['coal_gwh', 'solar_gwh', 'wind_gwh', 'hydro_gwh', 'nuclear_gwh', 'gas_gwh', 'bioenergy_gwh', 'total_gwh']
    for fuel in fuels:
        vals = [float(row[fuel]) for row in rows if row[fuel]]
        print(f"  {fuel:<15}: min={min(vals):.1f}, max={max(vals):.1f}, avg={sum(vals)/len(vals):.1f}")
    print()

if __name__ == '__main__':
    audit_csv('data/clean/daily_demand_india.csv')
    audit_csv('data/clean/monthly_generation_india.csv')
    audit_csv('data/clean/state_annual_summary.csv', date_col='peak_date')
    audit_csv('data/clean/state_daily_demand.csv')
    audit_sqlite()
    audit_target_semantics()
    audit_monthly_gen()
