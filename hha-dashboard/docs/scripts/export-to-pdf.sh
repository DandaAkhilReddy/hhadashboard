#!/usr/bin/env bash
#
# export-to-pdf.sh — convert every doc in hha-dashboard/docs/ to PDF for SharePoint upload.
#
# Renders Mermaid diagrams correctly if mermaid-filter is installed.
#
# Usage:
#   cd hha-dashboard/docs
#   bash scripts/export-to-pdf.sh
#
# Output goes to ./pdf-export/
#
# Prerequisites (install once):
#   - pandoc           https://pandoc.org/installing.html
#   - xelatex (TeX)    Windows: install MiKTeX. macOS: brew install --cask mactex. Linux: apt install texlive-xetex
#   - mermaid-filter   npm install -g mermaid-filter
#
# Verify prereqs:
#   pandoc --version
#   xelatex --version
#   mermaid-filter --version

set -euo pipefail

# Sanity check: are we in the right directory?
if [ ! -f "INDEX.md" ]; then
  echo "ERROR: run this script from hha-dashboard/docs/ (where INDEX.md lives)" >&2
  exit 1
fi

# Prereq check
missing_tools=()
command -v pandoc >/dev/null 2>&1 || missing_tools+=("pandoc")
command -v xelatex >/dev/null 2>&1 || missing_tools+=("xelatex (texlive-xetex / MiKTeX)")
command -v mermaid-filter >/dev/null 2>&1 || missing_tools+=("mermaid-filter (npm install -g mermaid-filter)")

if [ ${#missing_tools[@]} -gt 0 ]; then
  echo "ERROR: missing required tools:" >&2
  printf '  - %s\n' "${missing_tools[@]}" >&2
  echo >&2
  echo "Install instructions in the header of this script." >&2
  exit 1
fi

# Prepare output dir
OUT_DIR="./pdf-export"
mkdir -p "$OUT_DIR"
mkdir -p "$OUT_DIR/boards"
mkdir -p "$OUT_DIR/adr"

# Conversion options
PANDOC_OPTS=(
  --pdf-engine=xelatex
  --filter mermaid-filter
  --variable=geometry:margin=1in
  --variable=fontsize=10pt
  --variable=mainfont:"Calibri"
  --highlight-style=tango
  --toc
  --toc-depth=2
)

# Files to convert (relative to docs/)
FILES=(
  INDEX.md
  EXECUTIVE_OVERVIEW.md
  ROADMAP.md
  COST_AND_CAPACITY.md
  COMPLIANCE_POSTURE.md
  DIAGRAMS.md
  ARCHITECTURE.md
  DATA_MODEL.md
  INGESTION_VENTRA.md
  API_ENDPOINT_CATALOG.md
  TROUBLESHOOTING.md
  SECURITY_INCIDENT_PLAYBOOK.md
  RUNBOOK.md
  ONBOARDING.md
  ENTRA_SETUP.md
  PHASE_1_CENSUS_PORTAL.md
  GLOSSARY.md
  VENTRA_DATA_REQUIREMENTS.md
  VENTRA_QUESTIONS.md
  VENTRA_SCRIPT_30MIN.md
  VENTRA_FOLLOWUP_EMAIL.md
  boards/OPERATIONS.md
  boards/FINANCE.md
  boards/CLINICAL.md
  boards/PEOPLE.md
  boards/DOCTOR_SCORECARDS.md
  adr/001-hipaa-data-classification.md
  adr/002-rbac-model.md
  adr/003-audit-chain.md
  adr/004-backup-and-disaster-recovery.md
  adr/005-fl-tx-scope-split.md
)

# Counters
total=${#FILES[@]}
success=0
failed=0
skipped=0
failed_files=()

echo "Converting $total markdown files to PDF..."
echo "Output: $OUT_DIR/"
echo

for f in "${FILES[@]}"; do
  if [ ! -f "$f" ]; then
    echo "  SKIP: $f (file not found)"
    skipped=$((skipped+1))
    continue
  fi

  out="$OUT_DIR/${f%.md}.pdf"
  out_dir_for_file=$(dirname "$out")
  mkdir -p "$out_dir_for_file"

  echo -n "  $f → $out ... "
  if pandoc "${PANDOC_OPTS[@]}" "$f" -o "$out" 2>/tmp/pandoc-err.log; then
    echo "OK"
    success=$((success+1))
  else
    echo "FAIL"
    failed=$((failed+1))
    failed_files+=("$f")
    if [ -s /tmp/pandoc-err.log ]; then
      echo "    (see /tmp/pandoc-err.log for details)"
    fi
  fi
done

echo
echo "===== Summary ====="
echo "  Total:    $total"
echo "  Success:  $success"
echo "  Failed:   $failed"
echo "  Skipped:  $skipped"

if [ $failed -gt 0 ]; then
  echo
  echo "Failed files:"
  printf '  - %s\n' "${failed_files[@]}"
  echo
  echo "Common causes:"
  echo "  - Mermaid diagram syntax error → check the diagram source"
  echo "  - LaTeX special characters → escape with backslash"
  echo "  - Missing mermaid-filter → npm install -g mermaid-filter"
  exit 1
fi

echo
echo "All PDFs are in $OUT_DIR/"
echo
echo "To upload to SharePoint:"
echo "  1. Compress: zip -r hha-dashboard-docs.zip $OUT_DIR"
echo "  2. Open SharePoint → Documents → Upload → zip file"
echo "  3. Or drag-and-drop individual PDFs into the appropriate library folder"
