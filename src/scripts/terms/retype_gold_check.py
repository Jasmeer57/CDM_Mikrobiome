"""Gold check of the re-typing prompts before a full run (run inside retype_v2.sbatch, TASK=check).

    python src/scripts/terms/retype_gold_check.py --port P [--model M]

Entities: 20 real CDM terms with an unambiguous expected type (term, variants, definition and corpus sentences exactly as
the full run sees them). Triples: 12 invented sentences (no paper text) whose relation is unambiguous under the rules.
Prints every miss and writes outputs/results/entity_retype_2026-11-10/GOLD_CHECK.json. Not an accuracy estimate: it
only shows that the prompt, schema and parsing give the intended answers on clear cases. Written with Claude Code (declare).
"""
import argparse, json, sqlite3, sys
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/terms")); sys.path.insert(0, str(ROOT / "src/scripts/definitions")); sys.path.insert(0, str(ROOT / "src/scripts/triples"))
import retype_entity_terms as R, generate_term_definitions as G, retype_triples_v2 as T
from repair_triples import GLOSS
from retype_generic_triples import GENERIC
ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--model", default="cyankiwi/Qwen3.5-9B-AWQ-4bit")
ap.add_argument("--db303", default=str(ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db")); a = ap.parse_args()
port, MODEL = a.port, a.model
gold = {"Antilipemic agent": "CHEMICAL", "double-stranded DNA virus": "ORGANISM", "Bacteroides": "ORGANISM", "women": "POPULATION_OR_HOST_GROUP",
        "China": "GEOGRAPHY", "months": "MEASURE_OR_UNIT", "analyzed": "NOT_A_CONCEPT", "Qiagen": "LAB_METHOD", "Ruminococcaceae": "ORGANISM",
        "informed consent": "NOT_A_CONCEPT", "Healthy Subjects": "POPULATION_OR_HOST_GROUP", "concentration": "MEASURE_OR_UNIT",
        "stump": "ANATOMY_OR_BODY_SITE", "FDR values": "DATA_ANALYSIS", "Stool culture": "LAB_METHOD", "authors": "NOT_A_CONCEPT",
        "Sardinia": "GEOGRAPHY", "glycan fermentation": "PATHWAY", "vaccinated": "CLINICAL", "LEfSe": "DATA_ANALYSIS"}
c310 = sqlite3.connect(f"file:{ROOT}/releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db?mode=ro", uri=True)
c303 = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True)
rows = []
for t in gold:
    r = c310.execute("SELECT term_id, term, variants, definition FROM term_curation WHERE term=? ORDER BY kept DESC LIMIT 1", (t,)).fetchone()
    rows.append(r or (None, t, "", ""))
items = [[n, t, [v for v in (var or "").split("|") if v and v != t][:4], (d or "")[:300],
          [x[2] for x in (G.contexts(c303, tid) if tid else [])]] for n, (tid, t, var, d) in enumerate(rows)]
item = {"type": "object", "additionalProperties": False, "required": ["n", "type", "basis"],
        "properties": {"n": {"type": "integer"}, "type": {"type": "string", "enum": list(R.TYPES)}, "basis": {"type": "string", "enum": ["CONTEXT", "NAME_ONLY"]}}}
schema = {"type": "object", "additionalProperties": False, "required": ["r"], "properties": {"r": {"type": "array", "items": item}}}
prompt = R.PROMPT.format(types="\n".join(f"  {k}: {v}" for k, v in R.TYPES.items()))
got = {}
for i in range(0, len(items), R.BATCH):
    b = [[k] + x[1:] for k, x in enumerate(items[i:i + R.BATCH])]
    p = R.chat(port, MODEL, prompt + "\n\nItems:\n" + json.dumps(b, ensure_ascii=False), R.sized(schema, len(b)), 1500)
    for r in p["r"]:
        got[i + r["n"]] = r["type"]
ok = 0
res = {"entities": [], "triples": []}
for n, t in enumerate(gold):
    hit = got.get(n) == gold[t]; ok += hit
    res["entities"].append({"term": t, "expected": gold[t], "got": got.get(n), "ok": hit})
    print(("OK  " if hit else "MISS"), f"{t:28s} expected {gold[t]:24s} got {got.get(n)}  (ctx {len(items[n][4])})")
print(f"entities: {ok}/{len(gold)} correct")


# ---- triples: invented sentences
TG = [("Akkermansia", "ORGANISM", "obese patients", "DISEASE", "Akkermansia was significantly depleted in obese patients compared with lean controls.", "DECREASED_IN"),
      ("fibre supplementation", "CHEMICAL", "Bifidobacterium", "ORGANISM", "Fibre supplementation increased the abundance of Bifidobacterium.", "PROMOTES"),
      ("Prevotella", "ORGANISM", "fasting glucose", "CLINICAL", "Prevotella abundance was positively correlated with fasting glucose.", "POSITIVELY_ASSOCIATED_WITH"),
      ("Bacteroides", "ORGANISM", "BMI", "CLINICAL", "Bacteroides was inversely correlated with BMI.", "NEGATIVELY_ASSOCIATED_WITH"),
      ("Blautia", "ORGANISM", "depression", "DISEASE", "Blautia was associated with depression.", "ASSOCIATION_UNSIGNED"),
      ("Shannon diversity", "GENOMICS", "smokers", "CLINICAL", "Shannon diversity did not differ between smokers and non-smokers.", "NULL_FINDING"),
      ("Lactobacillus", "ORGANISM", "DNA extraction", "LAB_METHOD", "Lactobacillus strains were cultured on MRS agar; DNA was extracted from stool with a commercial kit.", "NOT_SUPPORTED"),
      ("diet", "CHEMICAL", "gut microbiota", "ORGANISM", "Diet affects the gut microbiota.", "MODULATES"),
      ("Bifidobacterium", "ORGANISM", "age", "CLINICAL", "Bifidobacterium decreased with age during the first two years of life.", "DECREASES_OVER_TIME"),
      ("Ruminococcus", "ORGANISM", "IBS subtypes", "DISEASE", "Ruminococcus abundance differed between IBS subtypes.", "DIFFERENTIALLY_ABUNDANT_IN"),
      ("Faecalibacterium prausnitzii", "ORGANISM", "butyrate", "CHEMICAL", "Faecalibacterium prausnitzii produces butyrate.", "PRODUCES"),
      ("Fusobacterium nucleatum", "ORGANISM", "colorectal cancer", "DISEASE", "Fusobacterium nucleatum was enriched in colorectal cancer tissue.", "INCREASED_IN"),
      ("healthy group", "CLINICAL", "Bifidobacterium", "ORGANISM", "Bifidobacterium was significantly higher in the healthy group than in patients.", "INCREASED_IN|REVERSED"),
      ("breast milk", "CHEMICAL", "infants", "CLINICAL", "Many experts advocate that breast milk is the best food for infants.", "NOT_SUPPORTED"),
      ("probiotic supplementation", "CHEMICAL", "body weight", "CLINICAL", "Six months of probiotic supplementation resulted in significant weight reduction.", "SUPPRESSES"),
      ("paired samples", "SAMPLE_METHOD", "unpaired samples", "SAMPLE_METHOD", "Paired samples from the same patient were more similar to each other than unpaired samples.", "COMPARED_WITH"),
      ("treatment", "CLINICAL", "randomization", "STUDY_DESIGN", "The use of antibiotics before stool collection did not interfere with randomization.", "NULL_FINDING")]
c303b = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True)
specific = sorted(r for (r,) in c303b.execute("SELECT DISTINCT relation_normalized FROM relation") if r not in GENERIC)
labels = specific + [k for k in T.NEW if k not in specific] + T.EXITS
gl = {**GLOSS, **T.NEW}
tprompt = T.PROMPT.format(glossary="\n".join(f"  {k}: {v}" for k, v in gl.items() if k in labels), allowed=", ".join(labels))
tschema = T.make_schema(labels)
tg = {}
for i in range(0, len(TG), T.BATCH):
    b = [[k, s, st, o, ot, [sent]] for k, (s, st, o, ot, sent, _) in enumerate(TG[i:i + T.BATCH])]
    p = R.chat(port, MODEL, tprompt + "\n\nItems:\n" + json.dumps(b, ensure_ascii=False), R.sized(tschema, len(b)), 2000)
    for r in p["r"]:
        tg[i + r["n"]] = r
tok = 0
for n, (s, _, o, _, sent, exp) in enumerate(TG):
    r = tg.get(n, {}); er, _, ed = exp.partition("|")
    hit = r.get("relation") == er and (not ed or r.get("direction") == ed); tok += hit
    res["triples"].append({"sentence": sent, "expected": exp, "got": r.get("relation"), "cue": r.get("cue"), "ok": hit})
    print(("OK  " if hit else "MISS"), f"{exp:28s} got {r.get('relation')}  cue={r.get('cue')!r}")
print(f"triples: {tok}/{len(TG)} correct")
res["summary"] = {"entities_correct": ok, "entities": len(gold), "triples_correct": tok, "triples": len(TG), "model": MODEL,
                  "entity_prompt": R.PV, "triple_prompt": T.PV}
out = ROOT / "outputs/results/entity_retype_2026-11-10/GOLD_CHECK.json"; out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(res, indent=1) + "\n")
