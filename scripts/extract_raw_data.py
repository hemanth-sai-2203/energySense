import os
import sys
import csv
import json
import datetime
import sqlite3

BASE_DIR = r"c:\Users\heman\Desktop\project_working\energySense"
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
CLEAN_DIR = os.path.join(BASE_DIR, "data", "clean")
STEPS_DIR = r"C:\Users\heman\.gemini\antigravity-ide\brain\038d5223-2a2b-42c0-90c5-1ea2c8fb8823\.system_generated\steps"

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(CLEAN_DIR, exist_ok=True)

# Step mappings
STEP_MAP = {
    "72": "daily_energy_met_MU.csv",
    "86": "peak_met_MW.csv",
    "88": "peak_unmet_MW.csv",
    "94": "ember_india_monthly_raw.csv",
    "126": "daily_climate_utci.csv",
    "128": "state_maharashtra.csv",
    "130": "state_delhi.csv",
    "84": "state_tamil_nadu.csv",
    "78": "state_andhra_pradesh.csv"
}

def extract_raw_csv(step_num, output_filename):
    src = os.path.join(STEPS_DIR, step_num, "content.md")
    dst = os.path.join(RAW_DIR, output_filename)
    if not os.path.exists(src):
        print(f"Warning: Step {step_num} path does not exist: {src}")
        return False
    
    print(f"Extracting step {step_num} -> {output_filename}...")
    with open(src, "r", encoding="utf-8", errors="ignore") as fin, open(dst, "w", encoding="utf-8", newline="") as fout:
        header_skipped = False
        for line in fin:
            if not header_skipped:
                # Find the start of CSV data (after the metadata separator '---' or first line starting with header fields)
                if line.strip() == "---" or (not line.startswith("Title:") and not line.startswith("Description:") and not line.startswith("Source:") and not line.startswith("OG Description:") and line.strip() != ""):
                    if line.strip() == "---":
                        # Read the next non-empty line as header
                        for next_line in fin:
                            if next_line.strip():
                                fout.write(next_line)
                                break
                    else:
                        fout.write(line)
                    header_skipped = True
            else:
                fout.write(line)
    size_mb = os.path.getsize(dst) / (1024 * 1024)
    print(f"Done: {output_filename} ({size_mb:.2f} MB)")
    return True

for step, fname in STEP_MAP.items():
    extract_raw_csv(step, fname)

print("All raw CSV extraction completed successfully.")
