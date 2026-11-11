"""Two-level gazetteers (family + model/kit) for two catalogue fields, CDM layer 3.2.0-candidate (2026-11-11).

  sequencing_platform     family (Illumina, Ion Torrent, PacBio, Oxford Nanopore, BGI/MGI, Roche 454, Sanger/capillary)
                          -> instrument model (MiSeq, HiSeq 2500, NovaSeq 6000, ...)
  dna_extraction_method   family (vendor or method class) -> kit / protocol (QIAamp Fast DNA Stool Mini Kit, ...)

Sources: vendor product lines (Illumina, Thermo Fisher Ion Torrent, PacBio, ONT, BGI/MGI, Roche 454, Qiagen/MO BIO,
Zymo, MP Biomedicals, Promega, Thermo, Omega, PerkinElmer Chemagic, Roche MagNA Pure, Macherey-Nagel, Stratec, ...)
plus product strings mined from the corpus methods sections (scan in the build log, 2026-11-11). The gazetteers were
written BEFORE any evaluation run; they were not tuned on the judges, GutBiomeDB, or the spot-check.

Each entry: (family, model, regex). Regexes are case-insensitive unless the entry sets cs=True; whitespace inside product
names is matched by \\s+ / \\s* because the corpus text has line breaks inside names. Entries are ordered from specific to
generic; the matcher keeps the longest/most-specific non-overlapping hit. model == "" means family-level only.
Family-level Illumina / BGI / 454 hits require a sequencing context in the same sentence (see CONTEXT_REQUIRED).

    python src/scripts/fixes_v32/gazetteer.py        # writes gazetteer JSON (+ sha256) to the results folder
Written with Claude Code (declare).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
OUT = ROOT / "outputs/results/catalogue_fields_v32_2026-11-11"
VERSION = "gaz-v32.1-2026-11-11"
S = r"[\s\-]*"          # flexible separator inside product names (space, newline, hyphen)
R = r"\s*(?:®|™|\(R\)|R⃝)?\s*"   # optional trademark sign

PLATFORM = [
    # --- Illumina ----------------------------------------------------------------------------------------------------
    ("Illumina", "NovaSeq X", r"Nova" + S + r"Seq" + R + S + r"X(?:\s*Plus)?\b"),
    ("Illumina", "NovaSeq 6000", r"Nova" + S + r"Seq" + R + S + r"6000"),
    ("Illumina", "NovaSeq", r"Nova" + S + r"Seq"),
    ("Illumina", "HiSeq X", r"Hi" + S + r"Seq" + R + S + r"X(?:\s*(?:Ten|10|Five))?\b"),
    ("Illumina", "HiSeq 4000", r"Hi" + S + r"Seq" + R + S + r"4000"),
    ("Illumina", "HiSeq 3000", r"Hi" + S + r"Seq" + R + S + r"3000"),
    ("Illumina", "HiSeq 2500", r"Hi" + S + r"Seq" + R + S + r"2500"),
    ("Illumina", "HiSeq 2000", r"Hi" + S + r"Seq" + R + S + r"2000"),
    ("Illumina", "HiSeq 1500", r"Hi" + S + r"Seq" + R + S + r"1500"),
    ("Illumina", "HiSeq 1000", r"Hi" + S + r"Seq" + R + S + r"1000"),
    ("Illumina", "HiSeq", r"Hi" + S + r"Seq"),
    ("Illumina", "NextSeq 2000", r"Next" + S + r"Seq" + R + S + r"2000"),
    ("Illumina", "NextSeq 1000", r"Next" + S + r"Seq" + R + S + r"1000"),
    ("Illumina", "NextSeq 550", r"Next" + S + r"Seq" + R + S + r"550"),
    ("Illumina", "NextSeq 500", r"Next" + S + r"Seq" + R + S + r"500"),
    ("Illumina", "NextSeq", r"Next" + S + r"Seq"),
    ("Illumina", "MiniSeq", r"Mini" + S + r"Seq"),
    ("Illumina", "MiSeq", r"Mi" + S + r"Seq"),
    ("Illumina", "iSeq 100", r"\biSeq" + R + S + r"(?:100)?\b"),
    ("Illumina", "Genome Analyzer IIx", r"Genome\s+Analy[sz]er(?:\s*II\s*x|\s*IIx|\s*II)?|\bGA\s*II\s*x\b|\bGAIIx\b"),
    ("Illumina", "HiScanSQ", r"HiScan" + S + r"SQ"),
    ("Illumina", "", r"\bIllumina\b"),                                   # family-level; context required
    # --- Ion Torrent (Thermo Fisher) ---------------------------------------------------------------------------------
    ("Ion Torrent", "Ion GeneStudio S5", r"Ion\s+GeneStudio\s+S5(?:\s*(?:XL|Plus|Prime))?"),
    ("Ion Torrent", "Ion S5", r"Ion" + R + r"\s*(?:Torrent\s+)?S5(?:\s*XL)?\b"),
    ("Ion Torrent", "Ion Proton", r"Ion" + R + r"\s*(?:Torrent\s+)?Proton"),
    ("Ion Torrent", "Ion PGM", r"(?:Ion" + R + r"\s*(?:Torrent\s+)?)?(?:Personal\s+Genome\s+Machine|\bPGM\b)"),
    ("Ion Torrent", "Genexus", r"\bGenexus\b"),
    ("Ion Torrent", "", r"Ion" + S + r"Torrent"),
    # --- PacBio ------------------------------------------------------------------------------------------------------
    ("PacBio", "Revio", r"\bRevio\b"),
    ("PacBio", "Sequel IIe", r"\bSequel" + R + r"\s*II\s*e\b|\bSequel\s*IIe\b"),
    ("PacBio", "Sequel II", r"\bSequel" + R + r"\s*II\b"),
    ("PacBio", "Sequel", r"\bSequel\b", True),                        # case-sensitive: "sequel" is an English word
    ("PacBio", "RS II", r"\b(?:PacBio\s+|Pacific\s+Biosciences\s+)?RS\s*II\b"),
    ("PacBio", "", r"\bPac\s*Bio\b|Pacific\s+Biosciences"),
    # --- Oxford Nanopore ---------------------------------------------------------------------------------------------
    ("Oxford Nanopore", "PromethION", r"Prometh\s*ION"),
    ("Oxford Nanopore", "GridION", r"Grid\s*ION"),
    ("Oxford Nanopore", "MinION", r"Min\s*ION"),
    ("Oxford Nanopore", "Flongle", r"\bFlongle\b"),
    ("Oxford Nanopore", "", r"Oxford\s+Nanopore|\bnanopore\s+sequenc\w*"),
    # --- BGI / MGI ---------------------------------------------------------------------------------------------------
    ("BGI/MGI", "DNBSEQ-T7", r"DNBSEQ" + S + r"T7"),
    ("BGI/MGI", "DNBSEQ-G400", r"DNBSEQ" + S + r"G400"),
    ("BGI/MGI", "DNBSEQ-G99", r"DNBSEQ" + S + r"G99"),
    ("BGI/MGI", "DNBSEQ", r"DNBSEQ|DNB" + S + r"seq"),
    ("BGI/MGI", "MGISEQ-2000", r"MGISEQ" + S + r"2000|MGI\s*2000"),
    ("BGI/MGI", "BGISEQ-500", r"BGISEQ" + S + r"500"),
    ("BGI/MGI", "BGISEQ", r"BGISEQ"),
    ("BGI/MGI", "", r"\bBGI\b|\bMGI\b"),                                # family-level; context required
    # --- Roche 454 ---------------------------------------------------------------------------------------------------
    ("Roche 454", "GS FLX", r"\bGS" + S + r"FLX(?:\s*\+|\s+Titanium|\s+Plus|\+)?"),
    ("Roche 454", "GS Junior", r"\bGS\s+Junior"),
    ("Roche 454", "GS 20", r"\bGS\s*20\b"),
    ("Roche 454", "", r"\b454\b|\bpyrosequenc\w*"),                     # family-level; context required
    # --- Sanger / capillary ------------------------------------------------------------------------------------------
    ("Sanger/capillary", "ABI 3730", r"(?:ABI|Applied\s+Biosystems)\s*(?:PRISM\s*)?3730\s*(?:xl|XL)?|\b3730\s*xl\b"),
    ("Sanger/capillary", "ABI 3130", r"(?:ABI|Applied\s+Biosystems)\s*(?:PRISM\s*)?3130\s*(?:xl|XL)?"),
    ("Sanger/capillary", "ABI 3500", r"(?:ABI|Applied\s+Biosystems)\s*(?:PRISM\s*)?3500\s*(?:xl|XL)?"),
    ("Sanger/capillary", "", r"\bSanger\s+sequenc\w*|capillary\s+(?:electrophoresis\s+)?sequenc\w*"),
]

EXTRACTION = [
    # --- Qiagen QIAamp -----------------------------------------------------------------------------------------------
    ("Qiagen", "QIAamp Fast DNA Stool Mini Kit", r"(?:QIA" + S + r"amp|Qiagen)" + R + r"\s*Fast\s+DNA\s+Stool\s+Mini|\bFast\s+DNA\s+Stool\s+Mini"),
    ("Qiagen", "QIAamp PowerFecal Pro DNA Kit", r"QIA" + S + r"amp" + R + r"\s*Power" + S + r"Fecal" + R + r"\s*Pro"),
    ("Qiagen", "QIAamp PowerFecal DNA Kit", r"QIA" + S + r"amp" + R + r"\s*Power" + S + r"Fecal"),
    ("Qiagen", "QIAamp DNA Stool Mini Kit", r"(?:QIA" + S + r"amp|Qiagen)" + R + r"\s*(?:DNA\s+)?Stool\s+(?:DNA\s+)?Mini|\bDNA\s+Stool\s+Mini\s+Kit"),
    ("Qiagen", "QIAamp UCP Pathogen Mini Kit", r"QIA" + S + r"amp" + R + r"\s*(?:UCP\s+)?Pathogen"),
    ("Qiagen", "QIAamp DNA Microbiome Kit", r"QIA" + S + r"amp" + R + r"\s*DNA\s+Microbiome"),
    ("Qiagen", "QIAamp DNA Mini Kit", r"QIA" + S + r"amp" + R + r"\s*DNA\s+Mini"),
    ("Qiagen", "QIAamp DNA Blood Mini Kit", r"QIA" + S + r"amp" + R + r"\s*(?:DNA\s+)?Blood\s+Mini"),
    ("Qiagen", "cador Pathogen Kit", r"\bcador\s+Pathogen"),
    ("Qiagen", "QIAamp (kit not specified)", r"\bQIA" + S + r"amp\b"),
    # --- Qiagen / MO BIO Power* line ---------------------------------------------------------------------------------
    ("Qiagen/MO BIO", "DNeasy PowerSoil Pro Kit", r"Power" + S + r"Soil" + R + r"\s*Pro\b"),
    ("Qiagen/MO BIO", "PowerLyzer PowerSoil DNA Isolation Kit", r"Power" + S + r"Ly[sz]er"),
    ("Qiagen/MO BIO", "MagAttract PowerSoil / PowerMicrobiome Kit", r"MagAttract" + R + r"\s*Power" + S + r"(?:Soil|Microbiome)"),
    ("Qiagen/MO BIO", "PowerMag Soil / Microbiome Kit", r"Power" + S + r"Mag\b"),
    ("Qiagen/MO BIO", "PowerMax Soil DNA Isolation Kit", r"Power" + S + r"Max" + R + r"\s*Soil"),
    ("Qiagen/MO BIO", "PowerSoil DNA Isolation Kit", r"(?:DNeasy" + R + r"\s*)?Power" + S + r"Soil(?:" + S + r"htp)?"),
    ("Qiagen/MO BIO", "PowerFecal DNA Isolation Kit", r"(?:DNeasy" + R + r"\s*)?Power" + S + r"Fecal(?:" + R + r"\s*Pro)?"),
    ("Qiagen/MO BIO", "PowerMicrobiome RNA/DNA Kit", r"Power" + S + r"Microbiome"),
    ("Qiagen/MO BIO", "PowerFood Microbial DNA Isolation Kit", r"Power" + S + r"Food"),
    ("Qiagen/MO BIO", "UltraClean DNA Isolation Kit", r"Ultra" + S + r"Clean(?:" + R + r"\s*(?:Fecal|Soil|Microbial))?"),
    ("Qiagen", "DNeasy Blood & Tissue Kit", r"DNeasy" + R + r"\s*Blood\s*(?:&|and)\s*Tissue"),
    ("Qiagen", "AllPrep DNA/RNA Kit", r"AllPrep" + R + r"\s*(?:Power" + S + r"Fecal\s+)?DNA"),
    ("Qiagen", "MagAttract DNA Kit", r"MagAttract"),
    ("Qiagen", "DNeasy (kit not specified)", r"\bDNeasy\b"),
    ("Qiagen/MO BIO", "MO BIO kit (not specified)", r"\bMo\s*Bio\b"),
    ("Qiagen", "QIAcube (automated extraction)", r"QIA" + S + r"cube"),
    # --- Zymo --------------------------------------------------------------------------------------------------------
    ("Zymo Research", "ZymoBIOMICS DNA Kit", r"Zymo" + S + r"BIOMICS" + R + r"(?:\s*96)?(?:\s*Mag" + S + r"Bead)?\s*DNA"),
    ("Zymo Research", "Quick-DNA Fecal/Soil Microbe Kit", r"Quick" + S + r"DNA" + R + r"\s*(?:Fecal|Faecal)\s*/\s*Soil"),
    ("Zymo Research", "Zymo Fecal DNA Kit", r"(?:Zymo\w*(?:\s+Research)?\s+)(?:Fecal|Faecal)\s+DNA"),
    ("Zymo Research", "ZymoBIOMICS (kit not specified)", r"Zymo" + S + r"BIOMICS"),
    # --- MP Biomedicals ----------------------------------------------------------------------------------------------
    ("MP Biomedicals", "FastDNA SPIN Kit for Soil", r"Fast" + S + r"DNA" + R + r"\s*(?:SPIN\s+)?(?:Kit\s+)?for\s+Soil"),
    ("MP Biomedicals", "FastDNA SPIN Kit for Feces", r"Fast" + S + r"DNA" + R + r"\s*(?:SPIN\s+)?(?:Kit\s+)?for\s+Fe[ac]?ces"),
    ("MP Biomedicals", "FastDNA SPIN Kit", r"Fast" + S + r"DNA" + R + r"\s*(?:SPIN|Pro)"),
    # --- other vendors -----------------------------------------------------------------------------------------------
    ("Promega", "Maxwell RSC / 16 (automated)", r"Maxwell" + R + r"\s*(?:RSC|16)?"),
    ("Promega", "Wizard Genomic DNA Purification Kit", r"Wizard" + R + r"\s*(?:SV\s+)?Genomic"),
    ("Thermo Fisher", "PureLink Microbiome / Genomic DNA Kit", r"PureLink" + R + r"\s*(?:Microbiome|Genomic)?"),
    ("Thermo Fisher", "MagMAX Microbiome / Pathogen Kit", r"Mag" + S + r"MAX"),
    ("Thermo Fisher", "GeneJET Genomic DNA Kit", r"GeneJET"),
    ("Omega Bio-tek", "E.Z.N.A. Stool / Soil DNA Kit", r"E\.?\s*Z\.?\s*N\.?\s*A\.?" + R),
    ("Omega Bio-tek", "Mag-Bind DNA Kit", r"Mag" + S + r"Bind"),
    ("PerkinElmer", "Chemagic (automated)", r"\bchemagic"),
    ("Roche", "MagNA Pure (automated)", r"Mag\s*NA\s*Pure"),
    ("Roche", "High Pure PCR Template Preparation Kit", r"High\s+Pure\s+PCR\s+Template"),
    ("Macherey-Nagel", "NucleoSpin Soil / DNA Stool Kit", r"Nucleo" + S + r"Spin" + R + r"\s*(?:Soil|DNA\s+Stool|Tissue|Food)"),
    ("Macherey-Nagel", "NucleoMag DNA Kit", r"NucleoMag"),
    ("Stratec/Invitek", "PSP Spin Stool DNA Kit", r"PSP" + R + r"\s*Spin\s+Stool"),
    ("Stratec/Invitek", "InviMag Stool DNA Kit", r"InviMag"),
    ("AGOWA", "AGOWA mag Mini DNA Isolation Kit", r"AGOWA" + R + r"\s*mag"),
    ("Sigma-Aldrich", "GenElute Genomic DNA Kit", r"GenElute"),
    ("Norgen", "Norgen Stool DNA Isolation Kit", r"\bNorgen\b"),
    ("TIANGEN", "TIANamp Stool / Bacteria DNA Kit", r"TIANamp"),
    ("Bio Basic / other", "GNOME DNA Isolation Kit", r"\bGNOME\b" + R + r"\s*DNA"),
    ("iNtRON", "G-spin Genomic DNA Kit", r"\bG" + S + r"spin\b"),
    ("Analytik Jena", "innuPREP Stool DNA Kit", r"innuPREP"),
    # --- protocols / method classes ----------------------------------------------------------------------------------
    ("Protocol", "IHMS SOP (protocol Q/H)", r"\bIHMS\b[^.]{0,40}?(?:SOP|protocol)\s*(?:\d+|[QH]\b)?|\bprotocol\s+Q\b"),
    ("Protocol", "Repeated bead beating plus column (RBB+C)", r"repeated\s+bead" + S + r"beat\w*|\bRBB\s*\+\s*C\b"),
    ("Protocol", "Godon et al. method", r"\bGodon\b"),
    ("Protocol", "Phenol-chloroform extraction", r"phenol\s*[\-–:/]?\s*chloroform"),
    ("Protocol", "CTAB extraction", r"\bCTAB\b"),
    ("Protocol", "Bead beating (mechanical lysis)", r"bead" + S + r"beat\w*|bead\s+mill\w*|FastPrep|TissueLyser|Precellys"),
]

# family-level patterns that are only accepted with a sequencing context in the same sentence (+-120 chars)
CONTEXT_REQUIRED = {("Illumina", ""), ("BGI/MGI", ""), ("Roche 454", "")}
SEQ_CONTEXT = re.compile(r"sequenc|platform|instrument|sequencer|\brun\b|pyrosequenc|Life\s+Sciences|Titanium", re.I)
# family-level Illumina mentions that name reagents, not the instrument ("Illumina adapters", "Illumina Nextera")
ILLUMINA_REAGENT = re.compile(r"\bIllumina" + R + r"\s*(?:adapt\w*|index\w*|indices|primer\w*|Nextera|TruSeq|librar\w*|barcod\w*|"
                              r"overhang|tag\w*|compatible|-compatible|protocol|PhiX|DNA\s+Prep)", re.I)


def compiled(table):
    out = []
    for e in table:
        fam, model, rx = e[:3]
        cs = len(e) > 3 and e[3]
        out.append((fam, model, re.compile(rx, 0 if cs else re.I)))
    return out


GAZ = {"sequencing_platform": compiled(PLATFORM), "dna_extraction_method": compiled(EXTRACTION)}


def match(field, text, base=0):
    """Non-overlapping gazetteer hits in text: list of dicts (family, model, start, end, surface, level). Priority: entry
    order (specific before generic), then longer span."""
    cands = []
    for prio, (fam, model, rx) in enumerate(GAZ[field]):
        for m in rx.finditer(text):
            a, b = m.start(), m.end()
            if b - a < 2:
                continue
            if field == "sequencing_platform" and (fam, model) in CONTEXT_REQUIRED:
                lo, hi = max(0, a - 120), min(len(text), b + 120)
                if not SEQ_CONTEXT.search(text[lo:hi]):
                    continue
                if fam == "Roche 454" and m.group(0) == "454" and not re.search(
                        r"Roche|Life\s+Sciences|pyrosequenc|GS\b|FLX|Titanium|454\s+(?:platform|sequenc)", text[lo:hi], re.I):
                    continue
                if fam == "Illumina" and ILLUMINA_REAGENT.match(text, a):
                    continue
            cands.append((prio, -(b - a), a, b, fam, model))
    cands.sort()
    taken, out = [], []
    for prio, _, a, b, fam, model in cands:
        if any(a < y and x < b for x, y in taken):
            continue
        taken.append((a, b))
        out.append({"family": fam, "model": model, "start": base + a, "end": base + b, "surface": text[a:b],
                    "level": "model" if model and "not specified" not in model else "family"})
    return sorted(out, key=lambda h: h["start"])


def canonical(field, family, model):
    """Display value for a (family, model) key."""
    if not model or "not specified" in model:
        return family if not model else model
    if field == "sequencing_platform" and family in ("Illumina", "PacBio", "Oxford Nanopore") and not model.startswith(family):
        return f"{family} {model}"
    if field == "sequencing_platform" and family == "Roche 454":
        return f"Roche 454 {model}"
    return model


def spec():
    tables = {"sequencing_platform": PLATFORM, "dna_extraction_method": EXTRACTION}
    out = {}
    for f, t in tables.items():
        entries = [{"family": e[0], "model": e[1], "regex": e[2], "case_sensitive": bool(len(e) > 3 and e[3]),
                    "context_required": f == "sequencing_platform" and (e[0], e[1]) in CONTEXT_REQUIRED} for e in t]
        body = {"field": f, "version": VERSION, "n_entries": len(entries),
                "n_families": len({e["family"] for e in entries}),
                "n_models": len({e["model"] for e in entries if e["model"] and "not specified" not in e["model"]}),
                "entries": entries}
        out[f] = body
    return out


def main():
    d = OUT / "gazetteers"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for f, body in spec().items():
        p = d / f"gazetteer_{f}.json"
        txt = json.dumps(body, indent=1, ensure_ascii=False) + "\n"
        p.write_text(txt, encoding="utf-8")
        sha = hashlib.sha256(txt.encode()).hexdigest()
        rows.append(f"{sha}  {p.name}")
        print(f, VERSION, body["n_entries"], "entries", body["n_families"], "families", body["n_models"], "models", sha[:12])
    (d / "GAZETTEERS.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
