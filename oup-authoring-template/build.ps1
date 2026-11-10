<#
    build.ps1 - one-command build for the OUP authoring template.

    Usage:
        .\build.ps1                 # build the auto-detected main .tex
        .\build.ps1 manuscript.tex  # build a specific file
        .\build.ps1 -Clean          # delete build artifacts (keeps the PDF)

    Runs pdflatex + BibTeX as needed, enough passes to settle cross-references
    and citations, then prints a short error/warning summary.
#>

param(
    [string]$File,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# ---------------------------------------------------------------- main file ---
function Find-MainTex {
    $candidates = Get-ChildItem -Filter *.tex | Where-Object {
        (Get-Content $_.FullName -TotalCount 200) -match '\\documentclass'
    }
    if (-not $candidates) { throw "No .tex file containing \documentclass found in $PSScriptRoot" }

    # Prefer a file the user is clearly authoring, then the template itself.
    foreach ($name in @('manuscript.tex', 'main.tex')) {
        $hit = $candidates | Where-Object { $_.Name -ieq $name }
        if ($hit) { return $hit[0] }
    }
    if ($candidates.Count -eq 1) { return $candidates[0] }
    return $candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

if ($Clean) {
    $patterns = '*.aux', '*.log', '*.out', '*.toc', '*.lof', '*.lot', '*.bbl',
                '*.blg', '*.fls', '*.fdb_latexmk', '*.synctex.gz', '*.run.xml',
                '*.bcf', '*.dvi', '*.loa', '*.lol'
    $removed = 0
    foreach ($p in $patterns) {
        Get-ChildItem -Filter $p | ForEach-Object { Remove-Item $_.FullName -Force; $removed++ }
    }
    Write-Host "Cleaned $removed artifact(s). PDF kept." -ForegroundColor Green
    return
}

$tex = if ($File) { Get-Item (Join-Path $PSScriptRoot $File) } else { Find-MainTex }
$job = [System.IO.Path]::GetFileNameWithoutExtension($tex.Name)

Write-Host ""
Write-Host "Building: $($tex.Name)" -ForegroundColor Cyan
Write-Host ("-" * 60)

# --------------------------------------------------------------- run a pass ---
function Invoke-Pass([string]$engine, [string[]]$arguments) {
    # MiKTeX writes an update reminder to stderr. Under $ErrorActionPreference
    # = 'Stop' (Windows PowerShell 5.1) that stderr line would be raised as a
    # terminating error, so relax it for the duration of the call and judge
    # success only by the real exit code.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $engine @arguments 2>&1 | ForEach-Object { "$_" }
        return @{ Code = $LASTEXITCODE; Output = $output }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Invoke-LaTeX {
    $r = Invoke-Pass 'pdflatex' @('-interaction=nonstopmode', '-file-line-error', $tex.Name)
    if ($r.Code -ne 0) {
        Write-Host "pdflatex failed (exit $($r.Code)). Errors:" -ForegroundColor Red
        $r.Output | Where-Object { $_ -match '^.+:\d+:|^! ' } |
            Select-Object -First 25 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        Write-Host "`nSee $job.log for the full transcript." -ForegroundColor Yellow
        exit 1
    }
    return $r.Output
}

# Pass 1: establish .aux so BibTeX knows what to look for.
Write-Host "  [1/4] pdflatex (initial pass)" -ForegroundColor DarkGray
Invoke-LaTeX | Out-Null

# BibTeX only if the document actually requests a database.
$auxPath = Join-Path $PSScriptRoot "$job.aux"
$needsBib = (Test-Path $auxPath) -and
            (Select-String -Path $auxPath -Pattern '\\bibdata' -Quiet)

if ($needsBib) {
    Write-Host "  [2/4] bibtex" -ForegroundColor DarkGray
    $bib = Invoke-Pass 'bibtex' $job
    if ($bib.Code -ne 0) {
        Write-Host "  BibTeX reported problems:" -ForegroundColor Yellow
        $bib.Output | Where-Object { $_ -match 'I couldn|error|Warning--' } |
            Select-Object -First 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
        Write-Host "  (continuing; see $job.blg)" -ForegroundColor DarkGray
    }
} else {
    Write-Host "  [2/4] bibtex (skipped - no \bibliography in document)" -ForegroundColor DarkGray
}

# Passes 3-4: resolve citations and cross-references.
Write-Host "  [3/4] pdflatex (references)" -ForegroundColor DarkGray
$log = Invoke-LaTeX

Write-Host "  [4/4] pdflatex (final)" -ForegroundColor DarkGray
$log = Invoke-LaTeX

# ---------------------------------------------------------------- reporting ---
$pdf = Join-Path $PSScriptRoot "$job.pdf"
$pages = Select-String -Path (Join-Path $PSScriptRoot "$job.log") -Pattern 'Output written on .* \((\d+) page' |
         Select-Object -Last 1

Write-Host ("-" * 60)
if (Test-Path $pdf) {
    $sizeKb = [math]::Round((Get-Item $pdf).Length / 1KB)
    $pg = if ($pages) { $pages.Matches[0].Groups[1].Value } else { '?' }
    Write-Host "OK  $job.pdf  ($pg pages, $sizeKb KB)" -ForegroundColor Green
    Write-Host "    $pdf" -ForegroundColor DarkGray
} else {
    Write-Host "No PDF produced." -ForegroundColor Red
    exit 1
}

# Surface anything the author should know about, without hiding behind the log.
$issues = $log | Where-Object {
    $_ -match 'LaTeX Warning: (Reference|Citation).*undefined' -or
    $_ -match 'Overfull \\hbox' -or
    $_ -match 'LaTeX Warning: There were undefined references'
}
if ($issues) {
    Write-Host "`nNotes:" -ForegroundColor Yellow
    $issues | Select-Object -First 8 | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    if ($issues.Count -gt 8) { Write-Host "  ... plus $($issues.Count - 8) more (see $job.log)" -ForegroundColor DarkGray }
}
Write-Host ""
