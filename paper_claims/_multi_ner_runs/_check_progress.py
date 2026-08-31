import json
cp = json.load(open('paper_claims/_multi_ner_runs/mapping_checkpoint.json', encoding='utf-8'))
done = len(cp['done'])
results = len(cp['results'])
mapped = sum(1 for r in cp['results'] if r.get('has_mapping'))
print(f'Done: {done}/36481, Results: {results}, Mapped: {mapped}')
