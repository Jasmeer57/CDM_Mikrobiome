import json
import pandas as pd
import os
import glob

def summarize_json(filepath):
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
            
        if isinstance(data, list):
            sample = data[:2]
            keys = set()
            for d in data:
                keys.update(d.keys())
            return {"type": "list", "length": len(data), "keys": list(keys), "sample": sample}
        elif isinstance(data, dict):
            if "results" in data:
                return {"type": "dict_with_results", "length": len(data["results"]), "sample": data["results"][:2]}
            else:
                return {"type": "dict", "keys": list(data.keys()), "sample": {k: data[k] for k in list(data.keys())[:2]}}
        return {"type": type(data).__name__}
    except Exception as e:
        return {"error": str(e)}

def summarize_csv(filepath):
    try:
        df = pd.read_csv(filepath, nrows=5)
        return {"columns": list(df.columns), "sample": df.head(2).to_dict('records')}
    except Exception as e:
        return {"error": str(e)}

results = {}
for filepath in sorted(glob.glob('*.json') + glob.glob('relationships/*.json') + glob.glob('neo4j/*.json') + glob.glob('*.csv') + glob.glob('relationships/*.csv') + glob.glob('neo4j/*.csv')):
    if filepath.endswith('.json'):
        results[filepath] = summarize_json(filepath)
    elif filepath.endswith('.csv'):
        results[filepath] = summarize_csv(filepath)

with open('evaluation_summary.json', 'w') as f:
    json.dump(results, f, indent=2)
