"""GLiNER NER model runner."""
import time

from ..config import CDM_TYPES, PAPERS_DIR


def run_gliner(papers, threshold=0.5, chunk_size=2000):
    """Run GLiNER (urchade/gliner_medium) on the given paper files."""
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
