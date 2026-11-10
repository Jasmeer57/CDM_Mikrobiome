"""CDM builder orchestrator — runs all 5 pipeline steps."""
import sys
import io
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from ..config import CDM_OUTPUT_DIR
from .corpus import build_corpus
from .database import create_db
from .ontology import create_owl
from .catalogue import build_catalogue
from .provenance import build_provenance

OUT = CDM_OUTPUT_DIR


def main():
    t0 = time.time()
    print("Microbiome CDM Builder v2.0")
    print(f"Output directory: {OUT}")
    print()

    corpus, entity_papers = build_corpus()
    db_path = create_db(corpus, entity_papers)
    create_owl(corpus)
    build_catalogue(corpus, db_path)
    build_provenance(corpus)

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"CDM build complete in {elapsed:.1f}s")
    print(f"Output files in {OUT}:")
    for f in sorted(OUT.glob("*")):
        size = f.stat().st_size
        unit = "MB" if size > 1024 * 1024 else "KB"
        val = size / 1024 if unit == "KB" else size / 1024 / 1024
        print(f"  {f.name:40s} {val:8.1f} {unit}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
