#!/usr/bin/env python3
"""
Phase 5: Build the NIBBLE.LIBRARY ProDOS hard-drive image.

Steps:
  1. Create a fresh 800KB ProDOS .po image
  2. Copy PRODOS + BASIC.SYSTEM from ProDOS_2.4.2.dsk
  3. Build load-address lookup from disk-jsons
  4. Stage all program files into /tmp with NAPS-encoded filenames
  5. Bulk-add staged files via cp2 (one call per year dir)
  6. Import menu BASIC files via cp2 import bas (one call)
  7. Write build-report.txt
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ─── Configuration ────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
CP2 = "cp2"
DATA_DIR = REPO_ROOT / "data"
DIST_DIR = REPO_ROOT / "dist"
DIST_DIR.mkdir(exist_ok=True)
BASE_DISK = Path("/Users/brobert/Desktop/Disks/ProDOS_2.4.2.dsk")
OUTPUT_IMAGE = DIST_DIR / "Nibble 1 and 2 liner collection.po"
EXTRACTED = DATA_DIR / "extracted"
EXTRACTED_PATCHED = DATA_DIR / "extracted_patched"
TOPIC_ASSIGNMENTS = DATA_DIR / "topic-assignments.json"
DISK_JSONS_DIR = DATA_DIR / "disk-jsons"
BUILD_REPORT_OUT = DIST_DIR / "build-report.txt"
STAGE_DIR = Path("/tmp/nibble-stage")

# ProDOS file type codes for NAPS filenames: NAME#TTAAAA
# TT = type byte hex, AAAA = aux address hex
NAPS_BAS = "fc0801"   # Applesoft BASIC, load $0801
NAPS_TXT = "040000"   # Text file, aux $0000

# Launcher / system files to skip
SKIP_NAMES = {"HELLO", "STARTUP", "PRODOS", "BASIC.SYSTEM"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def run(cmd: list, cwd=None) -> tuple[int, bytes, str]:
    result = subprocess.run(cmd, capture_output=True, cwd=cwd)
    return result.returncode, result.stdout, result.stderr.decode("utf-8", errors="replace")


def safe_filename(name: str) -> str:
    return name.replace(" ", "_").replace("/", "_")


def naps_bin(addr: int) -> str:
    """NAPS suffix for a binary file with given load address."""
    return f"06{addr:04x}"


# ─── Task 1: Create 800KB ProDOS Image ───────────────────────────────────────

def create_image() -> None:
    print("Creating 800KB ProDOS image…")
    if OUTPUT_IMAGE.exists():
        OUTPUT_IMAGE.unlink()
    rc, _, err = run([CP2, "create-disk-image", str(OUTPUT_IMAGE), "800kb", "prodos"])
    if rc != 0 or not OUTPUT_IMAGE.exists():
        sys.exit(f"FATAL: Cannot create image: {err}")
    run([CP2, "rename", str(OUTPUT_IMAGE), "/", "NIBBLE.1AND2"])
    print(f"  Created: {OUTPUT_IMAGE} ({OUTPUT_IMAGE.stat().st_size:,} bytes)")


# ─── Task 2: Copy PRODOS + BASIC.SYSTEM ──────────────────────────────────────

def copy_system_files() -> None:
    print("Copying PRODOS and BASIC.SYSTEM from base image…")
    rc, _, err = run([CP2, "copy", str(BASE_DISK), "PRODOS", "BASIC.SYSTEM",
                      str(OUTPUT_IMAGE)])
    if rc != 0:
        sys.exit(f"FATAL: Cannot copy system files: {err}")
    print("  Copied PRODOS and BASIC.SYSTEM")


# ─── Task 3: Build Load-Address Lookup ───────────────────────────────────────

def build_load_addr_table() -> dict[tuple[str, str], int]:
    table = {}
    year_part_re = re.compile(r"(\d{4}).*?[Pp]art\s*(\d+)")
    year_only_re = re.compile(r"(\d{4})")

    for jfile in sorted(DISK_JSONS_DIR.glob("*.json")):
        raw = json.loads(jfile.read_text())
        fn = jfile.stem
        m = year_part_re.search(fn)
        if m:
            disk_key = f"{m.group(1)}_PT{m.group(2)}"
        else:
            m2 = year_only_re.search(fn)
            if not m2:
                continue
            disk_key = f"{m2.group(1)}_PT1"

        for disk in raw.get("disks", []):
            for entry in disk.get("files", []):
                if entry.get("type") not in ("B", "BIN"):
                    continue
                addr_str = entry.get("address") or entry.get("auxType", "0")
                addr_str = addr_str.replace("A=", "").replace("$", "").strip()
                try:
                    addr = int(addr_str, 16)
                except ValueError:
                    addr = 0
                table[(disk_key, entry["name"])] = addr

    return table


# ─── Task 4: Stage all files ──────────────────────────────────────────────────

def find_source_file(disk_key: str, original_name: str) -> Optional[Path]:
    safe = safe_filename(original_name)
    for base_dir in [EXTRACTED_PATCHED, EXTRACTED]:
        candidate = base_dir / disk_key / safe
        if candidate.exists():
            return candidate
    return None


def get_file_type(disk_key: str, original_name: str, manifest_by_disk: dict) -> str:
    disk_files = manifest_by_disk.get(disk_key, {})
    return disk_files.get(original_name, {}).get("type", "A")


def build_manifest_lookup(manifest: dict) -> dict[str, dict[str, dict]]:
    lookup = {}
    for disk in manifest["disks"]:
        key = f"{disk['year']}_PT{disk['part']}"
        lookup[key] = {f["name"]: f for f in disk["files"]}
    return lookup


def stage_programs(
    programs: list[dict],
    manifest_by_disk: dict,
    load_addr_table: dict,
) -> tuple[int, int, list[str]]:
    """
    Copy each canonical program into STAGE_DIR/Y{year}/ with a NAPS-encoded
    filename so cp2 add --preserve=naps sets the correct ProDOS file type and
    aux address in one bulk operation.

    Returns (staged_count, skipped_count, error_list).
    """
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)
    STAGE_DIR.mkdir(parents=True)

    staged = 0
    skipped = 0
    errors = []

    for prog in programs:
        disk_key = prog["disk_key"]
        orig_name = prog["original_name"]
        prodos_name = prog["prodos_name"]
        year = prog["year"]

        if orig_name in SKIP_NAMES or prodos_name in SKIP_NAMES:
            skipped += 1
            continue

        if not prog.get("best", True):
            skipped += 1
            continue

        topics = prog.get("topics", [])
        if topics and topics[0] == "DOCS":
            file_type_check = get_file_type(disk_key, orig_name, manifest_by_disk)
            if file_type_check == "A":
                skipped += 1
                continue

        src = find_source_file(disk_key, orig_name)
        if src is None:
            msg = f"MISSING: {disk_key}/{orig_name} -> {prodos_name}"
            errors.append(msg)
            print(f"  {msg}")
            continue

        file_type = get_file_type(disk_key, orig_name, manifest_by_disk)

        if file_type == "A":
            naps = NAPS_BAS
        elif file_type == "B":
            _sentinel = object()
            raw_addr = load_addr_table.get((disk_key, orig_name), _sentinel)
            if (re.search(r'\.PIC\d*$', orig_name.upper()) or
                    re.search(r'\.P\d+$', prodos_name.upper())):
                raw_addr = 0x4000
            if raw_addr is _sentinel:
                raw_addr = 0x2000
                print(f"  WARN: no load addr for {disk_key}/{orig_name}, defaulting to $2000")
            naps = naps_bin(raw_addr)
        else:
            naps = NAPS_TXT

        year_dir = STAGE_DIR / f"Y{year}"
        year_dir.mkdir(exist_ok=True)
        dest = year_dir / f"{prodos_name}#{naps}"
        dest.write_bytes(src.read_bytes())
        staged += 1

    return staged, skipped, errors


# ─── Task 5: Bulk-add staged files via cp2 ───────────────────────────────────

def bulk_add_programs(years: list[int]) -> None:
    print("\nBulk-adding program files via cp2…")
    for year in years:
        year_dir = STAGE_DIR / f"Y{year}"
        if not year_dir.exists():
            continue
        count = sum(1 for _ in year_dir.iterdir())
        rc, _, err = run(
            [CP2, "add", "--preserve=naps", str(OUTPUT_IMAGE), f"Y{year}"],
            cwd=STAGE_DIR,
        )
        if rc != 0:
            sys.exit(f"FATAL: cp2 add failed for Y{year}: {err}")
        print(f"  Y{year}: {count} files")


# ─── Task 6: Add menu and data files ─────────────────────────────────────────

def add_menu_files(programs: list[dict]) -> int:
    """
    Add menu BASIC programs (tokenized via cp2 import bas), MENU stub into
    each year directory, data files, and instruction .T files.
    Returns count of files added.
    """
    added = 0
    errors = []

    # Tokenize root menu BASIC programs.
    # cp2 import bas derives the ProDOS filename from the host filename,
    # stripping the extension. Run from a staging dir with just bare filenames
    # so they land at the root, not under a path like dist/STARTUP.
    print("\nImporting root menu BASIC programs…")
    menu_bas_stage = STAGE_DIR / "_menu_bas"
    menu_bas_stage.mkdir(parents=True, exist_ok=True)
    bas_names = []
    for name in ['STARTUP', 'MENU', 'BY.YEAR', 'BY.NAME', 'BY.TOPIC']:
        bas_path = DIST_DIR / f'{name}.bas'
        if not bas_path.exists():
            errors.append(f"MISSING menu file: {bas_path}")
            print(f"  MISSING: {bas_path}")
        else:
            (menu_bas_stage / f'{name}.bas').write_bytes(bas_path.read_bytes())
            bas_names.append(f'{name}.bas')
    if bas_names:
        rc, _, err = run(
            [CP2, "import", str(OUTPUT_IMAGE), "bas"] + bas_names,
            cwd=menu_bas_stage,
        )
        if rc != 0:
            errors.append(f"WRITE FAIL menu bas: {err.strip()[:120]}")
            print(f"  ERROR importing menu bas files: {err.strip()[:120]}")
        else:
            print(f"  Imported: {', '.join(Path(n).stem for n in bas_names)}")
            added += len(bas_names)

    # Tokenize MENU stub into each year subdirectory.
    # Stage as Y{year}/MENU.bas and run cp2 import from the staging root so the
    # ProDOS path becomes Y{year}/MENU.
    print("\nImporting MENU stub into year subdirectories…")
    stub_path = DIST_DIR / 'MENU.STUB.bas'
    if not stub_path.exists():
        errors.append(f"MISSING menu stub: {stub_path}")
        print(f"  MISSING: {stub_path}")
    else:
        stub_years = sorted({p['year'] for p in programs if p.get('best', True)})
        stub_stage = STAGE_DIR / "_stubs"
        stub_stage.mkdir(parents=True, exist_ok=True)
        stub_src = stub_path.read_bytes()
        stub_rel_paths = []
        for year in stub_years:
            year_dir = stub_stage / f"Y{year}"
            year_dir.mkdir(exist_ok=True)
            (year_dir / "MENU.bas").write_bytes(stub_src)
            stub_rel_paths.append(f"Y{year}/MENU.bas")
        rc, _, err = run(
            [CP2, "import", str(OUTPUT_IMAGE), "bas"] + stub_rel_paths,
            cwd=stub_stage,
        )
        if rc != 0:
            errors.append(f"WRITE FAIL year MENU stubs: {err.strip()[:120]}")
            print(f"  ERROR: {err.strip()[:120]}")
        else:
            print(f"  Imported MENU stub into {len(stub_years)} year directories")
            added += len(stub_years)

    # Stage data files (TXT type) and add in one cp2 add call
    print("\nAdding data files…")
    data_stage = STAGE_DIR / "_data"
    data_stage.mkdir(parents=True, exist_ok=True)
    data_fnames = ['NAME.DATA', 'YEAR.DATA', 'TOPIC.DATA']
    missing_data = []
    for fname in data_fnames:
        src = DIST_DIR / fname
        if not src.exists():
            errors.append(f"MISSING data file: {src}")
            missing_data.append(fname)
        else:
            (data_stage / f"{fname}#{NAPS_TXT}").write_bytes(src.read_bytes())
    if not missing_data:
        rc, _, err = run(
            [CP2, "add", "--preserve=naps", str(OUTPUT_IMAGE)] +
            [f"{fname}#{NAPS_TXT}" for fname in data_fnames],
            cwd=data_stage,
        )
        if rc != 0:
            errors.append(f"WRITE FAIL data files: {err.strip()[:120]}")
            print(f"  ERROR adding data files: {err.strip()[:120]}")
        else:
            print(f"  Added: {', '.join(data_fnames)}")
            added += len(data_fnames)

    # Stage instruction .T text files into year subdirs and bulk-add per year
    instr_manifest_path = DIST_DIR / 'instr-manifest.json'
    if instr_manifest_path.exists():
        print("\nAdding instruction .T text files…")
        instr_manifest = json.loads(instr_manifest_path.read_text())
        # Stage into STAGE_DIR/_txt/Y{year}/ then add each year dir
        txt_root = STAGE_DIR / "_txt"
        txt_root.mkdir(exist_ok=True)
        by_year: dict[int, list[Path]] = {}
        for entry in instr_manifest:
            local_path = Path(entry['local_path'])
            if not local_path.exists():
                print(f"  MISSING .T file: {local_path}")
                continue
            year = entry['year']
            year_dir = txt_root / f"Y{year}"
            year_dir.mkdir(exist_ok=True)
            dest = year_dir / f"{entry['txt_name']}#{NAPS_TXT}"
            dest.write_bytes(local_path.read_bytes())
            by_year.setdefault(year, []).append(dest)

        added_txt = 0
        for year in sorted(by_year):
            rc, _, err = run(
                [CP2, "add", "--preserve=naps", str(OUTPUT_IMAGE), f"Y{year}"],
                cwd=txt_root,
            )
            if rc != 0:
                print(f"  ERROR adding .T files for Y{year}: {err.strip()[:80]}")
            else:
                added_txt += len(by_year[year])
        print(f"  Added {added_txt} .T instruction files")
        added += added_txt
    else:
        print(f"\nWARNING: instr-manifest.json not found — run generate_menus.py first")

    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(f"FATAL: {len(errors)} errors adding menu/data files")

    return added


# ─── Task 7: Verify & Report ─────────────────────────────────────────────────

def verify_and_report(staged: int, skipped: int, errors: list[str]) -> None:
    print("\nVerifying image contents…")
    rc, listing_bytes, _ = run([CP2, "catalog", str(OUTPUT_IMAGE)])
    listing = listing_bytes.decode("utf-8", errors="replace")

    # Count files per year directory from cp2 catalog output.
    # cp2 lists subdirectory files as "Y1984:FILENAME" on each line.
    year_counts: dict[str, int] = {}
    for line in listing.splitlines():
        m = re.search(r'\bY(\d{4}):(\S+)', line)
        if m:
            year = m.group(1)
            year_counts[year] = year_counts.get(year, 0) + 1

    image_size = OUTPUT_IMAGE.stat().st_size

    report_lines = [
        "NIBBLE.LIBRARY Build Report",
        "=" * 50,
        f"Image: {OUTPUT_IMAGE}",
        f"Image size: {image_size:,} bytes ({image_size // 1024} KB)",
        "",
        f"Programs staged: {staged}",
        f"Programs skipped (launchers/not-best): {skipped}",
        f"Errors: {len(errors)}",
        "",
        "Files per year directory:",
    ]
    for year in sorted(year_counts):
        report_lines.append(f"  Y{year}: {year_counts[year]} files")

    if errors:
        report_lines.append("")
        report_lines.append("Errors:")
        for e in errors:
            report_lines.append(f"  {e}")

    report_lines.append("")
    report_lines.append("Image catalog:")
    report_lines.append(listing)

    report_text = "\n".join(report_lines)
    BUILD_REPORT_OUT.write_text(report_text)
    print(f"Build report written to {BUILD_REPORT_OUT}")
    print(f"  {image_size:,} bytes used; year file counts: " +
          ", ".join(f"Y{y}={c}" for y, c in sorted(year_counts.items())))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Phase 5: Building NIBBLE.LIBRARY.po")
    print("=" * 60)

    programs = json.loads(TOPIC_ASSIGNMENTS.read_text())
    manifest = json.loads((DATA_DIR / "file-manifest.json").read_text())
    manifest_by_disk = build_manifest_lookup(manifest)
    load_addr_table = build_load_addr_table()
    print(f"Loaded {len(programs)} program entries")
    print(f"Load address table: {len(load_addr_table)} binary file entries")

    create_image()
    copy_system_files()

    print(f"\nStaging {len(programs)} programs…")
    staged, skipped, errors = stage_programs(programs, manifest_by_disk, load_addr_table)
    print(f"Staged: {staged}, skipped: {skipped}, errors: {len(errors)}")

    years = sorted({p['year'] for p in programs if p.get('best', True)})
    bulk_add_programs(years)

    menu_added = add_menu_files(programs)
    print(f"\nMenu/data files added: {menu_added}")

    verify_and_report(staged, skipped, errors)


if __name__ == "__main__":
    main()
