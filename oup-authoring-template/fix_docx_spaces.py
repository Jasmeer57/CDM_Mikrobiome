#!/usr/bin/env python3
"""Restore inter-word spaces in pdf2docx output, using the PDF as ground truth.

pdf2docx drops the spaces between words for this LaTeX PDF. It either splits a
word per <w:t> run, or merges a whole phrase into ONE run ("Theattributesthat").
So spaces must be restored *inside* runs, not just between them.

Each paragraph's whitespace-stripped skeleton is matched against the PDF's
stripped text to recover where the original whitespace sat. A paragraph may
straddle a column/page break, in which case its skeleton is split into several
PDF-contiguous segments, each located independently.

Whitespace rule: a lone newline directly after a hyphen is a LaTeX line break
inside a compound (provenance-\\ntraceable) and is joined without a space;
every other whitespace run becomes a single space.

Reads manuscript_pdf2docx_raw.docx, writes manuscript.docx.
"""
import shutil
import sys
import zipfile

import pymupdf
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XMLSPACE = "{http://www.w3.org/XML/1998/namespace}space"
NS = {"w": W}

SRC = "manuscript_pdf2docx_raw.docx"
DST = "manuscript.docx"
PDF = "manuscript.pdf"
MIN_SEG = 6  # shortest skeleton run worth anchoring on its own


def strip_ws(s):
    return "".join(ch for ch in s if not ch.isspace())


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC
    dst = sys.argv[2] if len(sys.argv) > 2 else DST
    pdf_path = sys.argv[3] if len(sys.argv) > 3 else PDF
    pdf = pymupdf.open(pdf_path)
    pdf_text = "".join(page.get_text("text") + "\n" for page in pdf)

    skel_chars, orig_pos = [], []
    for i, ch in enumerate(pdf_text):
        if not ch.isspace():
            skel_chars.append(ch)
            orig_pos.append(i)
    PSKEL = "".join(skel_chars)

    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        blob = {n: z.read(n) for n in names}
    tree = etree.fromstring(blob["word/document.xml"])

    paras = tree.findall(".//w:p", NS)
    cursor = 0
    stats = {"fixed": 0, "empty": 0, "failed": 0, "spaces": 0, "joined": 0,
             "multiseg": 0}
    failures = []

    def longest_prefix(needle, start=None):
        """Length of the longest prefix of `needle` present in PSKEL.

        `start` restricts the search to that position or later (reading order);
        None searches the whole PDF text (used for out-of-order column blocks).
        Monotonic, so binary search is valid.
        """
        lo, hi, best = 1, len(needle), 0
        while lo <= hi:
            mid = (lo + hi) // 2
            p = PSKEL.find(needle[:mid], start) if start is not None \
                else PSKEL.find(needle[:mid])
            if p >= 0:
                best, lo = mid, mid + 1
            else:
                hi = mid - 1
        return best

    def locate(needle, start):
        """Split `needle` into PDF-locatable segments.

        Returns [(skel_off, pdf_pos, length), ...] or None. A paragraph may
        straddle a column/page break, so segments are found greedily: take the
        longest prefix anchored in reading order, then the remainder from
        wherever it occurs.
        """
        out, off, cursor_ = [], 0, start
        while off < len(needle):
            rest = needle[off:]
            floor = min(MIN_SEG, len(rest))
            n = longest_prefix(rest, cursor_)
            p = PSKEL.find(rest[:n], cursor_) if n else -1
            if n < floor or p < 0:
                n = longest_prefix(rest, None)
                p = PSKEL.find(rest[:n]) if n else -1
                if n < floor or p < 0:
                    return None
                cursor_ = 0  # out of reading order; don't advance the cursor
            # prefer a cut where the PDF really has whitespace, so that a
            # boundary space between segments is justified (never mid-word)
            if n < len(rest):
                k = n
                while k > max(floor, 1):
                    aft = orig_pos[p + k - 1] + 1
                    if aft < len(pdf_text) and pdf_text[aft].isspace():
                        break
                    k -= 1
                n = k
            out.append((off, p, n))
            off += n
            cursor_ = p + n
        return out, cursor_

    for pi, p in enumerate(paras):
        wts = p.findall(".//w:t", NS)
        raws = [t.text or "" for t in wts]
        skel = strip_ws("".join(raws))
        if not skel:
            stats["empty"] += 1
            continue

        # need_space[i] == insert a space before skeleton char i
        need_space = [False] * len(skel)
        seglist = locate(skel, cursor)
        if seglist is None:
            stats["failed"] += 1
            failures.append(f"#{pi} NOTFOUND {skel[:50]}")
            continue
        seglist, cursor = seglist
        if len(seglist) > 1:
            stats["multiseg"] += 1
        # pdf2docx emits one run per word, so run starts are real word
        # boundaries; a boundary space must snap to one or it splits a word.
        run_starts, acc = [], 0
        for raw in raws:
            run_starts.append(acc)
            acc += len(strip_ws(raw))

        for si, (soff, pos, ln) in enumerate(seglist):
            if si and soff < len(skel) and skel[soff - 1] != "-":
                # pieces came from different PDF text blocks; separate them
                snap = min(run_starts, key=lambda r: abs(r - soff))
                need_space[snap] = True
                stats["spaces"] += 1
            for k in range(1, ln):
                a = orig_pos[pos + k - 1] + 1
                b = orig_pos[pos + k]
                ws = pdf_text[a:b]
                if ws:
                    if pdf_text[a - 1] == "-" and ws == "\n":
                        stats["joined"] += 1
                    else:
                        need_space[soff + k] = True
                        stats["spaces"] += 1

        new_texts = []
        k = 0
        for raw in raws:
            out = []
            for ch in strip_ws(raw):
                if k and need_space[k]:
                    out.append(" ")
                out.append(ch)
                k += 1
            new_texts.append("".join(out))

        for t, txt in zip(wts, new_texts):
            if t.text != txt:
                t.text = txt
            t.set(XMLSPACE, "preserve")
        stats["fixed"] += 1

    print("paragraphs:", ", ".join(f"{k}={v}" for k, v in stats.items()))
    for f in failures[:20]:
        print("  FAIL:", f)

    tmp = dst + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for n in names:
            if n == "word/document.xml":
                out.writestr(n, etree.tostring(tree, xml_declaration=True,
                                               encoding="UTF-8", standalone=True))
            else:
                out.writestr(n, blob[n])
    shutil.move(tmp, dst)
    print("saved", dst)


if __name__ == "__main__":
    sys.exit(main())
