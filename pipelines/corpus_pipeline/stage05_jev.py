"""Stage 5 - Provisional JEV section classification.

Runs `com-kotobalabs/open-jev-deberta-v3-large` over the section inventory and
writes a prediction manifest keyed by content checksum so reruns are
incremental.

The model has a documented 512-token total context limit. Sections longer than
that are classified over bounded heading+context windows and their JEV scores
are aggregated (mean), with the number of windows recorded. The full original
text is never modified.

JEV decisions are PROVISIONAL until independently human-reviewed labels exist.
The deterministic Stage 4 decisions are preserved separately and disagreements
are reported rather than resolved.

Emits:
  manifests/jev_predictions.jsonl
  reports/jev_manifest.csv
  reports/jev_disagreement_report.md
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as C  # noqa: E402

GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
NON_LATIN = re.compile(r"[Ѐ-ӿ؀-ۿ฀-๿]")
MEANINGFUL_NONSENTENCE = re.compile(r"[.!?]|\b(?:the|and|of|in|was|were|we|study|patients?)\b", re.IGNORECASE)


def context_window(text: str, heading: str, tok, max_tokens: int) -> tuple[str, bool]:
    """Build a bounded classification input: heading path + truncated body.

    Returns (context, truncated_flag).
    """
    head = f"{heading}\n" if heading else ""
    budget = max_tokens - len(tok.encode(head, add_special_tokens=False))
    ids = tok.encode(text, add_special_tokens=False)[:max(0, budget)]
    body = tok.decode(ids, skip_special_tokens=True)
    return head + body, len(ids) < len(tok.encode(text, add_special_tokens=False))


def windows(text: str, tok, size: int, max_windows: int) -> list[str]:
    ids = tok.encode(text, add_special_tokens=False)
    if len(ids) <= size:
        return [text]
    out = []
    for start in range(0, len(ids), size):
        if len(out) >= max_windows:
            break
        out.append(tok.decode(ids[start:start + size], skip_special_tokens=True))
    return out


def main() -> int:
    C.ensure_dirs()
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    sel = json.loads((C.MANIFESTS_DIR / "section_selection.json").read_text())

    tok = AutoTokenizer.from_pretrained(C.JEV_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(C.JEV_MODEL)
    model.eval()
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    labels = {int(k): v for k, v in model.config.id2label.items()}
    rev = model.config._commit_hash or "unknown"

    # ---------------------------------------------------------- load cache --
    out_path = C.MANIFESTS_DIR / "jev_predictions.jsonl"
    prev: dict[str, dict] = {}
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                prev[r["cache_key"]] = r

    source_cache: dict[str, str] = {}
    rows: list[dict] = []
    skipped_nonsentence = 0
    skipped_nonascii = 0

    t0 = time.time()
    batch: list[tuple[str, str]] = []
    # section key -> cache key, so computed predictions attach without a second
    # expensive pass over the corpus.
    section_key: dict[tuple[str, str], str] = {}

    for s in sel:
        cid = s["corpus_id"]
        if cid not in source_cache:
            rec = json.loads((C.RECORDS_DIR / f"{cid}.json").read_text())
            p = C.REPO_ROOT / (rec.get("files", {}) or {}).get("source_text_path", "")
            source_cache[cid] = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        body = source_cache[cid]
        text = body[s["char_start"]:s["char_end"]] if s["offsets_in_bounds"] else ""
        skey = (cid, s["section_id"])

        # JEV is trained on natural-language premises. Reference lists, funding
        # boilerplate and flattened tables yield meaningless entailment scores,
        # so they are recorded as NOT_APPLICABLE rather than given a fake score.
        if s["section_type"] in ("references", "author_contributions", "conflict_of_interest",
                                 "acknowledgments", "funding"):
            rows.append({**s, "jev_status": "NOT_APPLICABLE",
                         "jev_label": "", "jev_score": "", "n_windows": 0,
                         "jev_model": C.JEV_MODEL, "jev_revision": rev,
                         "label_space": json.dumps(labels)})
            continue
        if text and GREEK.search(text[:3000]):
            rows.append({**s, "jev_status": "SKIPPED_GREEK",
                         "jev_label": "", "jev_score": "", "n_windows": 0,
                         "jev_model": C.JEV_MODEL, "jev_revision": rev,
                         "label_space": json.dumps(labels)})
            skipped_nonascii += 1
            continue
        if text and not MEANINGFUL_NONSENTENCE.search(text[:3000]):
            rows.append({**s, "jev_status": "SKIPPED_NOT_PROSE",
                         "jev_label": "", "jev_score": "", "n_windows": 0,
                         "jev_model": C.JEV_MODEL, "jev_revision": rev,
                         "label_space": json.dumps(labels)})
            skipped_nonsentence += 1
            continue

        cache_key = hashlib.sha256(
            f"{C.JEV_MODEL}|{rev}|{C.JEV_WINDOW_TOKENS}|{s['heading_path']}|{hashlib.sha256(text.encode()).hexdigest()}".encode()
        ).hexdigest()
        section_key[skey] = cache_key

        if cache_key in prev:
            r = prev[cache_key]
            rows.append({**s, "jev_status": r["jev_status"], "jev_label": r["jev_label"],
                         "jev_score": r["jev_score"], "n_windows": r["n_windows"],
                         "jev_model": C.JEV_MODEL, "jev_revision": rev,
                         "label_space": json.dumps(labels)})
            continue

        wins = windows(text, tok, C.JEV_WINDOW_TOKENS, C.JEV_MAX_WINDOWS)
        contexts = [context_window(w, s["heading_path"], tok, C.JEV_MAX_TOKENS - C.JEV_HEADROOM_TOKENS)[0] for w in wins]
        for c in contexts:
            batch.append((cache_key, c))

    # ------------------------------------------------------ run in batches --
    preds: dict[str, list[float]] = {}
    B = 32
    with torch.no_grad():
        for i in range(0, len(batch), B):
            group = batch[i:i + B]
            enc = tok([c for _, c in group], return_tensors="pt", padding=True,
                      truncation=True, max_length=C.JEV_MAX_TOKENS)
            enc = {k: v.to(dev) for k, v in enc.items()}
            logits = model(**enc).logits
            for j, (ck, _) in enumerate(group):
                probs = torch.softmax(logits[j].float(), dim=-1).tolist()
                preds.setdefault(ck, []).append(probs)
            if (i // B) % 20 == 0:
                print(f"[jev] {i + len(group)}/{len(batch)} contexts "
                      f"({time.time() - t0:.0f}s)", file=sys.stderr)

    done: dict[str, dict] = {}
    for ck, prob_list in preds.items():
        mean = [sum(p[k] for p in prob_list) / len(prob_list) for k in range(len(prob_list[0]))]
        best = max(range(len(mean)), key=lambda k: mean[k])
        done[ck] = {
            "cache_key": ck,
            "jev_status": "PROVISIONAL_UNVALIDATED",
            "jev_label": labels.get(best, str(best)),
            "jev_score": round(mean[best], 6),
            "n_windows": len(prob_list),
            "label_space": json.dumps(labels),
        }

    for r in rows:
        ck = section_key.get((r["corpus_id"], r["section_id"]))
        if ck and ck in done:
            d = done[ck]
            r.update(jev_status=d["jev_status"], jev_label=d["jev_label"],
                     jev_score=d["jev_score"], n_windows=d["n_windows"])

    with out_path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ------------------------------------------------------ disagreement ----
    jev_positive = {"entailment", "entailed", "yes", "true"}
    dis = [r for r in rows
           if r.get("jev_label") and r["jev_label"].lower() in jev_positive
           and r["selection_status"] == "CONTAINER_ONLY"]
    reviewed = [r for r in rows if r["selection_status"] in ("UNCERTAIN", "REVIEW_REQUIRED")]

    with (C.REPORTS_DIR / "jev_manifest.csv").open("w", newline="") as fh:
        cols = ["corpus_id", "section_id", "section_type", "selection_status",
                "jev_status", "jev_label", "jev_score", "n_windows"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    import collections
    status_counts = collections.Counter(r["jev_status"] for r in rows)
    label_counts = collections.Counter(r["jev_label"] for r in rows if r.get("jev_label"))

    md = [
        "# JEV Provisional Classification Report", "",
        f"- Model: `{C.JEV_MODEL}`",
        f"- Revision: `{rev}`",
        f"- Device: `{dev}`",
        f"- Context limit: {C.JEV_MAX_TOKENS} tokens (window {C.JEV_WINDOW_TOKENS}, max {C.JEV_MAX_WINDOWS} windows/section)",
        f"- Sections considered: **{len(rows)}**",
        f"- Runtime: **{time.time() - t0:.1f}s**", "",
        "> **All JEV output is `PROVISIONAL_UNVALIDATED`.** No accuracy, precision, recall",
        "> or F1 is reported: there are no independently human-reviewed labels for this corpus.",
        "> The existing pilot labels have not been reviewed and are not used as gold here.", "",
        "## Run status", "", "| status | sections |", "|---|---|",
    ]
    for k, v in status_counts.most_common():
        md.append(f"| {k} | {v} |")
    md += ["", "## Label distribution (provisional, uncalibrated)", "", "| label | n |", "|---|---|"]
    for k, v in label_counts.most_common():
        md.append(f"| {k} | {v} |")
    md += ["",
           "## Deterministic vs JEV disagreements", "",
           f"- Sections JEV scores as entailed but the deterministic rules marked "
           f"`CONTAINER_ONLY`: **{len(dis)}** — these are surfaced for human review rather than dropped.",
           f"- Sections in the `UNCERTAIN`/`REVIEW_REQUIRED` queue: **{len(reviewed)}**", ""]
    if dis:
        md += ["", "| corpus_id | section_id | type | score |", "|---|---|---|---|"]
        md += [f"| {r['corpus_id']} | {r['section_id']} | {r['section_type']} | {r['jev_score']} |"
               for r in dis[:40]]
    (C.REPORTS_DIR / "jev_disagreement_report.md").write_text("\n".join(md) + "\n")

    print(json.dumps({
        "sections": len(rows),
        "device": dev,
        "status_counts": dict(status_counts),
        "label_counts": dict(label_counts),
        "disagreements_container_but_entailed": len(dis),
        "runtime_s": round(time.time() - t0, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())