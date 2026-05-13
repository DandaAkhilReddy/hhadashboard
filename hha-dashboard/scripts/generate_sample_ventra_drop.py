#!/usr/bin/env python3
"""Generate a deterministic sample Ventra drop for local smoke-testing.

Produces the four files Ventra would deliver for a single drop_date:

  collections.csv          25 rows  (5 facilities x 5 payer_classes)
  ar_snapshot.csv          30 rows  (5 facilities x 6 aging buckets)
  physician_monthly.csv    50 rows  (10 NPIs x 5 facilities) — present
                                    only when drop_date.day == 1 (mimics
                                    Ventra's month-close behavior; pass
                                    --include-monthly to force on any day)
  _MANIFEST.csv            written last, with sha256 + row_count per file

Data values are deterministic: each cell is a function of (facility_no,
payer_class / aging_bucket / npi index) so re-running the generator with
the same drop_date produces byte-identical files. That lets us check in
the output and trust the manifest sha256s won't drift.

Usage:
    python scripts/generate_sample_ventra_drop.py 2026-06-15 \\
        samples/ventra/sample-drop-2026-06-15

The first arg is the drop_date (YYYY-MM-DD). The second is the output
directory; created if it doesn't exist; existing files overwritten.

Facility_no values in the sample use the placeholder range 1..5 — these
must match real ``masters.sites.id`` values in your dev DB before the
ingest job's V12 validator will accept them. Seed via
``scripts/seed_sites.py`` first.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
from datetime import date
from pathlib import Path

FACILITIES = [1, 2, 3, 4, 5]
PAYER_CLASSES = ["commercial", "medicare", "medicaid", "selfpay", "other"]
AGING_BUCKETS = ["0-30", "31-60", "61-90", "91-120", "120+", "credit"]
# 10 well-formed but synthetic NPIs. The Luhn check digit is not validated
# by the ingest pipeline (just the 10-digit pattern), so these will pass
# V11 / DB CHECK on physician_mo_npi_10_digit.
NPIS = [
    "1000000007", "1000000015", "1000000023", "1000000031", "1000000049",
    "1000000056", "1000000064", "1000000072", "1000000080", "1000000098",
]
VENDOR_SOURCE_SYSTEMS = ["CB", "MGS", "VSQL", "DUVA"]


def _vendor_tag(facility_no: int) -> str:
    """Spread facilities across vendor PM systems deterministically.
    Ventra-side reality: each facility maps to one of CB/MGS/VSQL/DUVA."""
    return VENDOR_SOURCE_SYSTEMS[facility_no % len(VENDOR_SOURCE_SYSTEMS)]


def _two(value: float) -> str:
    """Format Decimal-like value to 2-decimal-place string for CSV output."""
    return f"{value:.2f}"


def build_collections(drop_date: date) -> str:
    """One row per (drop_date, facility, payer_class) — 5 * 5 = 25 rows."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "date",
            "facility_no",
            "payer_class",
            "gross_charges",
            "payments_received",
            "contractual_adjustments",
            "write_offs",
            "payer_refunds",
            "patient_refunds",
            "net_revenue",
            "source_system",
        ]
    )
    for fac in FACILITIES:
        for i, payer in enumerate(PAYER_CLASSES):
            # Variance: more revenue from commercial than medicaid, etc.
            payer_weight = 1.0 - (i * 0.15)
            gross = round(40_000 * fac * payer_weight, 2)
            payments = round(gross * 0.85, 2)
            contractual = round(gross * 0.10, 2)
            write_offs = round(gross * 0.02, 2)
            payer_refunds = round(gross * 0.005, 2)
            patient_refunds = round(gross * 0.005, 2)
            net = round(payments - payer_refunds - patient_refunds, 2)
            writer.writerow(
                [
                    drop_date.isoformat(),
                    fac,
                    payer,
                    _two(gross),
                    _two(payments),
                    _two(contractual),
                    _two(write_offs),
                    _two(payer_refunds),
                    _two(patient_refunds),
                    _two(net),
                    _vendor_tag(fac),
                ]
            )
    return buf.getvalue()


def build_ar_snapshot(drop_date: date) -> str:
    """One row per (drop_date, facility, aging_bucket) — 5 * 6 = 30 rows.
    Credit bucket carries negative outstanding; all others non-negative."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        ["snapshot_date", "facility_no", "aging_bucket", "outstanding_amount", "source_system"]
    )
    # Bucket distribution: heavy in 0-30, tapering down, small credit balance.
    bucket_weights = {
        "0-30": 1.00,
        "31-60": 0.65,
        "61-90": 0.40,
        "91-120": 0.25,
        "120+": 0.15,
        "credit": -0.03,  # negative — credit balances
    }
    for fac in FACILITIES:
        base = 200_000 * fac
        for bucket in AGING_BUCKETS:
            amount = round(base * bucket_weights[bucket], 2)
            writer.writerow(
                [
                    drop_date.isoformat(),
                    fac,
                    bucket,
                    _two(amount),
                    _vendor_tag(fac),
                ]
            )
    return buf.getvalue()


def build_physician_monthly(month_first: date) -> str:
    """One row per (month, npi, facility) — 10 * 5 = 50 rows."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "month",
            "physician_npi",
            "facility_no",
            "encounters_count",
            "total_rvu",
            "total_work_rvu",
            "revenue_attributed",
            "source_system",
        ]
    )
    for fac in FACILITIES:
        for i, npi in enumerate(NPIS):
            encounters = 30 + (fac * 5) + i
            rvu = round(encounters * 2.2, 2)
            work_rvu = round(rvu * 0.78, 2)
            revenue = round(encounters * 850.0, 2)
            writer.writerow(
                [
                    month_first.isoformat(),
                    npi,
                    fac,
                    encounters,
                    _two(rvu),
                    _two(work_rvu),
                    _two(revenue),
                    _vendor_tag(fac),
                ]
            )
    return buf.getvalue()


def build_manifest(file_contents: dict[str, str]) -> str:
    """Compute sha256 + row_count for each data file and write the
    manifest CSV. file_contents is {file_name: csv_text}."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["file_name", "sha256", "row_count"])
    for name in sorted(file_contents):
        content = file_contents[name]
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        # Row count = lines - header. Trailing newline handled by splitlines.
        row_count = max(0, len(content.splitlines()) - 1)
        writer.writerow([name, sha, row_count])
    return buf.getvalue()


def generate(drop_date: date, output_dir: Path, include_monthly: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "collections.csv": build_collections(drop_date),
        "ar_snapshot.csv": build_ar_snapshot(drop_date),
    }
    # physician_monthly.csv is emitted only on month-close days unless forced.
    if include_monthly or drop_date.day == 1:
        # Vendor convention: month value = first-of-month for the period
        # being reported. On the 1st (drop_date.day == 1), we report the
        # PRIOR month (jobs do month-close after EOB).
        if drop_date.day == 1:
            month_year = drop_date.year - (1 if drop_date.month == 1 else 0)
            month_num = 12 if drop_date.month == 1 else drop_date.month - 1
            month_first = date(month_year, month_num, 1)
        else:
            month_first = date(drop_date.year, drop_date.month, 1)
        files["physician_monthly.csv"] = build_physician_monthly(month_first)

    manifest = build_manifest(files)

    for name, content in files.items():
        (output_dir / name).write_text(content, encoding="utf-8", newline="")
    (output_dir / "_MANIFEST.csv").write_text(manifest, encoding="utf-8", newline="")

    print(f"wrote {len(files) + 1} files to {output_dir}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("drop_date", help="YYYY-MM-DD")
    parser.add_argument("output_dir", type=Path, help="target directory")
    parser.add_argument(
        "--include-monthly",
        action="store_true",
        help="emit physician_monthly.csv regardless of drop_date.day",
    )
    args = parser.parse_args()

    try:
        drop_date = date.fromisoformat(args.drop_date)
    except ValueError as e:
        print(f"bad drop_date: {e}", file=sys.stderr)
        return 1

    generate(drop_date, args.output_dir, args.include_monthly)
    return 0


if __name__ == "__main__":
    sys.exit(main())
