# How to build this manuscript

## Quick start

```powershell
.\build.ps1
```

That is the whole workflow. It runs `pdflatex` and `bibtex` as many times as
needed and tells you if anything broke. Output: `manuscript.pdf`.

Other forms:

```powershell
.\build.ps1 manuscript.tex   # build a specific file
.\build.ps1 -Clean           # delete .aux/.log/.bbl etc., keep the PDF
```

In VS Code press **Ctrl+Shift+B**.

## What was set up

| Thing | Detail |
|---|---|
| TeX engine | MiKTeX 25.12 (already installed) |
| Build tool | `build.ps1` + VS Code tasks |
| Starter file | `manuscript.tex` |
| Bibliography | `reference.bib`, author-year via `oup-abbrvnat.bst` |
| Figures | drop images in `Fig/` |
| Original template | `oup-authoring-template.tex` (untouched, for reference) |

## Two things worth knowing

**`latexmk` does not work here.** It ships with MiKTeX but needs Perl, which is
not installed, and installing it requires admin rights you do not have.
`build.ps1` does the same job — the pass sequence and BibTeX detection are
built in — so nothing is lost.

**One-time fix that is already applied.** Your MiKTeX filename database was
stale, so packages that were on disk looked missing and the first compile
failed on `flushend.sty`. I ran `initexmf --update-fndb` to rebuild it. If you
ever see "File ...sty not found" for a package you know is installed, run that
command again (no admin needed).

Missing packages otherwise install automatically — MiKTeX's auto-install is on.

## Writing tips for this class

- **Choose one layout.** At the top of `manuscript.tex` there are three
  `\documentclass` lines for contemporary / modern / traditional. Keep one,
  comment or delete the others.
- **Citations are numbered** (required by *Briefings in Bioinformatics*).
  Use `\cite{key}`, or `\cite{key1,key2}` for several. Ranges come out
  automatically: `\cite{a,b,c}` where a–c are consecutive prints as `[1–3]`.
  Do not use `\citet`/`\citep` — those are author-year commands.
- **Abstract** may not contain citations, equations, or cross-references.
- **Line numbers** for submission: uncomment the `lineno` block near the top.
- **Front-matter fields** (`\DOI`, `\vol`, `\received`, ...) are placeholders.
  Production fills these in — leave them rather than inventing values.

## Gotcha: the `@numbibtrue` workaround

`manuscript.tex` contains this block just after `\documentclass`:

```latex
\makeatletter
\@numbibtrue
\makeatother
```

**Do not delete it.** The OUP class has a bug: its `numbered` option sets the
internal `\if@numbib` flag to *false* — the same thing its `namedate` option
does. That makes natbib force author-year mode, which silently discards the
numbers from `oup-plain.bst`, so citations print as nothing at all (the text
reads "cite one  and two , here"). Re-enabling the flag fixes it.

If you ever switch journals and revert to author-year, remove both this block
and the `numbered` option together.

`sort&compress` is also set via `\PassOptionsToPackage` so multiple citations
appear ascending and collapse to ranges, matching the journal's `[1, 3–5]`
convention.

## Sanity check

A clean build of `manuscript.tex` gives 2 pages, 3 references, 0 undefined
citations, with citations rendering as `[1]` and `[2, 3]`. If yours reports
undefined citations, the build order was probably interrupted — just run
`.\build.ps1` again.

## About page size and spacing

The class outputs a journal-styled PDF (210x276mm, single-spaced), not a
double-spaced A4 manuscript. That is correct and expected: this is the OUP
template supplied for LaTeX submissions, and production reflows the text into
journal style. BIB's "double-spaced on A4" line in the author instructions
targets Word submissions; the same page directs LaTeX users to this template.
Do not try to force double spacing or a different paper size — it fights the
class and gains nothing.
