import time
import re
import os
import sys
from collections import defaultdict
from datetime import datetime

LOG_FILE = 'cdm_pipeline.log'

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def parse_log_line(line):
    # Parse timestamp
    timestamp_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    timestamp = timestamp_match.group(1) if timestamp_match else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Parse Pass info
    pass_match = re.search(r'Pass (\d+) found (\d+) entities', line)
    if pass_match:
        return 'pass_complete', int(pass_match.group(1)), int(pass_match.group(2)), timestamp

    # Parse Start Pass
    start_pass_match = re.search(r'Starting Pass (\d+)', line)
    if start_pass_match:
        return 'pass_start', int(start_pass_match.group(1)), 0, timestamp
        
    # Parse File info (if available in logs, though currently logs might not explicitly say "Processing file X" often enough)
    # But we can infer activity.
    
    return None, None, None, None

def monitor():
    print(f"Waiting for log file: {LOG_FILE}...")
    while not os.path.exists(LOG_FILE):
        time.sleep(1)

    print(f"Monitoring {LOG_FILE}...")
    
    pass_counts = defaultdict(int)
    total_entities = 0
    active_pass = None
    last_update = datetime.now()
    
    with open(LOG_FILE, 'r') as f:
        # Go to end of file
        # f.seek(0, 2) 
        # Actually, let's read the whole file first to get current state
        lines = f.readlines()
        for line in lines:
            event, pass_num, count, ts = parse_log_line(line)
            if event == 'pass_complete':
                pass_counts[pass_num] += count
                total_entities += count
                active_pass = None
            elif event == 'pass_start':
                active_pass = pass_num

        while True:
            line = f.readline()
            if not line:
                # Update display every second if no new lines
                if (datetime.now() - last_update).total_seconds() > 1:
                    clear_screen()
                    print(f"=== CDM PIPELINE MONITOR ===")
                    print(f"Last Update: {datetime.now().strftime('%H:%M:%S')}")
                    print(f"Total Entities Found: {total_entities}")
                    print("-" * 30)
                    print(f"{'Pass':<10} | {'Entities':<10}")
                    print("-" * 30)
                    for p in sorted(pass_counts.keys()):
                        print(f"Pass {p:<5} | {pass_counts[p]:<10}")
                    print("-" * 30)
                    if active_pass:
                        print(f"Currently Running: Pass {active_pass}...")
                    else:
                        print("Idle / Processing...")
                    last_update = datetime.now()
                
                time.sleep(0.1)
                continue

            event, pass_num, count, ts = parse_log_line(line)
            if event == 'pass_complete':
                pass_counts[pass_num] += count
                total_entities += count
                active_pass = None
                last_update = datetime.now() - getattr(time, 'timedelta', lambda x: x)(seconds=2) # Force update
            elif event == 'pass_start':
                active_pass = pass_num
                last_update = datetime.now() - getattr(time, 'timedelta', lambda x: x)(seconds=2) # Force update

if __name__ == "__main__":
    try:
        monitor()
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
