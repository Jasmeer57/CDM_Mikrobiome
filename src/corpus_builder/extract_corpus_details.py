#!/usr/bin/env python3
"""Rule/regex-based metadata + finding extractor over the corpus full texts.

Runs OFFLINE on all corpus records (papers_txt-backed). Fills Layer 2
(study/microbiome metadata) and Layer 3 (evidence-backed findings) slots that
rule patterns can reach, complementing the deep NER ensemble running on HPC.

Design rules (mirrors enrich_corpus_records.py):
  - NEVER overwrite existing non-empty values; only fill null/empty lists.
  - Every filled field is tracked in record['extraction_rules'] provenance.
  - Findings are evidence-quoted: exact supporting sentence + locator.

Usage:
    python3 extract_corpus_details.py [--records outputs/results/human_microbiome_corpus_v1]
"""

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent
DEFAULT_RECORDS = REPO / "outputs/results" / "human_microbiome_corpus_v1"

# ─────────────────────────────────────────────────────────────────────────────
# Lexicons. Each entry: (compiled regex, normalized capture target).
# For single-group patterns the group is the normalized label.
# ─────────────────────────────────────────────────────────────────────────────

def _rx(*pats):
    return [re.compile(p, re.IGNORECASE) for p in pats]


LEXICONS = {
    "sequencing_platforms": _rx(
        r"\bIllumina\s+(MiSeq|NextSeq|HiSeq\s*\d*|NovaSeq\s*\d*|MiniSeq|iSeq)\b",
        r"\b(454|GS\s*FLX|Ion\s*Torrent|PacBio\s*Sequel\w*|Oxford\s*Nanopore|MinION)\b",
        r"\bSanger\s+(?:capillary\s+)?sequencing\b",
    ),
    "target_genes_or_regions": _rx(
        r"\b16S\s*r?(?:RNA|DNA)?\b",
        r"\b(?:V\d(?:\s*[-–]\s*V?\d)?)\s*(?:region|hypervariable\s*region)?\b",
        r"\bITS\d?\s*(?:region|spacer)?\b",
        r"\b23S\s*r?RNA?\b",
        r"\bshotgun\s+metagenom\w+\b",
        r"\bmetatranscriptom\w+\b",
    ),
    "dna_extraction_methods": _rx(
        r"\b(?:Qiagen\s+)?QIAamp\b[\w\s]*(?:kit)?",
        r"\b(?:Qiagen\s+)?DNeasy\b[\w\s]*(?:kit)?",
        r"\bMo\s?Bio\s+(?:UltraClean|PowerSoil|PowerFecal)\w*\b",
        r"\b(?:UltraClean|PowerSoil|PowerFecal)\s*(?:Stool)?\s*(?:kit|Pro)\b",
        r"\bFastDNA\s+Spin\s+Kit\b",
        r"\bMagMax\b[\w\s]*(?:kit)?",
        r"\bphenol[–\s-]chloroform\b",
    ),
    "sample_collection_methods": _rx(
        r"\b(?:fecal|faecal|stool)\s*(?:sample|specimen)?s?\s*(?:were\s+)?(?:collected|obtained|gathered)\b",
        r"\b(?:buccal|saliva|sputum|vaginal|skin|nasal|oral)\s*(?:swab|sample|specimen)s?\s*(?:were\s+)?(?:collected|obtained)\b",
        r"\b(?:throat|rectal|nasopharyngeal)\s*swab\w*\b",
        r"\bfreshly\s+collected\b",
    ),
    "bioinformatics_pipelines": _rx(
        r"\bQIIME\s?2?\b", r"\bMothur\b", r"\bUSEARCH\d*\b", r"\bVSEARCH\b",
        r"\bDADA2?\b", r"\bRDP\b", r"\bMetaPhlAn\d?\b", r"\bHUMAnN\d?\b",
        r"\bLEfSe\b", r"\bKneadData\b", r"\bKraken\d?\b", r"\bBracken\b",
        r"\bBowtie2?\b", r"\bBWA\b", r"\bflash\b", r"\bmapper\b",
    ),
    "taxonomic_databases": _rx(
        r"\bSILVA\b", r"\bGreengenes\d?\b", r"\bGTDB\b", r"\bNCBI\s*16S\b",
        r"\bEzBioCloud\b", r"\bHOMD\b", r"\bRefSeq\b", r"\bRDP\s*database\b",
    ),
    "statistical_methods": _rx(
        r"\bPERMANOVA\b", r"\bANOSIM\b", r"\bMRPP\b", r"\bDESeq2?\b", r"\bedgeR\b",
        r"\bANCOM(?:\s*BC)?\b", r"\bALDEx2\b", r"\bWilcoxon\b",
        r"\bMann[–\s-]Whitney\b", r"\bKruskal[–\s-]Wallis\b",
        r"\bBenjamini[–\s-]Hochberg\b", r"\bBonferroni\b", r"\bfalse\s+discovery\s+rate\b",
        r"\bLEfSe\b", r"\bSparCC\b", r"\bFisher'?s?\s*(?:exact)?\s*test\b",
        r"\bPCoA\b", r"\bPCA\b", r"\bNMDS\b", r"\blinear\s+(?:mixed[–\s-]?)?model\w*\b",
        r"\blog[–\s-]linear\s+model\b", r"\bSpearman\b", r"\bPearson\b",
    ),
    "body_sites": _rx(
        r"\b(?:fecal|faecal|stool)\b", r"\bgastric\b", r"\boral\b", r"\bsaliva\w*\b",
        r"\bvagin\w+\b", r"\bskin\b", r"\bnasal\b", r"\bsputum\b", r"\brectal\b",
        r"\bduoden\w+\b", r"\bcolonic\b", r"\bmucos\w+\b", r"\bileum\b", r"\bthroat\b",
        r"\bbreast\s+milk\b", r"\bmeconium\b", r"\bplacenta\w*\b", r"\burine\b",
        r"\bcervic\w+\b", r"\btonsil\w*\b", r"\bmiddle\s+ear\b", r"\blung\w*\b",
        r"\bbronch\w+\b", r"\besophag\w+\b", r"\bcecum\b", r"\bappendix\b",
        r"\bteeth\b", r"\bdental\s+plaque\b", r"\bgingiv\w*\b", r"\btongue\b",
    ),
    "sample_types": _rx(
        r"\b(?:stool|feces|faeces)\b", r"\bswab\w*\b", r"\b(?:aspirate|biopsy|lavage)s?\b",
        r"\b(?:saliva|sputum|serum|plasma|urine|milk)\b", r"\bmucosa\b", r"\btissue\s+samples?\b",
    ),
    "negative_controls": _rx(
        r"\b(?:negative|blank|no[–\s-]template)\s+controls?\b",
        r"\bmock\s+community\b", r"\bZymo\w*\b",
        r"\bextraction\s+blanks?\b", r"\bPCR\s+blanks?\b",
    ),
    "contamination_handling": _rx(
        r"\bdecontam\w*\b", r"\bcontaminant\w*\s+(?:removal|identification|filter)\w*",
        r"\b(?:reagent|kit)\s+contamination\b",
        r"\bcontamination\s+(?:assessment|screen)\w*",
    ),
    "assay_types": _rx(
        r"\b16S\s*(?:rRNA|rDNA|amplicon|sequencing)?\w*\b",
        r"\bshotgun\b", r"\bmetagenomic\b", r"\bmetatranscriptomic\w*\b",
        r"\bmetabolomic\w*\b", r"\bmetaproteomic\w*\b", r"\bculturom\w*\b",
        r"\b(?:flow\s+cytometry|FISH)\b", r"\b(?:qPCR|RT-PCR|real[–\s-]time\s+PCR)\b",
    ),
}

HEALTH_CONDITION_PATTERNS = _rx(
    r"\bcolorectal\s+cancer\b", r"\bCRC\b", r"\binflammatory\s+bowel\s+disease\b", r"\bIBD\b",
    r"\bCrohn'?s?\s+disease\b", r"\bulcerative\s+colitis?\b",
    r"\birritable\s+bowel\s+syndrome\b", r"\bIBS\b",
    r"\btype\s*[12]\s+diabetes\b", r"\bT[12]D\b", r"\bgestational\s+diabetes\b",
    r"\bobesity\b", r"\bobese\b",
    r"\bnon[–\s-]?alcoholic\s+fatty\s+liver\w*\b", r"\bNAFLD\b", r"\bNASH\b",
    r"\bcardiovascular\s+disease\b", r"\bCVD\b", r"\batherosclerosis\b", r"\bhypertension\b",
    r"\bCOPD\b", r"\bchronic\s+obstructive\s+pulmonary\w*\b", r"\basthma\b",
    r"\ballerg\w+\b", r"\batopic\s+dermatitis\b", r"\beczema\b", r"\bpsoriasis\b",
    r"\bParkinson'?s?\s+disease\b", r"\bAlzheimer'?s?\s+disease\b",
    r"\bdepression\b", r"\banxiety\b", r"\bautism\w*\b", r"\bASD\b",
    r"\bschizophrenia\b", r"\bbipolar\b",
    r"\bmultiple\s+sclerosis\b",
    r"\bchronic\s+kidney\s+disease\b", r"\bCKD\b", r"\bcirrhosis\b",
    r"\bHIV\b", r"\bsepsis\b", r"\bbacteremia\b",
    r"\bClostridioides\s+difficile\b", r"\bClostridium\s+difficile\b", r"\bC\.\s*difficile\b",
    r"\bnecrotizing\s+enterocolitis\b", r"\bNEC\b",
    r"\bpreterm\b", r"\bpremature\s+(?:birth|infant\w*)\b",
    r"\bundernutrition\b", r"\bmalnutrition\b", r"\bkwashiorkor\b",
    r"\banorexia\s+nervosa\b",
    r"\bmetabolic\s+syndrome\b", r"\bgout\b", r"\bosteoporosis\b",
    r"\bmigraine\b", r"\bsleep\s+apnea\b", r"\brheumatoid\s+arthritis\b",
    r"\btype\s+1\s+diabetes\b", r"\bliver\s+cancer\b", r"\bpancreatic\s+cancer\b",
)

EXPOSURE_LEXICONS = {
    "antibiotics": _rx(
        r"\b(?:vancomycin|metronidazole|ciprofloxacin|clarithromycin|amoxicillin|ampicillin)\b",
        r"\b(?:azithromycin|doxycycline|minocycline|rifaximin|gentamicin|streptomycin)\b",
        r"\b(?:erythromycin|tetracycline|chloramphenicol|clindamycin|meropenem|imipenem)\b",
        r"\bcarbapenem\w*\b", r"\bfluoroquinolon\w*\b", r"\bmacrolide\w*\b",
        r"\bbeta[–\s-]?lactam\w*\b", r"\bantibiotic\w*\b",
    ),
    "probiotics": _rx(
        r"\bLactobacill\w+\b", r"\bBifidobacteri\w+\b", r"\bSaccharomyces\s+(?:boulardii|cerevisiae)\b",
        r"\bprobiotic\w*\b", r"\bVSL#3\b",
    ),
    "prebiotics": _rx(
        r"\bprebiotic\w*\b", r"\binulin\b", r"\bfructooligosaccharide\w*\b",
        r"\bFOS\b", r"\bGOS\b", r"\bgalactooligosaccharide\w*\b", r"\bresistant\s+starch\b",
    ),
    "dietary_exposures": _rx(
        r"\bhigh[–\s-]?fat\s+diet\b", r"\bwestern\s+diet\b", r"\bMediterranean\s+diet\b",
        r"\bvegan\w*\b", r"\bvegetarian\w*\b", r"\bgluten[–\s-]?free\b",
        r"\bfermented\s+(?:food|milk)s?\b", r"\bfibre\b", r"\bfiber\s+intake\b",
        r"\bdietary\s+(?:intervention|supplement\w*|pattern\w*)\b",
    ),
    "microbiota_transplantation": _rx(
        r"\b(?:fecal|faecal)\s+(?:micro\w*\s*)?(?:transplant\w*|transfer\w*)\b",
        r"\bFMT\b", r"\bstool\s+transplant\w*\b",
    ),
}

STUDY_DESIGN_PATTERNS = _rx(
    r"\brandom(?:is|iz)ed\s+control?\w*\s+trial\b", r"\bRCT\b",
    r"\bcohort\s+(?:study|design)?\b", r"\bprospective\b", r"\bretrospective\b",
    r"\blongitudinal\b", r"\bcross[–\s-]sectional\b",
    r"\bcase[–\s-]control\s+(?:study)?\b",
    r"\bpilot\s+(?:study|trial)?\b", r"\bfeasibility\s+(?:study|trial)?\b",
    r"\bmetagenome[–\s-]wide\s+association\b",
    r"\btwin\s+study\b", r"\bgnotobiotic\b", r"\b(?:animal|murine)\s+model\b",
)

# ── Field-specific singular extractors ───────────────────────────────────────

N_PARTICIPANTS = re.compile(
    r"(\d[\d,]*)\s+(?:participants?|subjects?|individuals?|patients?|volunteers?|healthy\s+adults?|enrolled)\b",
    re.IGNORECASE)
N_SAMPLES = re.compile(
    r"(\d[\d,]*)\s+(?:fecal\s+|faecal\s+|stool\s+|gut\s+)?(?:samples?|specimens?|stool\s+samples?)\b"
    r"(?!\s+(?:were|are)\s+(?:collected|analyz|sequenc)\w*)",
    re.IGNORECASE)
N_SAMPLES_COLLECTED = re.compile(
    r"(\d[\d,]*)\s+(?:fecal\s+|faecal\s+|stool\s+|gut\s+|saliva\s+|vaginal\s+|skin\s+)?"
    r"samples?\s+(?:were|are|had\s+been)\s+(?:collected|obtained|analyz\w+|sequenced|gathered)\b",
    re.IGNORECASE)

ACCESSIONS = re.compile(
    r"\b(PRJ[END][A-Z]?\d+|SAM[NE][0-9A-Z]+|ERS\d+|SRR\d+|ERP\d+|DRA\d+)\b")
DOIS = re.compile(r"\b(10\.\d{4,9}/[^\s,;)\]}\"']+?)(?=[\s,;)\]}\"]|$)")

# Increased/decreased taxa findings (Layer 3, evidence-quoted)
FINDING_INCREASE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(?:was|were|is|are|became)\s+"
    r"(?:significantly\s+|significantly\s+enriched\s+in\s+the\s+)?"
    r"(?:enriched|increased|over[–\s-]?represented|elevated|abundant|more\s+abundant|higher)\b",
    re.IGNORECASE)
FINDING_DECREASE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(?:was|were|is|are)\s+"
    r"(?:significantly\s+)?"
    r"(?:depleted|decreased|reduced|under[–\s-]?represented|less\s+abundant|lower)\b",
    re.IGNORECASE)

# Latin-shaped taxon names: Genus or Genus species; optionally prefixed by
# "phylum/genus/family X" wording which the caller strips.
TAXON_LATIN = re.compile(
    r"\b(?:phylum|class|order|family|genus|species)\s+([A-Z][a-z]{2,}(?:\s+[a-z]{3,})?)\b")
TAXON_BOLD = re.compile(
    r"\b([A-Z][a-z]{2,}(?:\s+[a-z]{3,6})?)\b(?:\s+(?:spp\.?|str\.?)\b)?")

TAXON_STOP = {
    "diversity", "richness", "abundance", "composition", "samples", "children",
    "patients", "subjects", "participants", "individuals", "groups", "group",
    "levels", "level", "differences", "difference", "values", "mass", "index",
    "microbiota", "community", "communities", "levels", "enterotype",
    "disease", "disorder", "obesity", "cancer", "inflammation", "markers",
    "metabolites", "genes", "gene", "species", "genus", "study", "studies",
    "risk", "score", "scores", "weight", "weights", "bmi", "diagnosis", "spectrum",
    "stunted", "stunting", "wasting", "between", "relatives", "controls",
    "patients", "or", "the", "a", "an", "and", "these", "those", "their",
    "proteobacteria", "firmicutes", "bacteroidetes",  # phyla allowed actually — removed below
    "peptide", "fragments", "genera", "family", "families", "species", "reads",
    "markers", "cells", "sequences", "otus", "asvs", "metabolites", "genes",
}
TAXON_STOP.discard("proteobacteria")
TAXON_STOP.discard("firmicutes")
TAXON_STOP.discard("bacteroidetes")

# ─────────────────────────────────────────────────────────────────────────────

SENT_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\d])")


def is_taxon(word):
    # Latin-shaped head: either "Genus" or "Genus species" (italic-style lowercase epitet)
    parts = word.strip().split()
    head = parts[-1].lower().rstrip(".,;")
    if head in TAXON_STOP or len(head) < 4:
        return False
    # Must start uppercase + lowercase body (Latin by convention) unless flagged
    if not re.match(r"^[A-Z][a-z]{2,}$", parts[0]):
        return False
    if len(parts) == 2 and not re.match(r"^[a-z]{3,}$", parts[1]):
        return False
    return True


def sentences(text):
    """Yield (start_char, sentence) tuples over text."""
    pos = 0
    for m in SENT_BOUNDARY.finditer(text):
        yield pos, text[pos:m.start()]
        pos = m.end()
    if pos < len(text):
        yield pos, text[pos:]


def find_section(sections, char_off):
    """Resolve record's section list index for a char offset into plain text."""
    for s in sections:
        if s.get("start_char") is not None and s["start_char"] <= char_off < s.get("end_char", 1 << 30):
            return s.get("section_id")
    return None


def uniq_labels(matches_iter):
    """Normalize matched fragments: strip, dedupe (case-insensitive), cap."""
    seen = set()
    out = []
    for m in matches_iter:
        label = (m.group(1) if m.groups() else m.group(0)).strip()
        label = re.sub(r"\s+", " ", label)
        if label and label.lower() not in seen:
            seen.add(label.lower())
            out.append(label)
    return out


def fill_list_field(rec_dict, key, new_vals, provenance, rules_seen):
    """Append-fill a list field without duplicating existing entries. Returns count added."""
    cur = rec_dict.get(key) or []
    have = {str(v).strip().lower() for v in cur if v}
    added = 0
    for v in new_vals:
        if v.strip().lower() not in have:
            cur.append(v)
            have.add(v.strip().lower())
            added += 1
    if added:
        rec_dict[key] = cur
        rules_seen[key] = rules_seen.get(key, 0) + added
    return added


def extract_for_paper(text, sections):
    """Extract all rule-based fields from a paper's clean text. Returns dict of results."""
    res = {}
    for field, pats in LEXICONS.items():
        vals = []
        for p in pats:
            vals.extend(uniq_labels(p.finditer(text)))
        res[field] = vals[:15]

    res["health_conditions"] = uniq_labels(p.finditer(text) for p in HEALTH_CONDITION_PATTERNS)[:15] \
        if False else uniq_labels(
            (m for p in HEALTH_CONDITION_PATTERNS for m in p.finditer(text)))

    for field, pats in EXPOSURE_LEXICONS.items():
        vals = []
        for p in pats:
            vals.extend(uniq_labels(p.finditer(text)))
        res[field] = vals[:12]

    designs = uniq_labels(m for p in STUDY_DESIGN_PATTERNS for m in p.finditer(text))
    res["study_design"] = designs[:6]

    mp = N_PARTICIPANTS.search(text)
    res["number_of_participants"] = mp.group(1).replace(",", "") if mp else None
    ms = N_SAMPLES_COLLECTED.search(text) or N_SAMPLES.search(text)
    res["number_of_samples_text"] = ms.group(1).replace(",", "") if ms else None

    res["data_accessions"] = uniq_labels(ACCESSIONS.finditer(text))
    res["dois"] = uniq_labels(DOIS.finditer(text))[:10]

    # Findings: increased/decreased taxa sentences
    findings = []
    for off, sent in sentences(text):
        if len(sent) < 25 or len(sent) > 600:
            continue
        for rx, direction in ((FINDING_DECREASE, "decreased"), (FINDING_INCREASE, "increased")):
            for m in rx.finditer(sent):
                tax = m.group(1).strip()
                if not is_taxon(tax):
                    continue
                findings.append({
                    "direction": direction,
                    "taxon_raw": tax,
                    "evidence_text": sent.strip(),
                    "evidence_locator": find_section(sections, off) or "unknown_section",
                    "extraction_method": "regex_v1",
                })
                break
        if len(findings) >= 12:
            break
    res["findings"] = findings
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=str(DEFAULT_RECORDS), type=str)
    args = ap.parse_args()
    recdir = Path(args.records)
    paths = sorted(recdir.glob("records/*/*.json"))
    print(f"Processing {len(paths)} records")

    t0 = time.time()
    stats = Counter()
    for i, p in enumerate(paths, 1):
        rec = json.loads(p.read_text())
        text_path = rec.get("full_text", {}).get("clean_text_path")
        stext = None
        if text_path and Path(text_path).exists():
            try:
                stext = Path(text_path).read_text(errors="ignore")
            except OSError:
                stext = None
        if not stext:
            stext = (rec.get("publication", {}).get("abstract") or "") + "\n" + \
                    "\n".join(s.get("text", "") for s in rec.get("full_text", {}).get("sections", [])[:5] if s.get("text"))
        if not stext.strip():
            stats["no_text"] += 1
            continue

        sections = rec.get("full_text", {}).get("sections", [])
        ext = extract_for_paper(stext, sections)

        rules_seen = {}

        sm = rec.setdefault("study_metadata", {})
        mm = rec.setdefault("microbiome_metadata", {})
        ex = rec.setdefault("exposures_and_interventions", {})
        fb = rec.setdefault("findings", [])

        if not (sm.get("study_design") or "").strip():
            sm["study_design"] = "; ".join(ext["study_design"]) or None
            if sm["study_design"]:
                rules_seen["study_metadata.study_design"] = 1
        def _fill(target, key, vals):
            cur = target.get(key) or []
            have = {str(v).strip().lower() for v in cur}
            for v in vals:
                if v and v.strip().lower() not in have:
                    cur.append(v)
            if cur:
                target[key] = cur
                return len(cur)
            return 0

        if not sm.get("health_conditions"):
            n = _fill(sm, "health_conditions", ext["health_conditions"])
            if n: rules_seen["study_metadata.health_conditions"] = n
        if not sm.get("number_of_participants"):
            if ext["number_of_participants"]:
                sm["number_of_participants"] = ext["number_of_participants"]
                rules_seen["study_metadata.number_of_participants"] = 1
        if not sm.get("data_accessions"):
            accs = ext["data_accessions"]
            if accs:
                sm["data_accessions"] = accs
                rules_seen["study_metadata.data_accessions"] = len(accs)

        for key in ("sequencing_platforms", "target_genes_or_regions", "dna_extraction_methods",
                    "sample_collection_methods", "bioinformatics_pipelines", "taxonomic_databases",
                    "statistical_methods", "body_sites", "sample_types", "negative_controls",
                    "contamination_handling", "assay_types"):
            if not mm.get(key):
                n = _fill(mm, key, ext[key])
                if n: rules_seen[f"microbiome_metadata.{key}"] = n

        for key in ("antibiotics", "probiotics", "prebiotics", "dietary_exposures"):
            if not ex.get(key):
                n = _fill(ex, key, ext[key])
                if n: rules_seen[f"exposures_and_interventions.{key}"] = n
        if not (ex.get("microbiota_transplantation") or "").strip():
            if ext["microbiota_transplantation"]:
                ex["microbiota_transplantation"] = ext["microbiota_transplantation"][0]
                rules_seen["exposures_and_interventions.microbiota_transplantation"] = 1

        # Findings: append only ones not already present (dedupe by evidence_text)
        existing_ev = {f.get("evidence_text") for f in fb if isinstance(f, dict)}
        added_f = 0
        for f in ext["findings"]:
            if f["evidence_text"] in existing_ev:
                continue
            entry = {
                "finding_type": "taxon_abundance_direction",
                "direction": f["direction"],
                "taxon_raw": f["taxon_raw"],
                "evidence_text": f["evidence_text"],
                "evidence_locator": f["evidence_locator"],
                "extraction_method": f["extraction_method"],
                "confidence": "rule_low",
                "human_verified": False,
            }
            fb.append(entry)
            existing_ev.add(f["evidence_text"])
            added_f += 1
        if added_f:
            rules_seen["findings"] = added_f
            stats["papers_with_new_findings"] += 1
        if ext["findings"]:
            stats["papers_with_finding_candidates"] += 1

        if rules_seen:
            prov = rec.setdefault("extraction_rules", {})
            prov.update({
                "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                "fields_filled": rules_seen,
                "method": "regex_v1",
            })
            p.write_text(json.dumps(rec, indent=2))
            stats["papers_updated"] += 1
        if i % 50 == 0:
            print(f"  {i}/{len(paths)} ({time.time()-t0:.0f}s)")

    print(f"\nDone in {time.time()-t0:.0f}s")
    print(f"papers updated:            {stats['papers_updated']}")
    print(f"papers with findings added: {stats['papers_with_new_findings']}")
    print(f"no text found:             {stats['no_text']}")


if __name__ == "__main__":
    main()
