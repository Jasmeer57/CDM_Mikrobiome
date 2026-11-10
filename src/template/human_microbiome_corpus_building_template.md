# Human Microbiome Full-Text Corpus: Building Template

**Purpose:** Build a traceable, quality-controlled corpus from 453 human microbiome full-text papers.

**Corpus size:** 453 paper records  
**ID range:** `HMPAPER_000001`–`HMPAPER_000453`  
**Schema version:** `1.0.0`  
**Project owner:** `[name/team]`  
**Last updated:** `[YYYY-MM-DD]`

---

## 1. Corpus architecture

Organize the corpus into three connected layers.

1. **Document layer:** bibliographic metadata, source files, full text, sections, tables, figures, references, source provenance and reuse license.
2. **Study layer:** population, study design, participant/sample counts, body sites, assays, sequencing, bioinformatics, statistics and data accessions.
3. **Evidence layer:** individual reported findings, exact supporting text, evidence location, reported statistics, extraction provenance and verification status.

One paper may contain multiple cohorts, experiments, body sites, or findings. Do not force all information into one flat record.

## 2. Corpus-wide tracking table

Use one row per paper. The `corpus_id` values below are the stable identifiers for all 453 records. Fill other fields as each paper is processed.

| Corpus ID | Title | DOI / PMID / PMCID | Year | Source / file path | Inclusion decision | Processing status | Full-text status | Annotation status | Reviewer / notes |
|---|---|---|---|---|---|---|---|---|---|
| `HMPAPER_000001` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000002` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000003` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000004` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000005` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000006` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000007` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000008` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000009` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000010` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000011` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000012` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000013` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000014` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000015` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000016` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000017` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000018` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000019` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000020` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000021` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000022` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000023` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000024` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000025` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000026` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000027` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000028` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000029` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000030` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000031` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000032` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000033` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000034` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000035` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000036` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000037` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000038` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000039` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000040` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000041` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000042` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000043` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000044` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000045` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000046` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000047` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000048` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000049` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000050` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000051` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000052` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000053` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000054` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000055` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000056` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000057` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000058` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000059` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000060` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000061` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000062` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000063` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000064` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000065` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000066` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000067` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000068` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000069` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000070` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000071` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000072` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000073` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000074` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000075` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000076` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000077` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000078` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000079` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000080` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000081` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000082` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000083` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000084` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000085` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000086` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000087` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000088` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000089` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000090` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000091` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000092` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000093` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000094` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000095` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000096` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000097` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000098` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000099` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000100` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000101` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000102` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000103` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000104` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000105` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000106` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000107` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000108` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000109` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000110` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000111` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000112` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000113` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000114` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000115` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000116` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000117` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000118` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000119` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000120` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000121` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000122` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000123` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000124` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000125` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000126` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000127` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000128` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000129` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000130` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000131` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000132` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000133` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000134` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000135` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000136` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000137` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000138` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000139` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000140` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000141` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000142` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000143` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000144` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000145` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000146` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000147` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000148` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000149` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000150` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000151` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000152` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000153` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000154` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000155` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000156` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000157` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000158` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000159` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000160` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000161` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000162` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000163` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000164` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000165` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000166` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000167` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000168` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000169` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000170` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000171` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000172` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000173` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000174` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000175` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000176` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000177` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000178` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000179` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000180` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000181` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000182` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000183` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000184` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000185` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000186` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000187` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000188` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000189` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000190` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000191` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000192` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000193` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000194` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000195` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000196` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000197` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000198` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000199` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000200` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000201` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000202` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000203` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000204` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000205` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000206` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000207` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000208` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000209` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000210` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000211` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000212` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000213` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000214` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000215` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000216` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000217` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000218` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000219` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000220` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000221` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000222` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000223` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000224` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000225` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000226` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000227` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000228` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000229` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000230` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000231` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000232` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000233` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000234` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000235` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000236` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000237` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000238` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000239` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000240` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000241` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000242` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000243` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000244` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000245` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000246` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000247` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000248` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000249` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000250` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000251` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000252` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000253` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000254` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000255` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000256` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000257` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000258` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000259` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000260` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000261` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000262` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000263` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000264` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000265` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000266` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000267` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000268` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000269` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000270` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000271` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000272` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000273` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000274` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000275` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000276` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000277` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000278` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000279` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000280` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000281` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000282` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000283` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000284` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000285` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000286` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000287` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000288` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000289` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000290` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000291` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000292` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000293` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000294` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000295` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000296` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000297` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000298` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000299` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000300` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000301` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000302` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000303` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000304` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000305` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000306` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000307` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000308` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000309` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000310` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000311` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000312` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000313` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000314` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000315` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000316` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000317` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000318` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000319` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000320` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000321` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000322` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000323` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000324` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000325` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000326` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000327` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000328` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000329` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000330` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000331` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000332` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000333` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000334` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000335` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000336` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000337` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000338` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000339` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000340` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000341` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000342` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000343` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000344` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000345` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000346` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000347` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000348` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000349` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000350` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000351` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000352` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000353` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000354` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000355` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000356` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000357` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000358` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000359` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000360` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000361` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000362` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000363` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000364` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000365` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000366` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000367` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000368` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000369` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000370` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000371` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000372` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000373` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000374` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000375` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000376` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000377` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000378` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000379` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000380` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000381` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000382` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000383` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000384` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000385` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000386` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000387` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000388` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000389` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000390` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000391` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000392` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000393` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000394` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000395` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000396` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000397` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000398` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000399` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000400` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000401` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000402` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000403` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000404` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000405` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000406` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000407` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000408` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000409` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000410` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000411` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000412` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000413` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000414` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000415` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000416` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000417` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000418` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000419` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000420` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000421` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000422` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000423` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000424` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000425` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000426` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000427` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000428` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000429` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000430` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000431` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000432` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000433` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000434` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000435` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000436` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000437` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000438` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000439` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000440` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000441` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000442` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000443` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000444` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000445` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000446` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000447` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000448` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000449` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000450` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000451` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000452` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |
| `HMPAPER_000453` | | | | | `pending` | `not_started` | `not_checked` | `not_started` | |

### Standard status values

- **Processing:** `not_started`, `source_acquired`, `text_extracted`, `automated_checks_passed`, `manual_review_passed`, `needs_repair`, `excluded`
- **Full-text completeness:** `not_checked`, `complete`, `partial`, `failed`, `not_applicable`
- **Annotation:** `not_started`, `in_progress`, `extracted_unverified`, `human_verified`, `needs_revision`
- **Inclusion decision:** `pending`, `include`, `exclude`

Use a blank or `null` for information not yet extracted. Use `not_reported` only after checking the source and confirming that the paper does not report the information. Use `not_applicable` only when the field does not apply.

---

## 3. Individual paper record template

Copy this section for each paper, replacing `HMPAPER_000001` with its assigned ID. It is fine to store each copied record in a separate `.md` file, while keeping this master template as the specification.

# Paper Record: `HMPAPER_000001`

### A. Record control

- **Corpus ID:** `HMPAPER_000001`
- **Schema version:** `1.0.0`
- **Processing status:** `not_started`
- **Full-text completeness:** `not_checked`
- **Annotation status:** `not_started`
- **Reviewer:** 
- **Review date:** 
- **Curation notes:** 

### B. Publication metadata

- **Title:** 
- **DOI:** 
- **PMID:** 
- **PMCID:** 
- **Authors:** 
- **Journal:** 
- **Publication year:** 
- **Publication type:** `primary_research` / `review` / `protocol` / `other`
- **Language:** 
- **Abstract:** 
- **Keywords:** 

### C. Source and file provenance

- **Source database/repository:** 
- **Source URL:** 
- **Retrieval date:** `YYYY-MM-DD`
- **License name:** 
- **License URL:** 
- **Reuse permission checked:** `yes` / `no` / `unclear`
- **Original PDF path:** 
- **Original XML path:** 
- **Extracted text path:** 
- **Supplementary file paths:** 
- **Original file SHA-256:** 
- **Extraction tool and version:** 
- **Extraction date:** 
- **Text version ID/checksum:** 

### D. Eligibility and relevance

- **Human microbiome relevance:** `yes` / `no` / `unclear`
- **Inclusion decision:** `include` / `exclude` / `pending`
- **Inclusion reason(s):** 
- **Exclusion reason(s):** 
- **Protocol version applied:** 
- **Duplicate/canonical record ID, if applicable:** 

### E. Full-text integrity checks

- **Title matches source:** `pass` / `fail` / `not_checked`
- **Abstract matches source:** `pass` / `fail` / `not_checked` / `not_available`
- **Body text completeness:** `complete` / `partial` / `failed` / `not_checked`
- **Section hierarchy preserved:** `yes` / `no` / `not_checked`
- **Tables checked:** `yes` / `no` / `not_applicable`
- **Figure captions checked:** `yes` / `no` / `not_applicable`
- **Supplementary materials checked:** `yes` / `no` / `unavailable` / `not_applicable`
- **References retained:** `yes` / `no` / `not_checked`
- **Known extraction problems:** 

### F. Full-text section inventory

Add or remove rows to reflect the actual paper. Preserve nested section hierarchy; do not force every article to use identical headings.

| Section ID | Heading | Heading path | Order | Text path/reference | Checked |
|---|---|---|---:|---|---|
| `sec_001` | Introduction | Introduction | 1 | | `no` |
| `sec_002` | Methods | Methods | 2 | | `no` |
| `sec_003` | Results | Results | 3 | | `no` |
| `sec_004` | Discussion | Discussion | 4 | | `no` |

### G. Study metadata

Create a separate study block for each distinct cohort, experiment, or analysis when necessary.

#### Study ID: `HMPAPER_000001_STUDY_001`

- **Study design:** 
- **Research question/objective:** 
- **Country/region:** 
- **Recruitment setting:** 
- **Population description:** 
- **Number of participants (reported):** 
- **Number of biological samples (reported):** 
- **Number of technical replicates (reported):** 
- **Number of time points (reported):** 
- **Age information:** 
- **Sex/gender information as reported:** 
- **Health conditions:** 
- **Exposures/interventions:** 
- **Comparator/control group:** 
- **Eligibility criteria:** 
- **Confounders/covariates reported:** 
- **Limitations reported by authors:** 

#### Microbiome sampling and laboratory methods

- **Body site(s):** 
- **Specimen type(s):** 
- **Collection method:** 
- **Collection time point(s):** 
- **Storage/transport conditions:** 
- **DNA/RNA extraction method:** 
- **Assay type:** `16S` / `shotgun_metagenomics` / `metatranscriptomics` / `metabolomics` / `culture` / `other`
- **Sequencing platform:** 
- **Target gene/region:** 
- **Negative/positive controls:** 
- **Contamination handling:** 
- **Taxonomic profiling method:** 
- **Taxonomic database and version:** 
- **Functional profiling method:** 
- **Quality filtering and normalization:** 
- **Statistical methods:** 
- **Multiple-testing correction:** 
- **Software/pipeline and version:** 
- **Data accessions (BioProject/BioSample/SRA/other):** 
- **Code/data availability:** 

### H. Findings index

List every extracted finding as a separate record in the findings section below or in a separate file. A paper may have zero, one, or many findings. Include relevant null and contradictory findings; do not extract only positive associations.

| Finding ID | Study ID | Short description | Evidence locator | Extraction status | Verification status |
|---|---|---|---|---|---|
| `HMPAPER_000001_FIND_001` | `HMPAPER_000001_STUDY_001` | | | `not_started` | `pending` |

### I. Paper-level final review checklist

- [ ] Bibliographic identifiers checked
- [ ] Duplicate status resolved or documented
- [ ] Source and license information recorded
- [ ] Full text checked against source
- [ ] Sections, tables, figure captions and supplements checked or explicitly marked
- [ ] Participant counts distinguished from sample counts
- [ ] Reported facts distinguished from missing information
- [ ] Every finding has a stable ID and study link
- [ ] Evidence text and locator verified against the correct text version
- [ ] Reviewer and review date recorded
- [ ] Remaining limitations documented

**Final paper status:** `pending`

---

## 4. Finding-level record template

Use one record per distinct scientific result, not one record per paper. Preserve original wording and store normalized terminology separately.

### Finding: `HMPAPER_000001_FIND_001`

- **Finding ID:** `HMPAPER_000001_FIND_001`
- **Corpus ID:** `HMPAPER_000001`
- **Study ID:** `HMPAPER_000001_STUDY_001`
- **Claim type:** `result` / `null_result` / `author_interpretation` / `other`
- **Body site (original wording):** 
- **Body site (normalized):** 
- **Population/subgroup:** 
- **Exposure or comparison:** 
- **Outcome:** 
- **Taxon (original wording):** 
- **Taxon (normalized):** 
- **Taxonomic rank:** 
- **Microbial function/pathway:** 
- **Association direction:** `increased` / `decreased` / `no_association_reported` / `mixed` / `unclear`
- **Direction refers to:** 
- **Effect measure:** 
- **Effect estimate:** 
- **P-value:** 
- **Q-value / adjusted p-value:** 
- **Confidence interval:** 
- **Adjusted covariates:** 
- **Evidence text (exact quote or table evidence):** 
- **Evidence section ID:** 
- **Evidence locator type:** `section` / `table` / `figure` / `supplement` / `page` / `other`
- **Evidence locator:** 
- **Text version ID:** 
- **Extraction method:** `manual` / `automated` / `hybrid`
- **Extractor/model and version:** 
- **Confidence scale and value (if defined):** 
- **Verification status:** `pending` / `verified` / `rejected` / `needs_revision`
- **Reviewer:** 
- **Review date:** 
- **Notes:** 

### Evidence locator rule

Do not store offsets without documenting whether they refer to original XML, PDF page coordinates, the full extracted text, section-local text, or a chunk. Validate that the evidence can be recovered from the referenced text version. Store exact evidence text and a stable section/table identifier as well as offsets where possible.

Do not infer effect estimates or statistics that the paper does not report. Distinguish association from causation.

---

## 5. Extraction and curation log

Use one row per processing or review event.

| Corpus ID | Date | Stage | Tool/person | Tool version | Action/check | Result | Problem found | Resolution |
|---|---|---|---|---|---|---|---|---|
| `HMPAPER_000001` | `YYYY-MM-DD` | text extraction | | | | `pending` | | |

Recommended stages: `acquisition`, `metadata`, `text_extraction`, `section_validation`, `table_review`, `study_annotation`, `finding_extraction`, `evidence_validation`, `final_review`.

---

## 6. Corpus inclusion protocol

Finalize the criteria before completing curation.

### Proposed inclusion criteria

- Human participants or human-derived microbiome samples.
- Study investigates the human-associated microbiome.
- Full text is accessible and contains usable content.
- Eligible methods are defined in advance (e.g., 16S, shotgun metagenomics, metatranscriptomics, metabolomics, culture-based methods).
- Language: `[specify]`.
- Publication years: `[specify]`.
- Sources/databases: `[specify]`.
- Publication types: primary research by default; reviews can be included in a separately labelled subset.

### Proposed exclusion criteria

- Animal-only studies without eligible human-derived samples.
- In-vitro-only studies outside the project's scope.
- Duplicate records after a canonical record is selected and linked.
- No usable full text after documented retrieval attempts.
- Out-of-scope papers.

Do not exclude a paper merely because its findings are null or not statistically significant.

### Decision fields

For each paper record `include`, `exclude`, or `pending`; document explicit reasons, reviewer, date, and any adjudication of disagreements.

---

## 7. Quality-control plan

### Document integrity
- [ ] Confirm source file exists and opens.
- [ ] Compare extracted title and abstract against the source.
- [ ] Check for missing, duplicated, garbled, or truncated sections.
- [ ] Inspect tables, figure captions and supplementary files.
- [ ] Confirm text section order and hierarchy.
- [ ] Record extraction tool/version and file checksum.

### Annotation integrity
- [ ] Check that each finding belongs to the correct paper and study.
- [ ] Confirm taxon, body site, exposure/comparison and outcome against the source.
- [ ] Validate evidence text and locator against the exact text version.
- [ ] Verify statistical values and units without silently transforming them.
- [ ] Keep author-reported results separate from background claims and interpretation.
- [ ] Record human verification status.

### Corpus-level reporting
Report counts with denominators for:
- Papers acquired, extracted, checked, passed, repaired and excluded.
- Missing title, abstract, DOI and other identifier rates.
- Duplicate identifier groups.
- Full-text completeness rate.
- Tables and supplements checked.
- Findings extracted and human-verified.
- Evidence locator validity rate.
- Accuracy against a manually reviewed gold-standard subset, when available.

A schema-valid record is not necessarily scientifically correct. Do not describe the corpus as validated until annotation accuracy has been evaluated.

---

## 8. Recommended workflow for the 453 papers

1. Freeze and version the inclusion protocol.
2. Assign the 453 stable corpus IDs in the tracking table.
3. Inventory source files, identifiers, licenses and duplicate records.
4. Preserve original files and checksums.
5. Extract full text and retain section hierarchy.
6. Run automated structural checks and record failures.
7. Manually inspect a stratified sample, then prioritize records with extraction warnings.
8. Extract study metadata, keeping participants, samples, replicates and time points separate.
9. Extract findings as individual records linked to a study and evidence passage.
10. Validate locators against the exact text version.
11. Track unresolved issues rather than silently guessing.
12. Publish a versioned quality report describing what was and was not validated.

## 9. Core principle

Build a corpus that can answer both:

- “What does this paper say?”
- “What exact evidence supports this microbiome finding?”

A folder of PDFs or flattened text files may support reading, but reliable search, knowledge graphs, systematic evidence synthesis and reproducible text mining require stable identifiers, structured study metadata, evidence-level records and documented quality checks.
