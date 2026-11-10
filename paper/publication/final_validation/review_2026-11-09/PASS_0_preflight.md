# PASS 0 — Pre-flight (2026-11-09)

Auditor-mode, read-only. All writes confined to `review_2026-11-09/`.
Working copy of extracted PDF text: `_work/m_pdf.txt` (derived from the built PDF; no
paper-text sources were opened at any point).

## Manuscript location (input placeholder was unfilled)

`MANUSCRIPT_PATH = paper/publication/manuscript/` **does not exist**. Candidates found:

| Candidate | Format | Modified | Role |
|---|---|---|---|
| `oup-authoring-template/manuscript.tex` (+ built `manuscript.pdf`, 7 pp) | LaTeX | 2026-11-08 10:18 / 10:28 | **Assumed authoritative** — the OUP submission copy (BiB Problem Solving Protocol), same tree the claims register was built against |
| `paper/manuscript/manuscript.md` | Markdown | 2026-10-28 | Superseded draft (historical-only 444 build language) — swept for do-not-cite numbers anyway |
| `paper/publication/manuscript_bib/main.tex`, `paper/publication/manuscript_draft/*` | LaTeX / MD | older | Earlier drafts, not re-checked in Pass 0 |

**Please confirm the tex is the review target** (Question 1). All findings below are
against `oup-authoring-template/manuscript.tex` + its built PDF.

## 0a. Frozen DB checksum — **PASS**

```
sha256: 5d23ba87d29ac7a6de831e66b35c0f42bc10312132cf20dd0191526b8b041e3e
```
Matches the expected `5d23ba87` prefix exactly. Opened strictly via
`file:...?mode=ro&immutable=1` + `PRAGMA query_only=ON`; no writes attempted.

## 0b. Frozen DB contents, derived from `sqlite_master` + `COUNT(*)` per table — **PASS (all items)**

| Expected (ground truth) | Observed (derived) | Status |
|---|---|---|
| 44 tables | 44 tables | PASS |
| 8,490,496 rows total | 8,490,496 (sum of per-table COUNT(*)) | PASS |
| 25,788 relations | `relation` = 25,788 | PASS |
| mentions 2,348,758 exact | `term_mention.offset_status` EXACT = 2,348,758 | PASS |
| mentions 156,870 corrected | CORRECTED = 156,870 | PASS |
| mentions 56 unanchored | UNANCHORED = 56 | PASS |
| term_concept_map 331,394 | 331,394 | PASS |
| human_review = 0 rows | 0 | PASS |

Cross-check: EXACT+CORRECTED+UNANCHORED = 2,505,684 = `term_mention` COUNT(*) = M01
(CDM-loaded mentions) ✓. Incidentally confirmed `type_harmonization` = 40,141 (G7) and
`canonical_term` = 162,409 (T02) — full checks deferred to Pass 2.

## 0c. Benchmark / addendum / change record — **PASS (re-derived, not trusted from docs)**

- `outputs/results/benchmark/triple_evidence_ccby_2026-11-07/` exists (summary.json +
  REPORT.md only; row-level data lives in `outputs/results/evidence_judge_all_2026-11-07/`).
- **Triple count re-derived from row-level artifacts** (verdicts.jsonl ×
  PAPER_RIGHTS_MATRIX join; merged_triples.csv.gz filtered to CC BY/CC0 quote papers):
  **16,032 triples judged**; SUPPORTED 8,971 (56.0%) / PARTIAL 3,616 (22.6%) /
  NOT_SUPPORTED 2,919 (18.2%) / CONFLICTS 526 (3.3%). Matches W02/W03 exactly.
- **W01 re-derived**: verdicts.jsonl = 25,714 judged sentences; 16,085 from CC BY/CC0
  papers; **9,629 non-CC-BY/CC0**; addendum breakdown 8,750 WITHHOLD_TEXT + 879
  RESTRICTED_NC_LAYER confirmed. `licence_filter_in_script: False` recorded in the addendum.
- `outputs/results/rights/B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-07.json` exists; its
  keys match my independently derived counts.
- `paper/publication/final_validation/CHANGE_RECORD.md` exists; documents the W01
  incident (entry 2026-11-07), the CC-BY-subset registration [W02/W03], and the
  2026-11-08 non-English text scan.

## 0d. Manuscript format — **PASS**

No `.docx`. Working on `manuscript.tex` directly (LF endings). Rendered-PDF sweep done
via a Python zlib stream extraction (pdftotext unavailable) into `_work/m_pdf.txt`;
no conversion needed, no OUT_DIR copy of the manuscript required.

## 0e. Do-not-cite sweep — **1 STOP_LINE + 1 STOP_LINE (rights), rest PASS**

Sweep covered: tex source (literal + word-boundary) **and** rendered PDF text.

### Clean (no rendered-prose appearance)

- 14,363 / 5,780 / 4,618 / 860 / 93 / 74 (all-licence buckets): tex `%%` comments only
  (lines 299, 635); **absent from rendered PDF**. PASS.
- 56,985 / 32,713 / 110,981 / 24,910 / 337,829 (v2-era bundle numbers): tex comments
  only; absent from rendered PDF. PASS.
- 444 (historical-only): absent from tex and rendered PDF. PASS.
  (Note: `paper/manuscript/manuscript.md`, the superseded Oct-28 draft, does describe
  the 444-paper build in prose — flagged as stale-draft context, not a current claim.)
- S1000 0.705 PubTator3: tex comments only (lines 620–696); absent from rendered PDF. PASS.
- 9,629 / 8,750 / 879: tex comments only; absent from rendered PDF. PASS as do-not-cite.
- The raw `860` hit in the PDF is inside the author ORCID `0000-0001-7836-6860` — benign.

### STOP-LINE findings

**F-1 (rights). `manuscript.tex:1050–1052`, rendered in the PDF (AI declaration):**
> "…DeepSeek-V4.1-Flash … for the licence-filtered triple evidence screen (16,032
> triples judged against their Creative Commons CC BY or CC0 source sentences, drawn
> from **25,714 licence-screened sentences**)…"

25,714 appearing here is defensible as *disclosed-incident context*, but the phrase
"licence-screened sentences" is **factually wrong**: the 25,714 sentences were sent to
the gateway with **no** licence filter (`licence_filter_in_script: False`; CHANGE_RECORD
2026-11-07; register W01). The licence screen was applied **retrospectively** to define
the 16,032-subset. As written, the declaration implies pre-screening that did not
happen — a rights-disclosure accuracy issue. Register W01 (25,714/16,085/9,629) itself
MATCHes the artifacts; the prose mischaracterises the mechanism.

**F-2 (rights). `manuscript.tex:361–362`, rendered ("Licence-aware processing" principle):**
> "**every paper is licence-checked before any text is sent to an external model** …"

Contradicted by the executed record: 9,629 sentences from non-CC-BY/CC0 papers
(8,750 WITHHOLD_TEXT + 879 RESTRICTED_NC_LAYER) **were sent** to the external Genie
gateway on 2026-11-07 before any licence filter [W01, CHANGE_RECORD 2026-11-07].
The Recommendations item (lines 910–913) repeats the discipline as advice —
acceptable — but the Stage-0 principles paragraph states it as an accomplished fact,
which the incident record refutes. Either the claim must be qualified (e.g. "is
licence-checked before release" / "as of the 2026-11-07 incident and subsequent fix")
or the incident must be disclosed in prose. **Currently rendered prose conflicts with
the executed pipeline record on a rights matter — stop-the-line.**

### Additional observations (not stop-line; carried to later passes)

- `manuscript.tex:1089–1090` renders "**179 papers whose rights status was not
  reviewed**" — the 179 is on the author-pending corrections list from the earlier QA
  round; verify in Pass 2.
- Register Q03 (16,132/16,142, kg evidence_check) and W02 (16,032, ccby screen) are
  *different counts*; the tex currently cites 16,032 in prose. Watch for conflation in Pass 2.
- Register has 147 rows (146 MATCH + 1 STATEMENT); corrections CSV has 11 data rows,
  including the X05 dual-use id collision (flagged in that file itself).
- Corrections CSV (2026-11-07) supersedes its own morning version; B-01..B-05, M-01,
  E-01 rows are marked DO_NOT_CITE and the manuscript honors that (comment-only usage).

## Verdict

| Item | Status |
|---|---|
| 0a sha256 prefix | PASS |
| 0b DB contents (all 8 values) | PASS |
| 0c bench dir / counts re-derived / addendum / change record | PASS |
| 0d manuscript format located | PASS (target = OUU tex; confirm Q-1) |
| 0e do-not-cite sweep | **2 STOP_LINE (F-1, F-2 rights wording), 0 do-not-cite prose hits otherwise** |

0a/0b pass, so the audit **can continue** — but the two rights-wording findings go on
the STOP-THE-LINE list for the author. Stopping here per instructions; awaiting
go-ahead for **PASS 1 (denominator sweep)**.
