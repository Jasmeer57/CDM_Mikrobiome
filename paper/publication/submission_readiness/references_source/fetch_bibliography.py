import json, time, urllib.request, xml.etree.ElementTree as ET
from datetime import date
VERIFY_DATE = date.today().isoformat()
REFS = [  # (key, role, identifier)
 ("abdill2025","R1","doi:10.1016/j.cell.2024.12.017"), ("leinonen2011","R2","doi:10.1093/nar/gkq1019"),
 ("goncalves2019","R3","doi:10.1038/sdata.2019.21"), ("geistlinger2023","R4","doi:10.1038/s41587-023-01872-y"),
 ("li2016bc5cdr","R5; corpus","doi:10.1093/database/baw068"), ("luo2022biored","R5; corpus","doi:10.1093/bib/bbac282"),
 ("sanger2024hunflair2","R5; tool","doi:10.1093/bioinformatics/btae564"), ("chen2025llmbench","R6","doi:10.1038/s41467-025-56989-2"),
 ("wei2024pubtator3","tool","doi:10.1093/nar/gkae235"), ("akbik2019flair","tool","doi:10.18653/v1/n19-4010"),
 ("neumann2019scispacy","tool","doi:10.18653/v1/w19-5034"), ("cohen2017craft","model training corpus","doi:10.1007/978-94-024-0881-2_53"),
 ("kim2004jnlpba","model training corpus","doi:10.3115/1567594.1567610"), ("pyysalo2015bionlp13","model training corpus","doi:10.1186/1471-2105-16-s10-s2"),
 ("lee2019biobert","base model","doi:10.1093/bioinformatics/btz682"), ("beltagy2019scibert","base model","doi:10.18653/v1/d19-1371"),
 ("zaratiana2024gliner","tool","doi:10.18653/v1/2024.naacl-long.300"), ("zaratiana2025gliner2","tool","doi:10.18653/v1/2025.emnlp-demos.10"),
 ("yazdani2026glinerbiomed","tool (see note)","doi:10.1093/bioinformatics/btag322"), ("kwon2023vllm","inference","doi:10.1145/3600006.3613165"),
 ("lin2023awq","quantisation","arxiv:2306.00978"), ("grattafiori2024llama3","LLM","arxiv:2407.21783"),
 ("jiang2023mistral","LLM","arxiv:2310.06825"), ("abdin2024phi3","LLM","arxiv:2404.14219"),
 ("guo2025deepseekr1","LLM","doi:10.1038/s41586-025-09422-z"), ("gemma2026gemma4","LLM","arxiv:2607.02770"),
 ("qwen35card","LLM (model card)","hf:Qwen/Qwen3.5-4B"),
 ("schoch2020taxonomy","vocabulary","doi:10.1093/database/baaa062"), ("brown2015gene","vocabulary","doi:10.1093/nar/gku1055"),
 ("davis2026ctd","vocabulary + KG","doi:10.1093/nar/gkag1041"), ("lipscomb2000mesh","vocabulary","pmid:10928714"),
 ("vasilevsky2022mondo","vocabulary","doi:10.1101/2022.04.13.22273750"), ("gargano2024hpo","vocabulary","doi:10.1093/nar/gkad1005"),
 ("janssens2018disbiome","KG","doi:10.1186/s12866-018-1197-5"), ("bodenreider2004umls","mapping service","doi:10.1093/nar/gkh061"),
 ("whetzel2011bioportal","mapping service","doi:10.1093/nar/gkr469"), ("cote2006ols","mapping service","doi:10.1186/1471-2105-7-97"),
 # 2026-11-08: routed via PMID 26262116 instead of doi:10.3233/978-1-61499-564-7-574.
 # The Crossref book-chapter record packs the whole name into 'family' ("Hripcsak
 # George") and carries no volume/pages; PubMed esummary has the correct author
 # list and vol 216, pp. 574-578 (Studies in Health Technology and Informatics).
 ("hripcsak2015ohdsi","standard (OMOP)","pmid:26262116"), ("yilmaz2011mixs","standard (MIxS)","doi:10.1038/nbt.1823"),
 ("efron1993bootstrap","statistics","doi:10.1007/978-1-4899-4541-9"), ("cohen1960kappa","statistics","doi:10.1177/001316446002000104"),
 # added 2026-11-07 (gaps found after the 3.0.3 audits)
 ("barrett2012bioproject","database (BioProject/BioSample)","doi:10.1093/nar/gkr1163"),
 ("wilson1927","statistics (Wilson interval)","doi:10.1080/01621459.1927.10502953"),
 ("zheng2023mtbench","LLM-as-a-judge (method)","arxiv:2306.05685"),
 ("deepseek2026v4","LLM (string-level judge, tech report)","arxiv:2606.19348"),
 ("deepseekv4flashcard","LLM string-level judge checkpoint (model card)","hf:deepseek-ai/DeepSeek-V4-Flash-0731"),
 ("deepseekv41card","LLM evidence-anchored judge (model card)","hf:deepseek-ai/DeepSeek-V4.1-Flash"),
 ("liu2019sbert","embedding method (G6/G7 triple-term links)","doi:10.18653/v1/d19-1410"),
 ("minilmcard","embedding model (G6/G7, model card)","hf:sentence-transformers/all-MiniLM-L6-v2"),
 ("ollama2026","LLM runtime (software)","gh:ollama/ollama"),
 # positioning block previously only in VERIFIED_REFERENCES.md (added 2026-11-03)
 ("langarica2025minerva","positioning (MINERVA)","doi:10.1093/bib/bbaf472"),
 ("chirumbolo2025minerva","positioning (comment)","doi:10.1093/bib/bbaf673"),
 ("langarica2025response","positioning (author reply)","doi:10.1093/bib/bbaf671"),
 ("hogan2024midred","positioning; annotated corpus","doi:10.18653/v1/2024.bionlp-1.31"),
 ("hong2025dimbre","positioning (DiMB-RE)","doi:10.1093/jamia/ocaf054"),
 ("higashi2024harmonization","positioning (metadata harmonisation preprint)","doi:10.1101/2024.10.26.620145"),
 # added 2026-11-08 (five user-supplied comparator references, verified via
 # Crossref + Europe PMC + PubMed esummary on 2026-11-08)
 ("lu2025microllm","positioning (MicroLLM: LLM+NER information extraction in microbiology)","doi:10.1093/bib/bbaf534"),
 ("li2025lore","positioning (LLM framework for disease-gene association prediction)","doi:10.1093/bib/bbaf070"),
 ("collins2026biotriplex","positioning (annotated corpus for gene-disease relation extraction)","doi:10.1093/bioinformatics/btag037"),
 ("patel2026microbialner","positioning (microbial NER and normalisation)","doi:10.1093/bioinformatics/btag418"),
 ("chen2026buffers","positioning (LLM-powered article extraction pipeline)","doi:10.1093/bib/bbag570"),
 # added 2026-11-09: CANDIDATES found by Claude Code web search, registry-verified below.
 # Authors decide whether to cite each one; uncited entries do not render (unsrt).
 ("liu2021sapbert","method used (SapBERT semantic match, BugSigDB comparison / Fig. 4)","doi:10.18653/v1/2021.naacl-main.334"),
 ("luoma2023s1000","candidate: corpus (S1000 species benchmark; only if S1000 is reported)","doi:10.1093/bioinformatics/btad369"),
 ("wilkinson2016fair","candidate: standard (FAIR principles; provenance / data model framing)","doi:10.1038/sdata.2016.18"),
 ("qi2023gutmdisorder","candidate: positioning (curated microbe-phenotype database)","doi:10.1093/nar/gkac871"),
 ("karkera2023microbiomere","candidate: positioning (language models for microbiome-disease relation mining)","doi:10.1186/s12859-023-05411-z"),
 ("microbiorel2025","candidate: positioning (generative relation extraction in the microbiome domain, preprint)","arxiv:2506.08647"),
 ("medjudge2026","candidate: LLM-as-a-judge reliability in healthcare (scoping review, preprint)","arxiv:2604.25933"),
]
def j(url): return json.load(urllib.request.urlopen(url, timeout=40))
out = []
ax = [i.split(":",1)[1] for _,_,i in REFS if i.startswith("arxiv:")]
root = ET.fromstring(urllib.request.urlopen("https://export.arxiv.org/api/query?id_list=" + ",".join(ax) + f"&max_results={len(ax)}", timeout=60).read())
ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
AX = {}
for e in root.findall("a:entry", ns):
    aid = e.find("a:id", ns).text.split("/abs/")[-1].split("v")[0]
    AX[aid] = {"title": " ".join(e.find("a:title", ns).text.split()), "authors": [x.find("a:name", ns).text.strip() for x in e.findall("a:author", ns)],
               "year": int(e.find("a:published", ns).text[:4]), "venue": "arXiv", "doi": f"10.48550/arXiv.{aid}", "url": f"https://arxiv.org/abs/{aid}", "registry": "arXiv API"}
for key, role, ident in REFS:
    kind, val = ident.split(":", 1)
    try:
        if kind == "doi":
            m = j(f"https://api.crossref.org/works/{val}")["message"]
            r = {"title": " ".join((m.get("title") or [""])[0].split()),
                 "authors": [" ".join([a.get("family")] + [" ".join("".join(w[0] for w in __import__("re").split("-", p) if w[:1].isalpha()) for p in (a.get("given") or "").replace(".", " ").split())]) if a.get("family") else a.get("name") for a in m.get("author", [])],
                 # 2026-11-08: prefer container-title (the journal). Crossref
                 # posted-content records (10.1101 preprints) have an EMPTY
                 # container-title and report publisher "openRxiv", with the
                 # real server (medRxiv / bioRxiv) in institution[0].name.
                 "venue": (m.get("container-title") or [None])[0]
                          or (m.get("institution") or [{"name": m.get("publisher", "")}])[0].get("name")
                          or m.get("publisher", ""),
                 "year": (m.get("issued", {}).get("date-parts") or [[None]])[0][0],
                 "volume": m.get("volume"), "issue": m.get("issue"), "pages": m.get("page") or m.get("article-number"), "doi": m["DOI"], "registry": "Crossref"}
            # strip Crossref inline markup (<i>...</i>, <sub>, <sup>...) and
            # re-collapse spacing left behind by removed tags, e.g.
            # "<i>BioTriplex</i> : a full-text..." -> "BioTriplex: a full-text..."
            r["title"] = __import__("re").sub(r"\s*:\s*", ": ", __import__("re").sub(r"<[^>]+>", "", r["title"]))
            time.sleep(0.2)
        elif kind == "arxiv":
            r = AX[val]
        elif kind == "pmid":
            s = j(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={val}&retmode=json")["result"][val]
            r = {"title": s["title"].rstrip("."), "authors": [a["name"] for a in s["authors"]], "venue": s["fulljournalname"], "year": int(s["pubdate"][:4]),
                 "volume": s["volume"], "issue": s["issue"], "pages": s["pages"], "pmid": val,
                  # 2026-11-08: keep the DOI from the registry record so the
                  # generated .bib can still link doi.org (Crossref route set it).
                 "doi": next((i["value"] for i in s["articleids"] if i["idtype"] == "doi"), None),
                 "pmcid": next((i["value"] for i in s["articleids"] if i["idtype"] == "pmc"), None), "registry": "PubMed"}
            if not r["doi"]:
                # 2026-11-08: PubMed esummary has no idtype "doi" for some
                # records (e.g. 26262116); fall back to Europe PMC so the .bib
                # keeps a doi.org link. Still registry-only, never from memory.
                try:
                    epm = j(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:{val}%20SRC:MED&format=json&pageSize=1")
                    hits = epm.get("resultList", {}).get("result") or []
                    if hits and hits[0].get("doi"):
                        r["doi"] = hits[0]["doi"]
                except Exception:
                    pass
        elif kind == "hf":
            m = j(f"https://huggingface.co/api/models/{val}")
            r = {"title": f"{val} (model card)", "authors": [val.split('/')[0]], "venue": "Hugging Face", "year": None, "url": f"https://huggingface.co/{val}",
                 "last_modified": m.get("lastModified"), "registry": "Hugging Face API"}
        elif kind == "gh":
            m = j(f"https://api.github.com/repos/{val}")
            r = {"title": f"{val} (software repository)", "authors": [m["owner"]["login"]], "venue": "GitHub", "year": int(m["created_at"][:4]),
                 "url": m["html_url"], "license": (m.get("license") or {}).get("spdx_id"), "registry": "GitHub API"}
        r.update(key=key, role=role, identifier=ident, verified=VERIFY_DATE)
    except Exception as e:
        r = {"key": key, "role": role, "identifier": ident, "error": repr(e)[:150]}
    out.append(r)
    print(key, "|", r.get("title", r.get("error"))[:80], "|", r.get("venue"), r.get("year"))
json.dump(out, open("bibliography.json", "w"), indent=1, ensure_ascii=False)
