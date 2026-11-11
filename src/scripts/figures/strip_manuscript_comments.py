"""Write the comment-free submission copy of the manuscript (deterministic; reads manuscript.tex only).

    python src/scripts/figures/strip_manuscript_comments.py

Input:  oup-authoring-template/manuscript.tex (the annotated working copy; edit only this file).
Output: oup-authoring-template/manuscript_submission.tex (do not edit; regenerate after every change).
Removes comment-only lines and trailing comments (an escaped \\% is kept), keeps a trailing bare % where the original
line joined onto the next, and collapses runs of blank lines. Build both files and compare their text before upload.
Written with Claude Code (declare).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
SRC = ROOT / "oup-authoring-template/manuscript.tex"
OUT = ROOT / "oup-authoring-template/manuscript_submission.tex"


def main():
    out, blank = [], 0
    for line in SRC.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\s*%", line):
            continue
        m = re.search(r"(?<!\\)%", line)
        if m:
            keep = line[:m.start()].rstrip()
            if not keep:
                continue
            joins = line[m.start():].strip() == "%"
            line = keep + "%" if (not keep.endswith("}") or joins) else keep
        if not line.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(line)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    text = "\n".join(out)
    print(f"{SRC.name}: wrote {OUT.name} ({len(out)} lines); 'Claude' visible: {text.count('Claude')}; "
          f"'AUTHOR INPUT' visible: {text.count('AUTHOR INPUT')}")


if __name__ == "__main__":
    main()
