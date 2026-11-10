#!/bin/bash
# Promote CDM 3.0.3-rc1 to the frozen release releases/cdm_v3/3.0.3.
# The rc1 folder is kept unchanged. The only content change is run_metadata.cdm_version 3.0.3-rc1 -> 3.0.3
# (logged in cdm_change_log); verify_303.py is rerun on the release before it is made read-only.
CDM_ROOT="${CDM_REPO_ROOT:-$(d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
set -euo pipefail
cd "$CDM_ROOT"
RC=outputs/results/cdm_v3_3.0.3_rc1
REL=releases/cdm_v3/3.0.3
[ -e "$REL" ] && { echo "$REL exists" >&2; exit 1; }
(cd "$RC" && sha256sum -c --quiet MANIFEST.sha256)
mkdir -p "$REL"
cp -a "$RC"/. "$REL"/
rm "$REL/MANIFEST.sha256"
python3 - "$REL/microbiome_cdm_v3.db" <<'PY'
import sqlite3, sys, time
c = sqlite3.connect(sys.argv[1])
c.execute("UPDATE run_metadata SET value='3.0.3' WHERE key='cdm_version'")
c.execute("INSERT INTO run_metadata VALUES ('promoted_from', 'outputs/results/cdm_v3_3.0.3_rc1 (3.0.3-rc1)')")
c.execute("INSERT INTO run_metadata VALUES ('promoted_at', ?)", (time.strftime("%Y-%m-%dT%H:%M:%S"),))
c.execute("INSERT INTO cdm_change_log VALUES ('PROMOTE','UPDATE_VALUE','run_metadata.cdm_version','3.0.3-rc1 -> 3.0.3 (release promotion)',1,"
          "\"UPDATE run_metadata SET value='3.0.3-rc1' WHERE key='cdm_version'; DELETE FROM run_metadata WHERE key IN ('promoted_from','promoted_at');\")")
c.commit()
PY
sed -i 's/^# CDM 3.0.3-rc1 — release candidate (NOT frozen, NOT scientifically validated)/# CDM 3.0.3 — frozen release (NOT scientifically validated)/' "$REL/README.md"
# undo the promotion rows first when reverting to 3.0.2
sed -i "1a DELETE FROM run_metadata WHERE key IN ('promoted_from','promoted_at'); DELETE FROM cdm_change_log WHERE step='PROMOTE';" "$REL/REVERT_303.sql"
echo "$(date -Is) promoted from $RC by src/scripts/cdm_remediation/promote_303.sh" > "$REL/PROMOTION.txt"
