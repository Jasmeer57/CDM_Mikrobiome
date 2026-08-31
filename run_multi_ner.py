"""
Multi-NER corpus runner: GLiNER + PubMedBERT + PubTator 3
Runs all three NER sources on the 422-paper corpus and saves per-paper results
in the same format as _spacy_runs/*.spacy_ner.csv:
    term, labels, model, paper, char_start, char_end
"""
import sys, io, os, csv, json, time, gc, warnings, re
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

import argparse
from pathlib import Path
from collections import Counter, defaultdict

REPO_ROOT = Path(__file__).resolve().parent
PAPERS_DIR = REPO_ROOT / "papers_txt"
OUTPUT_DIR = REPO_ROOT / "paper_claims" / "_multi_ner_runs"

# 14 CDM entity types
CDM_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS",
    "SAMPLE_METHOD", "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
]


# ────────────────── GLiNER ──────────────────
def run_gliner(papers, threshold=0.5, chunk_size=2000):
    import torch
    from gliner import GLiNER

    print("\n[GLiNER] Loading model...")
    model = GLiNER.from_pretrained("urchade/gliner_medium")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    print("[GLiNER] Device:", device)

    all_results = []  # list of (term, label, model, paper, start, end)
    t0 = time.time()

    for idx, paper_file in enumerate(papers):
        path = PAPERS_DIR / paper_file
        text = path.read_text(encoding="utf-8", errors="replace")

        chunks = [(i, text[i:i+chunk_size]) for i in range(0, len(text), chunk_size)]
        for chunk_idx, chunk_text in chunks:
            try:
                entities = model.predict_entities(chunk_text, CDM_TYPES, threshold=threshold)
                for e in entities:
                    all_results.append((
                        e["text"].strip(),
                        e["label"],
                        "gliner_medium",
                        paper_file,
                        chunk_idx * chunk_size + e.get("start", 0),
                        chunk_idx * chunk_size + e.get("end", 0),
                    ))
            except Exception:
                pass

        if (idx + 1) % 50 == 0 or idx == len(papers) - 1:
            print("  [GLiNER] %d/%d papers done (%.1fs)" % (idx + 1, len(papers), time.time() - t0))

    elapsed = time.time() - t0
    print("[GLiNER] Done: %d entities from %d papers in %.1fs" % (
        len(all_results), len(papers), elapsed))
    return all_results, elapsed


# ────────────────── PubMedBERT ──────────────────
# Use a PubMedBERT-based NER model fine-tuned on BC5CDR (disease+chemical)
# and another for gene/protein. We use the NCBI models from HuggingFace.

PUBMEDBERT_MODELS = [
    # (model_id, label_prefix, types)
    ("dmis-lab/biobert-v1.1", "biobert"),  # fallback if no PubMedBERT NER
]

def run_pubmedbert(papers, chunk_size=1500):
    """Run biomedical NER via HuggingFace token classification pipeline.

    Uses alvaroalon2/biobert_diseases_ner (BioBERT fine-tuned on NCBI Disease).
    Disease-only, high precision. Uses spaCy sentencizer for proper splitting.
    """
    from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline
    import torch

    model_name = "alvaroalon2/biobert_diseases_ner"
    print("\n[PubMedBERT] Loading %s ..." % model_name)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForTokenClassification.from_pretrained(model_name)
    device_num = 0 if torch.cuda.is_available() else -1

    nlp_pipe = pipeline("ner", model=model, tokenizer=tokenizer,
                   aggregation_strategy="simple", device=device_num)

    # Use spacy for sentence splitting (already installed)
    import spacy
    try:
        nlp_spacy = spacy.load("en_core_sci_sm", disable=["ner", "tagger", "lemmatizer"])
    except Exception:
        nlp_spacy = spacy.blank("en")
        nlp_spacy.add_pipe("sentencizer")

    all_results = []
    t0 = time.time()

    for idx, paper_file in enumerate(papers):
        path = PAPERS_DIR / paper_file
        text = path.read_text(encoding="utf-8", errors="replace")

        # Sentence splitting via spaCy
        doc = nlp_spacy(text[:100000])  # cap at 100k chars
        sentences = [sent.text.strip() for sent in doc.sents if len(sent.text.strip()) > 5]

        for sent_idx, sent in enumerate(sentences):
            # Skip overly long sentences (model has 512 token limit)
            if len(sent) > 400:
                # Split further on semicolons/commas
                parts = re.split(r'[;]', sent)
                for p in parts:
                    p = p.strip()
                    if len(p) > 200:
                        # Force split
                        for i in range(0, len(p), 200):
                            s = p[i:i+200].strip()
                            if len(s) > 5:
                                _run_pubmedbert_sent(nlp_pipe, s, paper_file, all_results)
                    elif len(p) > 5:
                        _run_pubmedbert_sent(nlp_pipe, p, paper_file, all_results)
            else:
                _run_pubmedbert_sent(nlp_pipe, sent, paper_file, all_results)

        if (idx + 1) % 25 == 0 or idx == len(papers) - 1:
            print("  [PubMedBERT] %d/%d papers done (%.1fs)" % (idx + 1, len(papers), time.time() - t0))

    elapsed = time.time() - t0
    print("[PubMedBERT] Done: %d entities from %d papers in %.1fs" % (
        len(all_results), len(papers), elapsed))
    return all_results, elapsed


def _run_pubmedbert_sent(nlp_pipe, sent, paper_file, all_results):
    """Run BioBERT NER on a single sentence and append results."""
    try:
        ner_results = nlp_pipe(sent)
        for ent in ner_results:
            term = ent["word"].strip()
            if term.startswith("##") or len(term) < 2:
                continue
            cdm_label = map_pubmedbert_label(ent["entity_group"])
            all_results.append((
                term,
                cdm_label,
                "biobert_diseases",
                paper_file,
                ent["start"],
                ent["end"],
            ))
    except Exception:
        pass


def map_pubmedbert_label(raw_label):
    """Map BioBERT disease NER label to CDM type."""
    rl = raw_label.upper()
    rl = re.sub(r'^[BI]-', '', rl)
    mapping = {
        "DISEASE": "DISEASE",
        "DISEASE_DISORDER": "DISEASE",
        "DISEASES_DISORDERS": "DISEASE",
    }
    return mapping.get(rl, "DISEASE")


# ────────────────── PubTator 3 ──────────────────

def run_pubtator(papers, api_key=None, batch_size=200):
    """Run PubTator 3 API on papers.

    PubTator annotates PubMed abstracts/full text by PMID.
    Since our papers are PRJ-accession-named txt files (not PMIDs),
    we need to extract the PMID from the text or use the title-based search.

    Strategy: Extract title from first line of each paper, search PubTator
    by title to get PMID, then fetch annotations.
    """
    import requests
    import time as _time

    BASE = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
    SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    print("\n[PubTator] Running via NCBI E-utilities + PubTator3 API ...")

    all_results = []
    found_count = 0
    t0 = time.time()

    session = requests.Session()
    if api_key:
        session.params["api_key"] = api_key

    for idx, paper_file in enumerate(papers):
        path = PAPERS_DIR / paper_file
        text = path.read_text(encoding="utf-8", errors="replace")

        # Extract title from first ~2000 chars
        lines = [l.strip() for l in text[:2000].split("\n") if l.strip()]
        title = None
        junk_titles = {
            "research article", "nature communications", "science",
            "plos one", "frontiers", "frontiers in", "pnas",
            "proceedings of the national academy of sciences",
        }
        for line in lines:
            # Skip accession-like lines and very short ones
            if line.startswith("PRJ") or len(line) < 10:
                continue
            # Skip journal names / section headers
            low = line.lower().strip()
            if low in junk_titles:
                continue
            # Skip lines that look like journal/volume info (e.g. "Food Research International 144 (2021) 110326")
            if re.search(r'\d{4}\s*\(\d{4}\)\s*\d', line):
                continue
            # Skip lines that are just a date or page range
            if re.match(r'^\d{4}$', line.strip()):
                continue
            title = line
            break

        if not title:
            continue

        # Search for PMID by title
        try:
            params = {
                "db": "pubmed",
                "term": title[:200],
                "retmode": "json",
                "retmax": 1,
            }
            resp = session.get(SEARCH_URL, params=params, timeout=15)
            data = resp.json()
            id_list = data.get("esearchresult", {}).get("idlist", [])
            if not id_list:
                continue
            pmid = id_list[0]
        except Exception:
            continue

        # Fetch PubTator annotations (biocjson format)
        try:
            pubtator_url = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
            resp = session.post(pubtator_url, json={"pmids": [pmid]}, timeout=30)
            if resp.status_code != 200:
                continue
            data = resp.json()
            docs = data.get("PubTator3", [])
            for doc in docs:
                for passage in doc.get("passages", []):
                    for ent in passage.get("annotations", []):
                        infons = ent.get("infons", {})
                        raw_type = infons.get("type", "").upper()
                        cdm_label = map_pubtator_label(raw_type)
                        ent_text = ent.get("text", "").strip()
                        if not ent_text:
                            continue
                        all_results.append((
                            ent_text,
                            cdm_label,
                            "pubtator3",
                            paper_file,
                            0, 0,
                        ))
                        found_count += 1
        except Exception:
            pass

        if (idx + 1) % 25 == 0 or idx == len(papers) - 1:
            elapsed = time.time() - t0
            print("  [PubTator] %d/%d papers (%d found, %.1fs)" % (
                idx + 1, len(papers), found_count, elapsed))
        # Rate limit: 10 req/s with API key, 3/s without
        _time.sleep(0.12)

    elapsed = time.time() - t0
    print("[PubTator] Done: %d entities from %d papers in %.1fs" % (
        len(all_results), len(papers), elapsed))
    return all_results, elapsed


def map_pubtator_label(raw_type):
    """Map PubTator type to CDM type."""
    rt = raw_type.upper()
    mapping = {
        "DISEASE": "DISEASE",
        "CHEMICAL": "CHEMICAL",
        "GENE": "PROTEIN",
        "GENE_GENE": "PROTEIN",
        "PROTEIN": "PROTEIN",
        "SPECIES": "ORGANISM",
        "TAXON": "ORGANISM",
        "ORGANISM": "ORGANISM",
        "CELLLINE": "CELL_TYPE",
        "CELL_LINE": "CELL_TYPE",
        "CELL_TYPE": "CELL_TYPE",
        "DNA": "DNA_RNA",
        "RNA": "DNA_RNA",
        "MUTATION": "GENOMICS",
        "VARIANT": "GENOMICS",
    }
    return mapping.get(rt, rt if rt in CDM_TYPES else "ENTITY")


# ────────────────── Save & summarize ──────────────────

def save_csv(results, output_path):
    """Save results in the same format as _spacy_runs/*.spacy_ner.csv"""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["term", "labels", "model", "paper", "char_start", "char_end"])
        for row in results:
            writer.writerow(row)
    print("Saved %d rows to %s" % (len(results), output_path))


def save_summary(all_results, elapsed_times, output_dir):
    """Save a summary JSON with per-model stats."""
    summary = {
        "total_papers": len(set(r[3] for r in all_results)),
        "total_entities": len(all_results),
        "models": {},
    }
    for model_name in set(r[2] for r in all_results):
        model_rows = [r for r in all_results if r[2] == model_name]
        labels = Counter(r[1] for r in model_rows)
        unique = set(r[0].lower() for r in model_rows)
        summary["models"][model_name] = {
            "total_entities": len(model_rows),
            "unique_entities": len(unique),
            "types_covered": len(labels),
            "types": dict(labels.most_common()),
            "elapsed_seconds": elapsed_times.get(model_name, 0),
        }

    summary_path = output_dir / "_multi_ner_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("\nSummary saved to", summary_path)
    print(json.dumps(summary, indent=2))


def save_csv_dict(rows, output_path):
    """Save list-of-dicts to CSV, preserving column order."""
    if not rows:
        print("No rows to save for", output_path)
        return
    fields = ["term", "labels", "model", "paper", "char_start", "char_end"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print("Saved %d rows to %s" % (len(rows), output_path))


def save_summary_rows(all_rows, elapsed_times, output_dir):
    """Save summary JSON from list-of-dicts (merged combined CSV rows)."""
    summary = {
        "total_papers": len(set(r["paper"] for r in all_rows)),
        "total_entities": len(all_rows),
        "models": {},
    }
    for model_name in set(r["model"] for r in all_rows):
        model_rows = [r for r in all_rows if r["model"] == model_name]
        labels = Counter(r["labels"] for r in model_rows)
        unique = set(r["term"].lower() for r in model_rows)
        summary["models"][model_name] = {
            "total_entities": len(model_rows),
            "unique_entities": len(unique),
            "types_covered": len(labels),
            "types": dict(labels.most_common()),
            "elapsed_seconds": elapsed_times.get(model_name, 0),
        }

    summary_path = output_dir / "_multi_ner_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("\nSummary saved to", summary_path)
    print(json.dumps(summary, indent=2))


# ────────────────── Main ──────────────────

def main():
    parser = argparse.ArgumentParser(description="Run multi-NER on corpus")
    parser.add_argument("--models", nargs="+", default=["gliner", "pubmedbert", "pubtator"],
                        choices=["gliner", "pubmedbert", "pubtator", "all"],
                        help="Which NER models to run")
    parser.add_argument("--max_files", type=int, default=500, help="Max papers to process")
    parser.add_argument("--incremental", action="store_true",
                        help="Skip papers already in the output CSV (append mode)")
    parser.add_argument("--threshold", type=float, default=0.5, help="GLiNER threshold")
    parser.add_argument("--api_key", default=os.environ.get("ENTREZ_API_KEY", ""),
                        help="NCBI Entrez API key for PubTator")
    args = parser.parse_args()

    if "all" in args.models:
        args.models = ["gliner", "pubmedbert", "pubtator"]

    # Get paper list
    all_papers = sorted([f.name for f in PAPERS_DIR.glob("*.txt")])[:args.max_files]
    print("Found %d papers in %s" % (len(all_papers), PAPERS_DIR))

    # Incremental mode: skip papers already in existing output CSVs
    # Only check the CSVs for the models being run
    if args.incremental:
        model_csv_map = {"gliner": "gliner_ner.csv", "pubmedbert": "pubmedbert_ner.csv", "pubtator": "pubtator3_ner.csv"}
        done = set()
        for model_name in args.models:
            csv_name = model_csv_map.get(model_name, "")
            if not csv_name:
                continue
            csv_path = OUTPUT_DIR / csv_name
            if csv_path.exists():
                with open(csv_path, encoding="utf-8", errors="replace") as f:
                    content = f.read().replace("\x00", "")
                    done.update(r["paper"] for r in csv.DictReader(io.StringIO(content)))
        papers = [p for p in all_papers if p not in done]
        print("Incremental: %d already done across selected models, %d remaining" % (len(done), len(papers)))
    else:
        papers = all_papers

    if not papers:
        print("Nothing to do — all papers already processed.")
        return

    print("Running models:", args.models, "on %d papers" % len(papers))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []
    elapsed_times = {}

    # Load existing results for merge when incremental
    existing_results = {"gliner": [], "pubmedbert": [], "pubtator": []}
    if args.incremental:
        for model_key, csv_name in [("gliner", "gliner_ner.csv"),
                                     ("pubmedbert", "pubmedbert_ner.csv"),
                                     ("pubtator", "pubtator3_ner.csv")]:
            csv_path = OUTPUT_DIR / csv_name
            if csv_path.exists():
                with open(csv_path, encoding="utf-8", errors="replace") as f:
                    content = f.read().replace("\x00", "")
                    existing_results[model_key] = list(csv.DictReader(io.StringIO(content)))
                print("  Loaded %d existing rows from %s" % (len(existing_results[model_key]), csv_name))

    if "gliner" in args.models:
        results, elapsed = run_gliner(papers, threshold=args.threshold)
        merged = existing_results["gliner"] + [dict(zip(["term","labels","model","paper","char_start","char_end"], r)) for r in results]
        save_csv_dict(merged, OUTPUT_DIR / "gliner_ner.csv")
        all_results.extend(results)
        elapsed_times["gliner_medium"] = elapsed
        del results; gc.collect()

    if "pubmedbert" in args.models:
        results, elapsed = run_pubmedbert(papers)
        merged = existing_results["pubmedbert"] + [dict(zip(["term","labels","model","paper","char_start","char_end"], r)) for r in results]
        save_csv_dict(merged, OUTPUT_DIR / "pubmedbert_ner.csv")
        all_results.extend(results)
        elapsed_times["pubmedbert_ner_all"] = elapsed
        del results; gc.collect()

    if "pubtator" in args.models:
        results, elapsed = run_pubtator(papers, api_key=args.api_key)
        merged = existing_results["pubtator"] + [dict(zip(["term","labels","model","paper","char_start","char_end"], r)) for r in results]
        save_csv_dict(merged, OUTPUT_DIR / "pubtator3_ner.csv")
        all_results.extend(results)
        elapsed_times["pubtator3"] = elapsed
        del results; gc.collect()

    # Combined CSV (all models, all papers)
    combined = []
    for csv_name in ["gliner_ner.csv", "pubmedbert_ner.csv", "pubtator3_ner.csv"]:
        csv_path = OUTPUT_DIR / csv_name
        if csv_path.exists():
            with open(csv_path, encoding="utf-8", errors="replace") as f:
                content = f.read().replace("\x00", "")
                combined.extend(csv.DictReader(io.StringIO(content)))
    save_csv_dict(combined, OUTPUT_DIR / "all_ner_combined.csv")
    save_summary_rows(combined, elapsed_times, OUTPUT_DIR)


if __name__ == "__main__":
    main()
