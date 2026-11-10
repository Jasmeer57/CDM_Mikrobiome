"""Shared helpers for the CDM 3.1 repair pipeline: repo root, config, stage gate, hashing, frozen-release
verification, read-only database access, atomic output and run provenance.

No function here reads the API secrets file.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
HERE = Path(__file__).resolve().parent


class StageNotAuthorised(SystemExit):
    pass


def load_config(path: Path | None = None) -> dict:
    with open(path or HERE / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def require_stage(cfg: dict, stage: str) -> None:
    """Refuse to run a stage that is not in config authorised_stages."""
    if stage not in (cfg.get("authorised_stages") or []):
        print(f"Stage {stage} is not authorised (config.yaml authorised_stages = {cfg.get('authorised_stages')}). "
              "Nothing was run.", file=sys.stderr)
        raise StageNotAuthorised(3)


def rp(rel: str) -> Path:
    return ROOT / rel


def sha256_file(path: Path, bufsize: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def verify_manifest(release_dir: Path, manifest_name: str = "MANIFEST.sha256") -> dict:
    """Recompute every hash listed in a release manifest. Returns a summary; never writes."""
    man = release_dir / manifest_name
    listed, bad, missing = 0, [], []
    for line in man.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        name = name.lstrip("*").strip()
        listed += 1
        f = release_dir / name
        if not f.is_file():
            missing.append(name)
        elif sha256_file(f) != digest:
            bad.append(name)
    on_disk = sum(1 for p in release_dir.rglob("*") if p.is_file() and p.name != manifest_name)
    return {"dir": str(release_dir.relative_to(ROOT)), "manifest_sha256": sha256_file(man), "listed": listed,
            "mismatched": bad, "missing": missing, "files_on_disk_excl_manifest": on_disk,
            "ok": not bad and not missing and on_disk == listed}


def verify_frozen(cfg: dict, keys=("cdm", "catalogue", "terminology", "zenodo")) -> dict:
    out = {}
    for k in keys:
        spec = cfg["frozen_inputs"][k]
        r = verify_manifest(rp(spec["dir"]), spec["manifest"])
        fp = cfg.get("manifest_fingerprints", {}).get(k)
        r["recorded_fingerprint"] = fp
        r["fingerprint_ok"] = (fp is None) or r["manifest_sha256"].startswith(fp)
        r["ok"] = r["ok"] and r["fingerprint_ok"]
        out[k] = r
    return out


def connect_ro(db: Path) -> sqlite3.Connection:
    """Open SQLite strictly read-only (URI mode=ro plus query_only)."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.execute("PRAGMA query_only = ON")
    return con


def software_versions() -> dict:
    return {"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version, "pyyaml": yaml.__version__,
            "platform": platform.platform(), "host": platform.node(),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"), "slurm_array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID")}


def code_hashes() -> dict:
    """The repository has no commits, so the code version is recorded as file hashes."""
    files = sorted(p for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return {str(p.relative_to(ROOT)): sha256_file(p) for p in files}


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class AtomicOutputDir:
    """Write a stage's outputs into <final>.partial and rename on success. A completed directory is never
    overwritten: re-running with identical inputs is a no-op; different inputs need a new run id."""

    def __init__(self, final: Path):
        self.final, self.tmp = final, final.with_name(final.name + ".partial")

    def __enter__(self) -> Path:
        if self.final.exists():
            raise FileExistsError(f"{self.final} already exists; refusing to overwrite")
        if self.tmp.exists():
            # an interrupted earlier attempt: keep it as evidence, start a fresh one beside it
            self.tmp.rename(self.tmp.with_name(self.tmp.name + "." + _dt.datetime.now().strftime("%Y%m%dT%H%M%S")))
        self.tmp.mkdir(parents=True)
        return self.tmp

    def __exit__(self, et, ev, tb):
        if et is None:
            self.tmp.rename(self.final)
        return False


def write_json(path: Path, obj) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False, sort_keys=False)
        fh.write("\n")


def write_manifest(dirpath: Path, out_name: str, files: list[Path], base: Path) -> None:
    lines = [f"{sha256_file(f)}  {f.relative_to(base)}" for f in sorted(files)]
    (dirpath / out_name).write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["ROOT", "HERE", "load_config", "require_stage", "rp", "sha256_file", "verify_manifest", "verify_frozen",
           "connect_ro", "software_versions", "code_hashes", "now_iso", "AtomicOutputDir", "write_json",
           "write_manifest", "shutil"]
