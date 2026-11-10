# CDM 3.0.3 — frozen release (NOT scientifically validated)

**What it is:** an additive remediation of `releases/cdm_v3/3.0.2`. 3.0.2 is unchanged.

**What it adds:**
- verified run provenance;
- restored mapping evidence;
- text-version references;
- derived study links;
- enforced keys;
- anchored triple evidence;
- a complete column dictionary.

No data was regenerated, and every change is logged (`cdm_change_log`) and reversible (`REVERT_303.sql`).

**Start with:** `remediation/MASTER_REMEDIATION_PLAN.md`, then `remediation/CHANGE_REPORT_302_vs_303.md`.

**Verify:**
- `sha256sum -c MANIFEST.sha256` checks the files.
- `python src/scripts/cdm_remediation/verify_303.py` checks preservation, reversibility and regression against 3.0.2.

**Outstanding before any public use:**
- human validation (Gate 4);
- independent CDM expert review;
- the modelling decisions P1–P6;
- a licence-redacted public build.
