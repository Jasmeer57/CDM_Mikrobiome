#!/usr/bin/env python3
"""Restartable HPC corpus builder for general human-microbiome full-text papers.

Pass 1: CPU-parallel TXT/PDF ingestion, metadata heuristics, topic classification,
section indexing, OCR-needed flags, JSON records and CSV/JSONL manifests.
Pass 2 (optional): local vLLM enrichment of sampled article sections into a strict schema.
The script does not OCR scanned PDFs and does not claim rule-based labels are validated.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, logging, os, re, time, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
try:
    import pymupdf
except ImportError:
    try: import fitz as pymupdf
    except ImportError: pymupdf = None

VERSION = "1.0.0"
TOPICS = [
    "gut_intestinal_microbiome", "oral_microbiome", "skin_microbiome", "vaginal_urogenital_microbiome",
    "respiratory_microbiome", "other_body_sites", "multi_body_site_studies", "microbiome_methods_technology",
    "metagenomics_metatranscriptomics", "metabolomics_multiomics", "microbial_ecology_diversity",
    "host_microbe_interactions_immunology", "microbiome_disease_associations", "infectious_disease_pathogens",
    "diet_nutrition_lifestyle", "medications_antibiotics", "probiotics_prebiotics_synbiotics",
    "fecal_microbiota_transplantation", "pregnancy_early_life", "aging", "cancer_oncology",
    "metabolic_disease", "neurology_mental_health", "cardiovascular_disease", "allergy_autoimmune_inflammation",
    "biomarkers_diagnostics", "epidemiology_population_cohorts", "clinical_trials_interventions",
    "systematic_reviews_meta_analyses", "basic_science_cell_biology", "bioinformatics_statistics", "other"
]
TOPIC_PATTERNS = {
 "gut_intestinal_microbiome": [r"gut microbiom", r"intestinal microbiot", r"faecal microbiot", r"fecal microbiot", r"stool microbiom", r"colon microbiot", r"ileal microbiot"],
 "oral_microbiome": [r"oral microbiom", r"salivary microbiot", r"dental plaque", r"subgingival microbiot", r"tongue microbiot"],
 "skin_microbiome": [r"skin microbiom", r"cutaneous microbiot", r"skin microbial communit"],
 "vaginal_urogenital_microbiome": [r"vaginal microbiot", r"urogenital microbiom", r"urinary microbiom", r"bladder microbiot", r"cervicovaginal"],
 "respiratory_microbiome": [r"lung microbiom", r"airway microbiot", r"respiratory microbiom", r"nasal microbiot", r"pulmonary microbiot"],
 "other_body_sites": [r"breast milk microbiot", r"placental microbiom", r"conjunctival microbiot", r"ear microbiom"],
 "multi_body_site_studies": [r"multiple body sites", r"across body sites", r"body-site microbiom", r"body site-specific"],
 "microbiome_methods_technology": [r"16s rrna", r"amplicon sequencing", r"microbiome profiling", r"microbial community profiling", r"shotgun sequencing"],
 "metagenomics_metatranscriptomics": [r"metagenom", r"metatranscriptom", r"metagenomic sequencing", r"shotgun metagenom"],
 "metabolomics_multiomics": [r"metabolom", r"multi-omics", r"multiomics", r"metabolite profiling", r"metaproteom"],
 "microbial_ecology_diversity": [r"alpha diversity", r"beta diversity", r"microbial ecology", r"community composition", r"dysbiosis", r"shannon index", r"bray.?curtis"],
 "host_microbe_interactions_immunology": [r"host.?microbe interaction", r"microbiota.?immune", r"immune modulation", r"host-microbial", r"microbial metabolites.*immune"],
 "microbiome_disease_associations": [r"microbiome.*disease", r"microbiota.*disease", r"microbiome-associated", r"microbial signature", r"disease-associated microbiota"],
 "infectious_disease_pathogens": [r"pathogen", r"colonization resistance", r"infection microbiome", r"pathobiont", r"antimicrobial resistance"],
 "diet_nutrition_lifestyle": [r"dietary fiber", r"dietary fibre", r"diet.*microbiom", r"nutrition.*microbiot", r"food intake", r"lifestyle.*microbiome"],
 "medications_antibiotics": [r"antibiotic.*microbiom", r"medication.*microbiom", r"drug-induced microbiome", r"proton pump inhibitor", r"metformin.*microbi"],
 "probiotics_prebiotics_synbiotics": [r"probiotic", r"prebiotic", r"synbiotic", r"live biotherapeutic"],
 "fecal_microbiota_transplantation": [r"fecal microbiota transplantation", r"faecal microbiota transplantation", r"\bfmt\b", r"microbiota transplant"],
 "pregnancy_early_life": [r"infant microbiom", r"neonatal microbiot", r"maternal microbiom", r"pregnancy.*microbiom", r"early-life microbiome", r"breastfeeding microbiot"],
 "aging": [r"aging microbiom", r"ageing microbiom", r"older adults.*microbiot", r"elderly.*microbiom"],
 "cancer_oncology": [r"cancer microbiom", r"tumor microbiot", r"tumour microbiot", r"oncology.*microbiome", r"colorectal cancer.*microbiot"],
 "metabolic_disease": [r"obesity.*microbiom", r"diabetes.*microbiom", r"metabolic syndrome.*microbiot", r"insulin resistance.*microbi"],
 "neurology_mental_health": [r"gut.?brain axis", r"neuropsychiatric.*microbiom", r"depression.*microbiot", r"parkinson.*microbiom", r"alzheimer.*microbiot"],
 "cardiovascular_disease": [r"cardiovascular.*microbiom", r"atherosclerosis.*microbiot", r"hypertension.*microbiom"],
 "allergy_autoimmune_inflammation": [r"allergy.*microbiom", r"autoimmune.*microbiot", r"inflammatory.*microbiom", r"asthma.*microbiom", r"rheumatoid arthritis.*microbiot"],
 "biomarkers_diagnostics": [r"microbiome biomarker", r"diagnostic biomarker", r"predictive signature", r"diagnostic accuracy"],
 "epidemiology_population_cohorts": [r"population-based", r"population cohort", r"prospective cohort", r"epidemiolog", r"birth cohort"],
 "clinical_trials_interventions": [r"randomized controlled trial", r"randomised controlled trial", r"clinical trial", r"placebo-controlled", r"intervention study"],
 "systematic_reviews_meta_analyses": [r"systematic review", r"meta-analysis", r"scoping review", r"narrative review", r"this review"],
 "basic_science_cell_biology": [r"organoid", r"in vitro", r"cell signaling", r"epithelial cell", r"co-culture"],
 "bioinformatics_statistics": [r"bioinformatics pipeline", r"differential abundance", r"machine learning", r"compositional data", r"qiime", r"dada2", r"kraken2", r"humann"],
}
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
PMID_RE = re.compile(r"\bPMID\s*:\s*(\d{5,9})\b", re.I)
PMCID_RE = re.compile(r"\bPMCID\s*:\s*(PMC\d+)\b|\b(PMC\d{4,})\b", re.I)
YEAR_RE = re.compile(r"\b(?:19[89]\d|20[0-3]\d)\b")
SECTION_ALIASES = {
 "Abstract": ["abstract", "summary"], "Introduction": ["introduction", "background", "rationale"],
 "Methods": ["methods", "materials and methods", "methods and materials", "patients and methods", "methodology", "experimental procedures", "study design"],
 "Results": ["results", "findings"], "Discussion": ["discussion", "general discussion"],
 "Conclusion": ["conclusion", "conclusions", "concluding remarks"], "References": ["references", "bibliography", "literature cited"]
}

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def read_text(p: Path) -> str:
    b=p.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try: return b.decode(enc)
        except UnicodeDecodeError: pass
    return b.decode("utf-8", errors="replace")
def norm(s: str) -> str:
    s=s.replace("\r\n","\n").replace("\r","\n").replace("\x00"," ")
    s=re.sub(r"[ \t]+\n","\n",s); s=re.sub(r"\n{4,}","\n\n\n",s)
    return s.strip()+"\n"
def atomic_text(p: Path, s: str):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+f".tmp.{os.getpid()}")
    with t.open("w",encoding="utf-8",errors="replace") as f: f.write(s); f.flush(); os.fsync(f.fileno())
    os.replace(t,p)
def atomic_json(p: Path, obj: Any):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+f".tmp.{os.getpid()}")
    with t.open("w",encoding="utf-8") as f: json.dump(obj,f,ensure_ascii=False,separators=(",",":")); f.write("\n"); f.flush(); os.fsync(f.fileno())
    os.replace(t,p)
def topic_folder(rel: str) -> str:
    return Path(rel).parts[0] if len(Path(rel).parts)>1 else "uncategorized"
def paper_id(rel: str) -> str: return "HMP_"+hashlib.sha1(rel.encode("utf-8",errors="replace")).hexdigest()[:12].upper()
def outpaths(out: Path, pid: str):
    shard=pid[-3:-1]; return out/"records"/shard/f"{pid}.json", out/"full_text"/shard/f"{pid}.txt"
def discover(root: Path):
    pdfs=sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower()==".pdf")
    txts=sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower()==".txt")
    bykey={(p.parent,p.stem.casefold()):p for p in txts}; matched=set(); jobs=[]
    for p in pdfs:
        rel=p.relative_to(root).as_posix(); t=bykey.get((p.parent,p.stem.casefold()))
        if t: matched.add(t)
        jobs.append({"root":str(root),"pdf":str(p),"txt":str(t) if t else None,"rel":rel,"category":topic_folder(rel),"id":paper_id(rel)})
    for p in txts:
        if p in matched: continue
        rel=p.relative_to(root).as_posix(); jobs.append({"root":str(root),"pdf":None,"txt":str(p),"rel":rel,"category":topic_folder(rel),"id":paper_id(rel)})
    jobs.sort(key=lambda x:x["rel"].casefold()); return jobs

def pdf_text(p: Path):
    if pymupdf is None: raise RuntimeError("PyMuPDF not installed; install requirements-base.txt")
    with pymupdf.open(str(p)) as doc:
        pages=len(doc); title=(doc.metadata or {}).get("title") or None; chunks=[]
        for page in doc:
            try: txt=page.get_text("text",sort=True)
            except Exception: txt=page.get_text()
            chunks.append(txt)
    return norm("\n\n\f\n\n".join(chunks)),pages,title

def extract_title(text, meta=None):
    if meta:
        x=re.sub(r"\s+"," ",meta).strip()
        if 8<=len(x)<=400 and sum(c.isalpha() for c in x)/max(1,len(x))>.45 and not x.lower().startswith(("untitled","microsoft word")) and not x.endswith((".","?","!")): return x,"pdf_metadata"
    first=text.split("\f",1)[0]; paras=[re.sub(r"\s+"," ",x).strip() for x in re.split(r"\n\s*\n",first)]
    rejects=("doi:","https://doi.org","copyright","all rights reserved","received ","accepted ","published online","abstract","keywords","corresponding author","published by")
    c=[]
    for i,x in enumerate(paras[:40]):
        w=x.split(); low=x.lower()
        if not 25<=len(x)<=250 or not 4<=len(w)<=30 or any(z in low for z in rejects): continue
        if "@" in x or x.count(",")>=3 or re.search(r"\b(university|department|hospital|faculty|institute|correspondence)\b",low): continue
        if x.endswith((".",";","?","!")) or re.search(r"\b(?:is a|are a|we investigated|we aimed|this study|the aim of)\b",low): continue
        if sum(ch.isalpha() for ch in x)/len(x)<.55: continue
        score=10+(2 if 45<=len(x)<=180 else 0)+(1 if 6<=len(w)<=22 else 0)-i*.1
        c.append((score,x))
    if c:return max(c)[1],"first_page_heuristic"
    for line in first.splitlines()[:60]:
        x=re.sub(r"\s+"," ",line).strip()
        if 30<=len(x)<=200 and len(x.split())>=5 and not any(z in x.lower() for z in rejects) and sum(ch.isalpha() for ch in x)/len(x)>.6:return x,"line_heuristic"
    return None,"not_extracted"
def abstract_text(text):
    m=re.search(r"(?im)^\s*(?:abstract|summary)\s*[:.]?\s*$",text[:100000])
    if m:
        start=m.end(); stop=re.search(r"(?im)^\s*(?:keywords?|key words|introduction|background|methods|materials and methods|results)\s*[:.]?\s*$",text[start:min(len(text),start+18000)])
        return re.sub(r"\s+"," ",text[start:start+stop.start() if stop else start+8000]).strip()[:6000] or None
    first=text.split("\f",1)[0]; intro=re.search(r"(?im)^\s*(?:\d+\.?\s+)?introduction\s*$",first[:30000]); kw=re.search(r"(?im)^\s*(?:keywords?|key words)\s*:",first[:30000])
    ends=[m.start() for m in (intro,kw) if m]; prefix=first[:min(ends)] if ends else first
    ps=[re.sub(r"\s+"," ",p).strip() for p in re.split(r"\n\s*\n",prefix)]
    ps=[p for p in ps if len(p)>250 and len(p.split())>35 and not any(x in p.lower() for x in ["corresponding author","published online","issn"])]
    return max(ps,key=len)[:6000] if ps else None
def identifiers(text):
    doi=DOI_RE.search(text[:12000]); pm=PMID_RE.search(text[:400000]); pc=PMCID_RE.search(text[:400000]); years=YEAR_RE.findall(text[:10000])
    return {"doi":doi.group(0).rstrip(".,;:)]}").lower() if doi else None,"pmid":pm.group(1) if pm else None,"pmcid":(pc.group(1) or pc.group(2)) if pc else None,"publication_year":int(years[0]) if years else None}
def sections(text):
    aliases={a.casefold():k for k,vals in SECTION_ALIASES.items() for a in vals}; found=[]
    for m in re.finditer(r"(?m)^([^\n]{2,100})\n",text):
        line=re.sub(r"\s+"," ",m.group(1)).strip(); n=re.sub(r"^(?:\d+(?:\.\d+)*[.)]?|[IVXLC]+[.)]?)\s+","",line,flags=re.I).casefold().rstrip(" .:")
        if n in aliases: found.append((m.start(),m.end(),aliases[n]))
        elif 3<=len(line)<=90 and len(line.split())<=12 and m.start()>1200 and not line.endswith((".",";",":","?","!")) and sum(c.isalpha() for c in line)/len(line)>.7 and not re.search(r"doi|journal|copyright|figure|table|university|department|abstract|keywords",line,re.I): found.append((m.start(),m.end(),line))
    seen=set(); compact=[]
    for a,b,h in found:
        if h in SECTION_ALIASES:
            if h in seen: continue
            seen.add(h)
        if compact and compact[-1][2].casefold()==h.casefold(): continue
        compact.append((a,b,h))
    out=[]
    for i,(a,b,h) in enumerate(compact): out.append({"section_id":f"SEC_{i+1:04d}","heading":h,"heading_path":[h],"order":i+1,"start_char":a,"end_char":compact[i+1][0] if i+1<len(compact) else len(text)})
    return out
def hit(text, pats): return any(re.search(p,text,re.I) for p in pats)
def classify(title, abstract, text, folder):
    focus=(title or "")+"\n"+(abstract or ""); ev=focus if len(focus.strip())>100 else text[:30000]
    topic_hits=[t for t,pats in TOPIC_PATTERNS.items() if hit(ev,pats)]
    # General relevance is based on explicit microbiome/microbiota language, not folder alone.
    micro=hit(ev,[r"microbiom",r"microbiota",r"microbial communit",r"16s rrna",r"metagenom",r"dysbiosis",r"human-associated microbi"])
    human=hit(ev,[r"human subjects?",r"patients?",r"participants?",r"healthy volunteers?",r"human stool",r"human fecal",r"human faecal",r"human saliva",r"human samples?",r"adults?",r"children",r"clinical cohort",r"human microbiome"])
    animal=hit(ev,[r"mice",r"mouse model",r"murine",r"rat model",r"zebrafish",r"animal model",r"in vitro",r"organoid"])
    if human and animal: evidence="mixed_human_animal_or_review"
    elif human: evidence="human_signal"
    elif animal: evidence="animal_or_in_vitro_signal"
    else: evidence="unclear"
    if hit(focus,[r"systematic review",r"meta-analysis",r"scoping review",r"narrative review",r"this review"]): stype="review"
    elif hit(focus,[r"randomized controlled trial",r"randomised controlled trial",r"clinical trial"]): stype="clinical_trial"
    elif hit(focus,[r"cohort study",r"case-control",r"cross-sectional study",r"prospective study",r"longitudinal study"]): stype="observational_human_candidate"
    else: stype="primary_research_or_other"
    folder_topic=folder if folder in TOPICS else None
    primary=[]
    if folder_topic: primary.append(folder_topic)
    for t in topic_hits:
        if t not in primary: primary.append(t)
    if not primary: primary=["other"]
    return {"microbiome_relevance":"yes" if micro else "unclear","human_evidence":evidence,"study_type":stype,"topic_labels":primary,"secondary_topics":[t for t in topic_hits if t not in primary],"inclusion_decision":"candidate_review" if micro else "uncertain_relevance","rule_based_confidence":"low_to_moderate","relevance_note":"Rule-based title/abstract classification; verify before treating as definitive."}
def process_one(job):
    root=Path(job["root"]); out=Path(job["out"]); pid=job["id"]; rp,tp=outpaths(out,pid); started=time.monotonic()
    pdf=Path(job["pdf"]) if job.get("pdf") else None; txt=Path(job["txt"]) if job.get("txt") else None; pages=None; meta=None; method="source_txt" if txt else "pymupdf"
    try:
        text=None
        if txt and txt.is_file():
            t=read_text(txt)
            if len(t.strip())>=300: text=t; clean=str(txt.resolve())
        if text is None and pdf and pdf.is_file():
            text,pages,meta=pdf_text(pdf); atomic_text(tp,text); clean=str(tp.resolve()); method="pymupdf"
        elif text is None and txt and txt.is_file():
            text=norm(read_text(txt)); atomic_text(tp,text); clean=str(tp.resolve()); method="source_txt_copied"
        if not text or not text.strip(): raise ValueError("No usable text found")
        title,title_method=extract_title(text,meta); abst=abstract_text(text); ids=identifiers(text); secs=sections(text)
        for s in secs: s["text_path"]=clean
        cls=classify(title,abst,text,job["category"]); low=len(text.strip())<500 or (pages and pages>2 and len(text.strip())/pages<100)
        rec={"paper_id":pid,"schema_version":VERSION,"publication":{"title":title,"title_extraction_method":title_method,"doi":ids["doi"],"pmid":ids["pmid"],"pmcid":ids["pmcid"],"authors":[],"journal":None,"publication_year":ids["publication_year"],"article_type":cls["study_type"],"language":None,"abstract":abst,"keywords":[],"source_url":None,"source_database":"local_file_corpus","license":None,"retrieved_at":None},
        "source":{"source_pdf":str(pdf.resolve()) if pdf else None,"source_txt":str(txt.resolve()) if txt else None,"relative_path":job["rel"],"source_folder":job["category"]},
        "corpus_classification":{"primary_topics":cls["topic_labels"],"secondary_topics":cls["secondary_topics"],"microbiome_relevance":cls["microbiome_relevance"],"human_evidence":cls["human_evidence"],"study_type":cls["study_type"],"inclusion_decision":cls["inclusion_decision"],"rule_based":cls,"llm_status":"not_requested"},
        "study_metadata":{"study_design":None,"research_question":None,"country_or_region":[],"population_description":None,"sample_size_reported":None,"number_of_participants":None,"number_of_samples":None,"health_conditions":[],"exposures":[],"control_group":None,"data_accessions":[],"confounders_reported":[],"limitations_reported":[]},
        "cohorts":[],"full_text":{"original_file":str(pdf.resolve()) if pdf else str(txt.resolve()) if txt else None,"clean_text_path":clean,"extraction_method":method,"page_count":pages,"character_count":len(text),"word_count_approx":len(text.split()),"section_index_kind":"character_offsets_into_clean_text_path","sections":secs,"tables":[],"figures":[],"supplementary_materials":[],"references":[]},
        "microbiome_metadata":{"applicable":cls["microbiome_relevance"]=="yes","body_sites":[],"sample_types":[],"kingdoms_or_domains":[],"assay_types":[],"sequencing_strategy":[],"sequencing_platforms":[],"target_genes_or_regions":[],"sample_collection_methods":[],"dna_extraction_methods":[],"negative_controls":[],"contamination_handling":[],"bioinformatics_pipelines":[],"taxonomic_databases":[],"functional_databases":[],"statistical_methods":[],"microbial_taxa_reported":[],"microbial_functions_reported":[],"metabolites_reported":[]},
        "exposures_and_interventions":{"medications":[],"antibiotics":[],"dietary_exposures":[],"probiotics":[],"prebiotics":[],"microbiota_transplantation":None,"other_exposures":[]},
        "findings":[],"quality_and_provenance":{"status":"needs_ocr_or_review" if low else "text_extracted","needs_ocr":bool(low),"full_text_completeness":"low_text_yield" if low else "text_extracted_not_manually_verified","extraction_tool":"PyMuPDF" if method=="pymupdf" else "source_txt","extraction_version":getattr(pymupdf,"VersionBind",None) if pymupdf else None,"extraction_date":now(),"tables_reviewed":False,"supplements_reviewed":False,"human_verified":False,"processing_seconds":round(time.monotonic()-started,3),"error":None}}
        atomic_json(rp,rec); return {"paper_id":pid,"status":"ok","record_path":str(rp),"chars":len(text),"words":len(text.split()),"seconds":round(time.monotonic()-started,3),"title":title,"doi":ids["doi"],"year":ids["publication_year"],"category":job["category"],"microbiome_relevance":cls["microbiome_relevance"],"human_evidence":cls["human_evidence"],"topics":";".join(cls["topic_labels"]),"needs_ocr":low,"clean_text_path":clean,"source_pdf":str(pdf) if pdf else "","source_txt":str(txt) if txt else ""}
    except Exception as e:
        err=f"{type(e).__name__}: {e}"; fail={"paper_id":pid,"schema_version":VERSION,"publication":{"title":None,"doi":None,"pmid":None,"pmcid":None,"publication_year":None,"abstract":None},"source":{"source_pdf":str(pdf) if pdf else None,"source_txt":str(txt) if txt else None,"relative_path":job["rel"],"source_folder":job["category"]},"corpus_classification":{"primary_topics":[job["category"]] if job["category"] in TOPICS else [],"secondary_topics":[],"microbiome_relevance":"unclear","human_evidence":"unclear","study_type":"unknown","inclusion_decision":"review_required","llm_status":"not_requested"},"study_metadata":{},"cohorts":[],"full_text":{"clean_text_path":None,"page_count":pages,"character_count":0,"word_count_approx":0,"sections":[]},"microbiome_metadata":{"applicable":None},"exposures_and_interventions":{},"findings":[],"quality_and_provenance":{"status":"error","human_verified":False,"extraction_date":now(),"error":err,"traceback":traceback.format_exc(limit=4)}}
        atomic_json(rp,fail); return {"paper_id":pid,"status":"error","record_path":str(rp),"error":err,"seconds":round(time.monotonic()-started,3),"category":job["category"],"source_pdf":str(pdf) if pdf else "","source_txt":str(txt) if txt else ""}

def write_csv(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True); fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader()
        for r in rows: w.writerow({k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in r.items()})
def run(args):
    root=Path(args.root).resolve(); out=Path(args.out).resolve(); out.mkdir(parents=True,exist_ok=True)
    jobs=discover(root)
    if args.benchmark_only: jobs=jobs[:args.benchmark_only]
    if args.max_papers: jobs=jobs[:args.max_papers]
    if args.resume and not args.force:
        jobs=[j for j in jobs if not outpaths(out,j["id"])[0].exists()]
    logging.info("Input jobs queued: %d",len(jobs))
    results=[]; start=time.monotonic(); done=0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs={pool.submit(process_one,{**j,"out":str(out)}):j for j in jobs}
        for fut in as_completed(futs):
            try:r=fut.result()
            except Exception as e:r={"status":"error","error":str(e),"relative_path":futs[fut]["rel"]}
            results.append(r); done+=1
            if done%args.log_every==0 or done==len(jobs):
                elapsed=time.monotonic()-start; rate=done/max(elapsed,0.001); eta=(len(jobs)-done)/max(rate,0.001)
                logging.info("progress %d/%d | %.2f papers/s | ETA %.1f min",done,len(jobs),rate,eta/60)
    if args.model: enrich_vllm(out,args.model,args)
    # Rebuild consolidated indexes from all records, including previous completed runs and any LLM updates.
    recpaths=sorted((out/"records").glob("*/*.json")); records=[]; findings=[]; studies=[]; summary={"total_records":0,"errors":0,"needs_ocr":0,"microbiome_yes":0,"human_signal":0,"topics":{}}
    jsonl_tmp=out/"papers.jsonl.gz.tmp"
    import gzip
    with gzip.open(jsonl_tmp,"wt",encoding="utf-8") as gz:
        for p in recpaths:
            try:r=json.loads(p.read_text(encoding="utf-8"))
            except Exception: continue
            gz.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n"); summary["total_records"]+=1
            qp=r.get("quality_and_provenance",{}); cc=r.get("corpus_classification",{}); pub=r.get("publication",{}); src=r.get("source",{}); ft=r.get("full_text",{})
            summary["errors"]+=qp.get("status")=="error"; summary["needs_ocr"]+=bool(qp.get("needs_ocr")); summary["microbiome_yes"]+=cc.get("microbiome_relevance")=="yes"; summary["human_signal"]+=cc.get("human_evidence")=="human_signal"
            for t in cc.get("primary_topics",[]): summary["topics"][t]=summary["topics"].get(t,0)+1
            records.append({"paper_id":r.get("paper_id"),"doi":pub.get("doi"),"pmid":pub.get("pmid"),"pmcid":pub.get("pmcid"),"title":pub.get("title"),"year":pub.get("publication_year"),"article_type":pub.get("article_type"),"source_folder":src.get("source_folder"),"relative_path":src.get("relative_path"),"primary_topics":cc.get("primary_topics",[]),"secondary_topics":cc.get("secondary_topics",[]),"microbiome_relevance":cc.get("microbiome_relevance"),"human_evidence":cc.get("human_evidence"),"inclusion_decision":cc.get("inclusion_decision"),"status":qp.get("status"),"needs_ocr":qp.get("needs_ocr"),"record_path":str(p),"full_text_path":ft.get("clean_text_path")})
            sm=r.get("study_metadata",{}); studies.append({"paper_id":r.get("paper_id"),"study_design":sm.get("study_design"),"research_question":sm.get("research_question"),"country_or_region":sm.get("country_or_region",[]),"population_description":sm.get("population_description"),"number_of_participants":sm.get("number_of_participants"),"number_of_samples":sm.get("number_of_samples"),"body_sites":r.get("microbiome_metadata",{}).get("body_sites",[]),"assay_types":r.get("microbiome_metadata",{}).get("assay_types",[]),"sequencing_strategy":r.get("microbiome_metadata",{}).get("sequencing_strategy",[]),"data_accessions":sm.get("data_accessions",[])})
            for f in r.get("findings",[]): findings.append({"paper_id":r.get("paper_id"),**f})
    os.replace(jsonl_tmp,out/"papers.jsonl.gz")
    write_csv(out/"corpus_manifest.csv",records); write_csv(out/"study_metadata.csv",studies); write_csv(out/"findings.csv",findings)
    write_csv(out/"processing_errors.csv",[r for r in records if r["status"]=="error"])
    summary.update({"input_root":str(root),"output_root":str(out),"run_processed":len(results),"run_seconds":round(time.monotonic()-start,2),"schema_version":VERSION,"generated_at":now(),"note":"Rule-based classifications are candidates, not validated scientific labels."})
    atomic_json(out/"corpus_summary.json",summary)
    logging.info("Finished corpus build. Manifest: %s",out/"corpus_manifest.csv")

def llm_schema():
    topics={"type":"array","items":{"type":"string","enum":TOPICS}}
    return {"type":"object","additionalProperties":False,"properties":{
      "microbiome_relevance":{"type":"string","enum":["yes","no","unclear"]},"human_evidence":{"type":"string","enum":["human","animal_only","in_vitro_only","mixed_human_animal_or_review","unclear"]},
      "study_type":{"type":"string","enum":["primary_human_study","primary_nonhuman_study","in_vitro_study","review","systematic_review","meta_analysis","clinical_trial","observational_study","case_report","methods_paper","other","unclear"]},
      "primary_topics":topics,"research_question":{"type":["string","null"]},"population_or_model":{"type":["string","null"]},"participant_or_sample_size":{"type":["string","null"]},
      "body_sites":{"type":"array","items":{"type":"string"}},"sample_types":{"type":"array","items":{"type":"string"}},"assay_types":{"type":"array","items":{"type":"string"}},"sequencing_strategy":{"type":"array","items":{"type":"string"}},"bioinformatics_methods":{"type":"array","items":{"type":"string"}},"data_accessions":{"type":"array","items":{"type":"string"}},"microbial_taxa":{"type":"array","items":{"type":"string"}},"microbial_functions_or_metabolites":{"type":"array","items":{"type":"string"}},
      "findings":{"type":"array","maxItems":3,"items":{"type":"object","additionalProperties":False,"properties":{"finding_text":{"type":"string"},"taxon_or_function":{"type":["string","null"]},"direction":{"type":"string","enum":["increase","decrease","no_association","mixed","not_stated"]},"effect_estimate":{"type":["string","null"]},"p_value":{"type":["string","null"]},"q_value":{"type":["string","null"]},"evidence_quote":{"type":["string","null"]},"evidence_location":{"type":["string","null"]}},"required":["finding_text","taxon_or_function","direction","effect_estimate","p_value","q_value","evidence_quote","evidence_location"]}},
      "limitations_reported":{"type":"array","items":{"type":"string"}},"extraction_note":{"type":"string"}},"required":["microbiome_relevance","human_evidence","study_type","primary_topics","research_question","population_or_model","participant_or_sample_size","body_sites","sample_types","assay_types","sequencing_strategy","bioinformatics_methods","data_accessions","microbial_taxa","microbial_functions_or_metabolites","findings","limitations_reported","extraction_note"]}
def enrich_vllm(out,model,args):
    try:
        from vllm import LLM, SamplingParams
        from vllm.sampling_params import StructuredOutputsParams
    except Exception as e: raise RuntimeError("vLLM requested but cannot import: "+str(e))
    enrich_records(out, model, args, backend="vllm")

def enrich_ollama(out,model,args):
    """Ollama backend (no-think, thread-parallel) — used for qwen3.5:4b-style fast enrichment."""
    enrich_records(out, model, args, backend="ollama")

def ollama_extract(host, model, prompt, max_tokens, timeout=600):
    """One Ollama /api/chat call with think disabled. Returns content str or raises."""
    import urllib.request
    payload={"model":model,"messages":[{"role":"user","content":prompt}],
             "stream":False,"think":False,
             "options":{"temperature":0.0,"seed":42,"num_predict":max_tokens,
                        "num_ctx":16384,"top_k":20,"top_p":0.8,"repeat_penalty":1.05}}
    req=urllib.request.Request(host.rstrip("/")+"/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        data=json.loads(resp.read().decode("utf-8"))
    if "error" in data: raise RuntimeError(data["error"])
    return (data.get("message") or {}).get("content","")

OLLAMA_PROMPT=("You are an expert curator building a STORMS-compliant human-microbiome corpus. "
 "Extract structured metadata from ONE paper's full text excerpt using ONLY the supplied text. "
 "Never infer or invent values: use null for scalars you cannot find and [] for arrays you cannot find. "
 "For every finding include body_site, exposure_or_comparison, outcome, association direction "
 "(increase/decrease/no_association/mixed/null), raw effect estimate (e.g. 'OR 1.4'), "
 "raw p/q values, adjusted covariates, and a SHORT VERBATIM quote copied EXACTLY from the text. "
 "Prioritize results-section findings (up to 10); separate the authors' reported findings from background/hypothesis text. "
 "Also fix boilerplate titles and return the real article title verbatim from the text. "
 "Return ONLY compact JSON matching this shape: "
 '{{"title": string-or-null, "microbiome_relevance": "yes"|"no"|"unclear", '
 '"human_evidence": "human"|"animal_only"|"in_vitro_only"|"mixed_human_animal_or_review"|"unclear", '
 '"study_type": string, "study_design": string-or-null, "research_question": string-or-null, '
 '"country_or_region": [], "population_description": string-or-null, '
 '"number_of_participants": int-or-null, "number_of_samples": int-or-null, "sample_size_reported": string-or-null, '
 '"health_conditions": [], "exposures": [], "control_group": string-or-null, '
 '"body_sites": [], "sample_types": [], "assay_types": [], "sequencing_strategy": string-or-null, '
 '"sequencing_platform": string-or-null, "target_gene_or_region": string-or-null, '
 '"sample_collection_method": string-or-null, "dna_extraction_method": string-or-null, '
 '"bioinformatics_pipeline": string-or-null, "taxonomic_database": string-or-null, '
 '"statistical_methods": [], "data_accessions": [], "confounders_reported": [], '
 '"limitations_reported": [], '
 '"findings": [{{"finding_text": string, "taxon_name": string-or-null, "taxonomic_rank": string-or-null, '
 '"microbial_function": string-or-null, "body_site": string-or-null, "exposure_or_comparison": string-or-null, '
 '"outcome": string-or-null, "direction": "increase"|"decrease"|"no_association"|"mixed"|null, '
 '"effect_measure": string-or-null, "effect_estimate": string-or-null, "p_value": string-or-null, "q_value": string-or-null, '
 '"confidence_interval": string-or-null, "adjusted_covariates": [], '
 '"evidence_quote": string-or-null, "evidence_location": string-or-null}}]}}\n\n'
 "TITLE: {title}\nDOI: {doi}\nABSTRACT: {abstract}\nTEXT EXCERPT:\n{excerpt}")

_JUNK_TITLE_RE = re.compile(
    r"full terms|www\.frontiersin\.org|downloaded from|journalInformation|"
    r"^http|^_\d|^copyright|^this is an open|creative commons|terms and conditions", re.I)

def _fill(target, key, value, method, notes):
    """Fill-if-empty: never clobber an existing non-empty value."""
    if value in (None, "", []): return False
    cur = target.get(key)
    if cur in (None, "", []):
        target[key] = value; notes.append(f"{key}<-{method}"); return True
    return False

def _norm_ws(s):
    return re.sub(r"\s+", " ", (s or "")).strip()
def _make_prompt(r, args):
    ft=r.get("full_text",{}); text=""
    try:
        tpath=Path(ft.get("clean_text_path") or ""); text=read_text(tpath) if tpath.is_file() else ""
    except Exception: pass
    title=r.get("publication",{}).get("title") or ""
    if title and _JUNK_TITLE_RE.search(title): title=""
    abst=r.get("publication",{}).get("abstract") or ""
    budget=max(2000,args.llm_context_chars); excerpt=text[:budget]
    if len(text)>budget*2: excerpt+="\n[END EXCERPT]\n"+text[-min(4000,budget//2):]
    return OLLAMA_PROMPT.format(title=title,doi=r.get("publication",{}).get("doi") or "",abstract=abst,excerpt=excerpt), text

def _parse_llm_json(content):
    content=(content or "").strip()
    if content.startswith("```"):
        content=re.sub(r"^```[a-z]*\n?|\n?```$","",content).strip()
    m=re.search(r"\{.*\}",content,re.S)  # outermost object
    if not m: return None
    raw=m.group(0)
    # tiny LLMs leak control chars (line-breaks inside quotes) into JSON;
    # strip them before parsing — they are never meaningful payload data
    raw=_CTRL_RE.sub(" ",raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # progressively stronger, still conservative repairs:
        # 1) unescaped INNER quotes inside string values — tiny models emit
        #    e.g. "finding": "the "healthy" controls" — rebind quotes to the
        #    ones followed by JSON structural chars, escape the rest
        try:
            return json.loads(_fix_inner_quotes(raw))
        except Exception:
            pass
        # 2) truncation: output cut mid-tail (hit max tokens) — close open
        #    containers, dropping only the dangling partial element
        repaired=_repair_truncated_json(raw)
        if repaired is not None:
            return json.loads(repaired)
        raise

_INNER_QUOTE_RE=re.compile(r'(?<![:,\[{\s])"(?![,:\]}]\s)|(?<![\s,:\[{])"(?=\s*[A-Za-z])')

def _fix_inner_quotes(raw):
    """Escape quotes that open a string NOT at a JSON value position and
    close one NOT at a structural boundary. Appends \\\" to those instead."""
    out=[]; i=0; n=len(raw)
    prev_significant=None  # last non-ws char before current quote
    while i<n:
        ch=raw[i]
        if ch!='"': 
            out.append(ch)
            if not ch.isspace(): prev_significant=ch
            i+=1; continue
        # ch is a quote. Decide: structural string boundary or inner quote?
        # look ahead to next char
        j=i+1
        while j<n and raw[j].isspace(): j+=1
        nxt=raw[j] if j<n else ''
        # a quote OPENS a string iff prev significant is one of , : [ { (or start)
        opens = prev_significant in (None,',',':','[','{')
        # a quote CLOSES a string iff next significant char is one of , : ] } (or end)
        closes = nxt in ('',',',':',']','}')
        if opens:
            out.append('"'); prev_significant='"'
        elif closes and not opens:
            # we're inside a string and this is the closing boundary
            out.append('"'); prev_significant='"'
        else:
            out.append('\\"'); prev_significant=None  # treat as inner text
        i+=1
    return "".join(out)

_CTRL_RE=re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

def _repair_truncated_json(raw):
    """Close a JSON object truncated mid-tail by a token limit.

    Strategy: walk chars tracking string-ness and bracket depth; on the last
    parse error, discard trailing partial key/value, then append the closing
    brackets for all still-open containers. Only the final incomplete element
    of arrays/objects is dropped; earlier complete elements are preserved.
    """
    depth=0; in_str=False; esc=False; last_cut=None
    for i,ch in enumerate(raw):
        if in_str:
            if esc: esc=False
            elif ch=="\\": esc=True
            elif ch=='"': in_str=False
            continue
        if ch=='"': in_str=True
        elif ch in "[{":
            depth+=1
        elif ch in "]}":
            depth-=1
        elif ch=="," and depth>=1:
            # remember position AFTER each comma inside a container:
            # candidate cut point (previous element was complete)
            last_cut=i
    if depth==0: return None  # not truncated — don't touch it
    # cut back to the last complete element boundary (or container start)
    if last_cut is not None:
        raw=raw[:last_cut]
    # strip a dangling partial key/value like `"key": "val` or `"ke`
    raw=raw.rstrip()
    # remove trailing incomplete fragment after the cut: keep only chars
    # belonging to already-complete structure. Simplest robust fix: drop any
    # trailing fragment that has unbalanced quotes.
    while _quote_balance(raw)!=0:
        raw=raw[:-1]
        if not raw: return None
    raw=raw.rstrip().rstrip(",")
    # close open containers in reverse order of opening
    opens=[]; in_str=False; esc=False
    for ch in raw:
        if in_str:
            if esc: esc=False
            elif ch=="\\": esc=True
            elif ch=='"': in_str=False
            continue
        if ch=='"': in_str=True
        elif ch in "[{": opens.append(ch)
        elif ch in "]}": opens and opens.pop()
    if opens==[]: return None
    raw+="".join("]" if o=="[" else "}" for o in reversed(opens))
    return raw

def _quote_balance(s):
    in_str=False; esc=False; bal=0
    for ch in s:
        if in_str:
            if esc: esc=False
            elif ch=="\\": esc=True
            elif ch=='"': in_str=False; bal=0
            continue
        if ch=='"': in_str=True; bal=1
    return bal

def _apply_extraction(r, extracted, model, text, notes):
    """Merge LLM output into a record. Fill-if-empty for Layer-2 fields; findings
    only get VERBATIM-verified quotes; title fixed only when currently junk/empty."""
    pub=r.setdefault("publication",{})
    # title fix (only replaces junk/empty, verified present in text)
    nt=extracted.get("title")
    if nt and _norm_ws(nt) and _norm_ws(nt).lower()[:60] in _norm_ws(text).lower():
        cur=pub.get("title") or ""
        if (not cur.strip()) or _JUNK_TITLE_RE.search(cur):
            pub["title"]=_norm_ws(nt); notes.append("title<-llm")
    # corpus classification / Layer-2 fields
    cc=r.setdefault("corpus_classification",{})
    er=r.setdefault("extraction_rules",{})
    notes_k=er.setdefault("notes",[]) if isinstance(er,dict) else None
    notes_out=notes_k if isinstance(notes_k,list) else None
    log=[]
    _fill(cc,"microbiome_relevance",extracted.get("microbiome_relevance"),model,log)
    _fill(cc,"human_evidence",extracted.get("human_evidence"),model,log)
    _fill(cc,"study_type",extracted.get("study_type"),model,log)
    sm=r.setdefault("study_metadata",{})
    for k,v in (("study_design",extracted.get("study_design")),
                ("research_question",extracted.get("research_question")),
                ("country_or_region",extracted.get("country_or_region") or []),
                ("population_description",extracted.get("population_description")),
                ("number_of_participants",extracted.get("number_of_participants")),
                ("number_of_samples",extracted.get("number_of_samples")),
                ("sample_size_reported",extracted.get("sample_size_reported")),
                ("health_conditions",extracted.get("health_conditions") or []),
                ("exposures",extracted.get("exposures") or []),
                ("control_group",extracted.get("control_group")),
                ("data_accessions",extracted.get("data_accessions") or []),
                ("confounders_reported",extracted.get("confounders_reported") or []),
                ("limitations_reported",extracted.get("limitations_reported") or []),
                ("statistical_methods",extracted.get("statistical_methods") or [])):
        _fill(sm,k,v,model,log)
    mm=r.setdefault("microbiome_metadata",{})
    for k,v in (("body_sites",extracted.get("body_sites") or []),
                ("sample_types",extracted.get("sample_types") or []),
                ("assay_types",extracted.get("assay_types") or []),
                ("sequencing_strategy",extracted.get("sequencing_strategy")),
                ("sequencing_platform",extracted.get("sequencing_platform")),
                ("target_gene_or_region",extracted.get("target_gene_or_region")),
                ("sample_collection_method",extracted.get("sample_collection_method")),
                ("dna_extraction_method",extracted.get("dna_extraction_method")),
                ("bioinformatics_pipelines",extracted.get("bioinformatics_pipeline")),
                ("taxonomic_database",extracted.get("taxonomic_database"))):
        _fill(mm,k,v,model,log)
    if log:
        if notes_out is not None: notes_out.extend(log)
        rules_log=er.setdefault("llm_filled",[]) if isinstance(er,dict) else None
        if isinstance(rules_log,list): rules_log.extend([model+":"+k for k in [l.split("<-")[0] for l in log]])
    # findings: verbatim-quote gate. LLM findings are APPENDED to existing regex
    # findings (never replace); each evidence_quote must appear in the source text.
    added_f=0; kept_quotes=0
    norm_text=_norm_ws(text).lower() if text else ""
    existing=r.setdefault("findings",[])
    for i,f in enumerate((extracted.get("findings") or [])[:10],1):
        q=_norm_ws(f.get("evidence_quote"))
        if not q: continue                      # refuse unverifiable claims
        if norm_text and q.lower()[:120] not in norm_text:
            continue                            # hallucinated/edited quote -> drop
        existing.append({
            "finding_id":f"{r.get('paper_id','P')}_L{i:02d}",
            "finding_text":f.get("finding_text"),"taxon_raw":f.get("taxon_name"),
            "taxon_or_function":f.get("taxon_name"),"taxonomic_rank":f.get("taxonomic_rank"),
            "microbial_function":f.get("microbial_function"),
            "body_site":f.get("body_site"),"exposure_or_comparison":f.get("exposure_or_comparison"),
            "outcome":f.get("outcome"),"direction":f.get("direction"),
            "effect_measure":f.get("effect_measure"),"effect_estimate":f.get("effect_estimate"),
            "p_value":f.get("p_value"),"q_value":f.get("q_value"),
            "confidence_interval":f.get("confidence_interval"),
            "adjusted_covariates":f.get("adjusted_covariates") or [],
            "evidence_text":q,"evidence_locator":f.get("evidence_location"),
            "extraction_method":f"ollama:{model}","confidence":"llm_medium",
            "human_verified":False})
        added_f+=1
    if added_f: notes.append(f"findings+={added_f}(verified)")
    qp=r.setdefault("quality_and_provenance",{})
    qp["llm_extraction_date"]=now(); qp["llm_model"]=model
    qp["llm_input_scope"]="title_abstract_bounded_text_excerpt"
    qp["human_verified"]=False
    cc["llm_status"]="completed"; cc["llm_model"]=model
    return added_f

def enrich_records(out, model, args, backend):
    """Shared enrichment driver: pick todo records, invoke backend, apply results."""
    paths=sorted((out/"records").glob("*/*.json")); todo=[]
    for p in paths:
        try:r=json.loads(p.read_text(encoding="utf-8"))
        except Exception:continue
        if r.get("quality_and_provenance",{}).get("status")=="error" or r.get("corpus_classification",{}).get("llm_status")=="completed":continue
        if r.get("corpus_classification",{}).get("microbiome_relevance")=="no":continue
        todo.append(p)
    if args.llm_max_papers: todo=todo[:args.llm_max_papers]
    if not todo: logging.info("No LLM enrichment jobs."); return
    manifest=[]
    if backend=="vllm":
        from vllm import LLM, SamplingParams
        from vllm.sampling_params import StructuredOutputsParams
        llm=LLM(model=model,dtype=args.model_dtype,max_model_len=args.model_max_len,gpu_memory_utilization=args.gpu_memory_utilization,trust_remote_code=args.trust_remote_code)
        schema=llm_schema(); sp=SamplingParams(temperature=0.0,max_tokens=args.llm_max_tokens,structured_outputs=StructuredOutputsParams(json=schema))
        for batch_start in range(0,len(todo),args.llm_batch_size):
            batch=todo[batch_start:batch_start+args.llm_batch_size]; prompts=[]
            for p in batch:
                r=json.loads(p.read_text(encoding="utf-8"))
                prompt,text=_make_prompt(r,args); prompts.append(prompt)
            outputs=llm.generate(prompts,sp)
            for p,o in zip(batch,outputs):
                try:
                    r=json.loads(p.read_text(encoding="utf-8"))
                    extracted=_parse_llm_json(o.outputs[0].text) or json.loads(o.outputs[0].text)
                    if not extracted: raise RuntimeError("empty extraction")
                    notes=[]; _apply_extraction(r,extracted,model,"",notes)
                    atomic_json(p,r); manifest.append({"paper_id":r.get("paper_id"),"llm_status":"completed","model":model})
                except Exception as e: manifest.append({"record_path":str(p),"llm_status":"error","error":str(e)})
            logging.info("LLM enrichment %d/%d",min(batch_start+len(batch),len(todo)),len(todo))
        return
    if backend=="ollama":
        host=args.ollama_host; timeout=args.ollama_timeout
        nproc=min(args.ollama_parallel, max(1,len(todo)))
        from concurrent.futures import ThreadPoolExecutor, as_completed as _acf
        logging.info("Ollama backend: %s at %s | %d papers | %d parallel workers",model,host,len(todo),nproc)
        def work(p):
            r=json.loads(p.read_text(encoding="utf-8"))
            prompt,text=_make_prompt(r,args)
            content=ollama_extract(host,model,prompt,args.llm_max_tokens,timeout)
            extracted=_parse_llm_json(content)
            if not extracted: raise RuntimeError("unparseable JSON response")
            notes=[]; added=_apply_extraction(r,extracted,model,text,notes)
            atomic_json(p,r)
            return {"paper_id":r.get("paper_id"),"llm_status":"completed","model":model,
                    "status":"ok","n_findings_added":added,"notes":";".join(notes)}
        done=0; start=time.monotonic()
        with ThreadPoolExecutor(max_workers=nproc) as pool:
            futs={pool.submit(work,p):p for p in todo}
            for fut in _acf(futs):
                try:manifest.append(fut.result())
                except Exception as e:
                    manifest.append({"record_path":str(futs[fut]),"llm_status":"error","error":str(e)})
                    logging.getLogger(__name__).warning("LLM enrichment FAILED for %s: %s",futs[fut],e)
                done+=1
                if done%20==0 or done==len(todo):
                    rate=done/max(time.monotonic()-start,0.001)
                    logging.info("LLM enrichment %d/%d | %.2f papers/s | ETA %.1f min",done,len(todo),rate,(len(todo)-done)/rate/60)
    write_csv(out/"llm_enrichment_log.csv",manifest)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",required=True); ap.add_argument("--out",required=True); ap.add_argument("--workers",type=int,default=max(4,min(32,os.cpu_count() or 8)))
    ap.add_argument("--resume",action="store_true",default=True); ap.add_argument("--force",action="store_true",help="reprocess records even if output JSON exists")
    ap.add_argument("--benchmark-only",type=int,default=0); ap.add_argument("--max-papers",type=int,default=0); ap.add_argument("--log-every",type=int,default=500)
    ap.add_argument("--model",default=None,help="Optional local vLLM model path/name for deep enrichment"); ap.add_argument("--llm-max-papers",type=int,default=0); ap.add_argument("--llm-batch-size",type=int,default=32); ap.add_argument("--llm-context-chars",type=int,default=16000); ap.add_argument("--llm-max-tokens",type=int,default=1800); ap.add_argument("--model-dtype",default="auto"); ap.add_argument("--model-max-len",type=int,default=8192); ap.add_argument("--gpu-memory-utilization",type=float,default=.88); ap.add_argument("--trust-remote-code",action="store_true")
    ap.add_argument("--ollama",default=None,help="Ollama model name for fast backend, e.g. qwen3.5:4b (starts no-think thread-parallel enrichment)"); ap.add_argument("--ollama-host",default="http://127.0.0.1:11397"); ap.add_argument("--ollama-parallel",type=int,default=12,help="concurrent /api/chat workers"); ap.add_argument("--ollama-timeout",type=int,default=600)
    args=ap.parse_args(); logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    if args.ollama and args.model: raise SystemExit("--ollama and --model are mutually exclusive")
    if args.ollama:
        # ollama path: rerun() then enrich_ollama() — mirror of enrich_vllm hook below
        args.ollama_mode=True
    else:
        args.ollama_mode=False
    run(args)
    if args.ollama_mode:
        out=Path(args.out); enrich_ollama(out,args.ollama,args)
if __name__=="__main__": main()
