import json, re
d = json.load(open(r'C:\Users\jkalra\Documents\Microbiome-CDM\bioproject_data_export.json', 'r', encoding='utf-8'))
bps = d['bioprojects']
for bp in bps[:15]:
    pid = bp['bioproject_id']
    sid = str(bp.get('study_id', ''))
    print(f'{pid:15s} | study_id={sid[:70]}')
print()
for bp in bps:
    if bp.get('journal'):
        pid = bp['bioproject_id']
        print(f'JOURNAL: {pid:15s} | journal={bp["journal"]}')
# Check publication_info formats
print()
fmt_counts = {}
for bp in bps:
    pi = bp.get('publication_info')
    if not pi:
        continue
    if pi.startswith('Journal:'):
        fmt_counts['keyvalue'] = fmt_counts.get('keyvalue', 0) + 1
    else:
        fmt_counts['comma'] = fmt_counts.get('comma', 0) + 1
print('publication_info formats:', fmt_counts)
