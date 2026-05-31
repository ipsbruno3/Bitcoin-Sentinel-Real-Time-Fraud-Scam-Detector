"""
Verify every downloaded CSV: count rows, sanity-check header, surface
any zero-byte or malformed file.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path

ROOT = Path(__file__).parent
CSV_DIR = ROOT / "csvs"

def main():
    rows = []
    by_cat: dict[str, dict] = {}
    for cat_dir in sorted(CSV_DIR.iterdir()):
        if not cat_dir.is_dir():
            continue
        cat = cat_dir.name
        cat_stat = by_cat.setdefault(cat, {"files": 0, "rows": 0, "bytes": 0, "issues": []})
        for f in sorted(cat_dir.iterdir()):
            if not f.is_file() or f.suffix != ".csv":
                continue
            size = f.stat().st_size
            cat_stat["files"] += 1
            cat_stat["bytes"] += size
            n = 0
            issue = None
            try:
                with f.open("r", encoding="utf-8", newline="") as fh:
                    first = fh.readline()
                    if not first.startswith(("\"#", "#")):
                        issue = f"unexpected first line: {first[:80]!r}"
                    header = fh.readline().strip()
                    if not header.startswith("address,"):
                        issue = (issue or "") + f" | bad header: {header[:80]!r}"
                    for _ in fh:
                        n += 1
            except Exception as e:
                issue = f"read error: {e}"
            cat_stat["rows"] += n
            rows.append({"category": cat, "wallet": f.stem, "rows": n, "bytes": size, "issue": issue})
            if issue:
                cat_stat["issues"].append({"wallet": f.stem, "issue": issue})

    # Print summary
    total_files = sum(c["files"] for c in by_cat.values())
    total_rows = sum(c["rows"] for c in by_cat.values())
    total_bytes = sum(c["bytes"] for c in by_cat.values())
    print(f"=== Total: {total_files} CSVs, {total_rows:,} address rows, {total_bytes/1024/1024:.1f} MB ===\n")
    for cat, s in sorted(by_cat.items()):
        print(f"{cat:30s}  files={s['files']:4d}  rows={s['rows']:>12,}  size={s['bytes']/1024/1024:>8.1f} MB  issues={len(s['issues'])}")
        for it in s["issues"][:5]:
            print(f"    - {it['wallet']}: {it['issue']}")

    # Save manifest
    out = ROOT / "manifest.json"
    out.write_text(json.dumps({
        "summary": {
            "total_files": total_files,
            "total_address_rows": total_rows,
            "total_bytes": total_bytes,
            "by_category": {k: {kk: vv for kk, vv in v.items() if kk != "issues"} for k, v in by_cat.items()},
        },
        "files": rows,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote manifest -> {out}")

if __name__ == "__main__":
    main()
