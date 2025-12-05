import pandas as pd
import sys
import os

file_path = "../Comprehensive Comparison of each step.xlsx"

if not os.path.exists(file_path):
    print(f"Error: File not found at {file_path}")
    sys.exit(1)

try:
    # Read all sheets
    xls = pd.ExcelFile(file_path)
    print(f"📂 File: {os.path.basename(file_path)}")
    print(f"📑 Sheets found: {xls.sheet_names}")
    print("-" * 50)
    
    for sheet in xls.sheet_names:
        print(f"- {sheet}")


except Exception as e:
    print(f"❌ Error reading Excel file: {e}")
