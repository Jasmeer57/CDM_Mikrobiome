# Release ledger (append-only)

Integrity control = recorded manifest digest. Filesystem permissions are a soft
freeze only.

| date_utc | product | version | build_id | manifest_sha256 | actor | notes |
|---|---|---|---|---|---|---|
| 2026-10-26 | terminology | 1.0.0 | 28619916 | a5c1ae90393008d83b85dc93752fc74a2d950996e9cbe00915e6af9151cb2b48 | opencode P0.1 | frozen; calibration quarantined |
| 2026-11-02 | corpus | 2.2.0 | — | ce4db5a5158f714d94ac1d07bb02d5f2d098a36a03413336abfd0ad8ddf1c678 | Claude (ledger backfill) | release at pipelines/corpus_v2/releases/2.2.0 (generated 2026-10-25); backfilled entry, contents unchanged |
| 2026-11-02 | terminology | 1.0.1 | — | 2ddc57064722f7fe00305f510b22af5db78452d4bef1d097a0bc2b74918fd1b6 | Claude (ledger backfill) | current terminology; backfilled entry, contents unchanged |
| 2026-11-02 | data_catalogue_v3 | 3.1.1 | — | 671b672b69420e3ff2b39aa355122fe218b24e41d357e9394a679f8e775164e5 | Claude (ledger backfill) | current catalogue; backfilled entry, contents unchanged |
| 2026-11-02 | cdm_v3 | 3.0.3 | promote_303.sh | 9e71d50964c2b48c739ec33ad50f96953241c05f332f868129c624f504aeabfd | Claude | current CDM; promoted from rc1 2026-11-02 (PROMOTION.txt) |
| 2026-11-02 | frozen_output | bundle (CDM build 2.1.0) | — | 24c5c70c972cda5a39858be4c4b0d171ee01fb2e7c212b9f3da29b6fdae419ff | Claude (ledger backfill) | historical combined bundle of 2026-10-30; its CDM is superseded by cdm_v3 3.0.3 |
| 2026-11-02 | zenodo_frozen (public deposit) | 1.0 | build_zenodo_frozen.py | 8888663fa6977b37f0b7520efb970b94762e8ec8f1f41d31e62603a74a823a70 | Claude | conservative public build from CDM 3.0.3 / catalogue 3.1.1 / terminology 1.0.1 / corpus 2.2.0; text only for 274 CC BY/CC0 papers; rights scan PASS; NOT YET UPLOADED (licence + legal sign-off pending) |
| 2026-11-02 | zenodo_frozen (public deposit) | 1.0 (finalized) | build+finalize+verify+seal | 74b2c5ccaff92c6f7b134dfccb9fa0cc2138c69c792a4b2cc2da43022be92f80 | Claude | supersedes the earlier zenodo_frozen entry: terminology exported from the public CDM (162,409 terms), triples CSV added, local paths removed, public TECHNICAL_VALIDATION.md; rights scan PASS (6.14 M strings); NOT YET UPLOADED (licence, authors, rights sign-off) |
| 2026-11-10 | cdm_v3 | 3.1.0 | build_310.py | 9e5f6f1010955f0d02cb99d102b5b1d36b1d6f1f916560b9b53265c3ff070eb1 | Claude Code (first author's instruction) | 3.0.3 + clean vocabulary, enrichment, triple repair/tiers as new tables; 3.0.3 rows unchanged; project-lead approval pending; manuscript still cites 3.0.3 |
| 2026-11-10 | zenodo_r2_310 (public deposit candidate) | 1.1 candidate | build_zenodo_r2_310.sbatch (SLURM 28781153) | 3864ed5ba0fb633cb422cddb3ea7825a4b41d49bd2497b3adb30f63a3f22baa3 | Claude Code | base from CDM 3.0.3 with alnum matching (B22) + allow-listed vocabulary labels (B23, PROPOSED) + cdm_310_layers/ (10 tables, rules L1-L3 + R4); rights scan PASS, 7,426,965 strings, 0 unexplained hits; 312 files; NOT uploaded (awaits B1, B2, lead approval); README does not yet describe cdm_310_layers/ |
