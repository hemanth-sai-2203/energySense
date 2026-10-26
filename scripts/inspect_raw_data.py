import os
import csv

BASE_DIR = r"c:\Users\heman\Desktop\project_working\energySense\data\raw"
files = [
    "daily_energy_met_MU.csv",
    "peak_met_MW.csv",
    "peak_unmet_MW.csv",
    "daily_climate_utci.csv",
    "state_maharashtra.csv",
    "state_delhi.csv",
    "ember_india_monthly_raw.csv"
]

for f in files:
    path = os.path.join(BASE_DIR, f)
    print(f"\n=================== {f} ===================")
    with open(path, "r", encoding="utf-8", errors="ignore") as fin:
        reader = csv.reader(fin)
        for i in range(4):
            try:
                row = next(reader)
                if len(row) > 10:
                    print(f"Row {i} (len={len(row)}): {row[:6]} ... {row[-3:]}")
                else:
                    print(f"Row {i}: {row}")
            except StopIteration:
                break
