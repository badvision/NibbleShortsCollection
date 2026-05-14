#!/usr/bin/env python3
"""
Phase 5: Build the NIBBLE.LIBRARY ProDOS hard-drive image.

Steps:
  1. Create a fresh 2MB ProDOS .po image
  2. Copy PRODOS + BASIC.SYSTEM from ProDOS_2.4.2.dsk
  3. Build load-address lookup from disk-jsons
  4. Populate all 639 canonical programs into year directories
  5. Write TOPIC.INDEX to image root
  6. Write build-report.txt
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ─── Configuration ────────────────────────────────────────────────────────────
# Repo root: parent of the src/ directory containing this script
REPO_ROOT = Path(__file__).parent.parent
# Use APPLECOMMANDER_JAVA env var to override, otherwise find Java 21+ automatically.
# AppleCommander requires Java 21+ (class file version 65.0).
def _find_java() -> str:
    override = os.environ.get("APPLECOMMANDER_JAVA")
    if override:
        return override
    candidates = [
        "/opt/homebrew/Cellar/openjdk/25.0.2/libexec/openjdk.jdk/Contents/Home/bin/java",
        "/opt/homebrew/opt/openjdk/bin/java",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return "java"

JAVA = _find_java()
AC_JAR = str(REPO_ROOT / "tools" / "AppleCommander-ac.jar")
CP2 = "cp2"  # Use system cp2 via PATH
DATA_DIR = REPO_ROOT / "data"
DIST_DIR = REPO_ROOT / "dist"
DIST_DIR.mkdir(exist_ok=True)
BASE_DISK = Path("/Users/brobert/Desktop/Disks/ProDOS_2.4.2.dsk")
OUTPUT_IMAGE = DIST_DIR / "NIBBLE.LIBRARY.po"
EXTRACTED = DATA_DIR / "extracted"
EXTRACTED_PATCHED = DATA_DIR / "extracted_patched"  # not used in repo (already merged into extracted)
TOPIC_ASSIGNMENTS = DATA_DIR / "topic-assignments.json"
NAME_MAPPING = DATA_DIR / "name-mapping.json"
DISK_JSONS_DIR = DATA_DIR / "disk-jsons"
TOPIC_INDEX_OUT = DIST_DIR / "TOPIC.INDEX"
BUILD_REPORT_OUT = DIST_DIR / "build-report.txt"

# Launcher / system files to skip
SKIP_NAMES = {"HELLO", "STARTUP", "PRODOS", "BASIC.SYSTEM"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def run(cmd: list, stdin_bytes: Optional[bytes] = None):
    result = subprocess.run(
        cmd,
        input=stdin_bytes,
        capture_output=True,
    )
    return result.returncode, result.stdout, result.stderr.decode("utf-8", errors="replace")


def ac(*args, stdin_bytes: Optional[bytes] = None):
    return run([JAVA, "-jar", AC_JAR] + list(args), stdin_bytes=stdin_bytes)


def safe_filename(name: str) -> str:
    """Convert original disk name to safe filesystem name (spaces → underscores)."""
    return name.replace(" ", "_").replace("/", "_")


# ─── Task 1: Create 2MB ProDOS Image ─────────────────────────────────────────

def create_image() -> None:
    print("Creating 800KB ProDOS image…")
    if OUTPUT_IMAGE.exists():
        OUTPUT_IMAGE.unlink()
    rc, _, err = run([CP2, "create-disk-image", str(OUTPUT_IMAGE), "800kb", "prodos"])
    if rc != 0 or not OUTPUT_IMAGE.exists():
        print(f"  cp2 create-disk-image failed: {err}")
        print("  Falling back to AppleCommander pro800…")
        rc, _, err = ac(f"-pro800", str(OUTPUT_IMAGE), "NIBBLE.1AND2")
        if rc != 0 or not OUTPUT_IMAGE.exists():
            sys.exit(f"FATAL: Cannot create image: {err}")
    # Rename volume (cp2 names it NEWDISK by default)
    run([CP2, "rename", str(OUTPUT_IMAGE), "/", "NIBBLE.1AND2"])
    print(f"  Created: {OUTPUT_IMAGE} ({OUTPUT_IMAGE.stat().st_size:,} bytes)")


# ─── Task 2: Copy PRODOS + BASIC.SYSTEM ──────────────────────────────────────

def copy_system_files() -> None:
    print("Copying PRODOS and BASIC.SYSTEM from base image…")
    # Use cp2 copy to preserve exact binary content — AppleCommander -p corrupts
    # the first $200 bytes of SYS files (zeros them out), breaking ProDOS boot.
    rc, _, err = run([CP2, "copy", str(BASE_DISK), "PRODOS", "BASIC.SYSTEM",
                      str(OUTPUT_IMAGE)])
    if rc != 0:
        sys.exit(f"FATAL: Cannot copy system files: {err}")
    for fname in ["PRODOS", "BASIC.SYSTEM"]:
        rc2, data, err2 = ac("-g", str(OUTPUT_IMAGE), fname)
        print(f"  Copied {fname} ({len(data):,} bytes)")


# ─── Task 3: Build Load-Address Lookup ───────────────────────────────────────

def build_load_addr_table() -> dict[tuple[str, str], int]:
    """
    Returns { (disk_key, original_name): load_addr_int } for all binary files.
    Parses address strings like "A=$0300", "$4000", "A=$0000".
    """
    table = {}
    year_part_re = re.compile(r"(\d{4}).*?[Pp]art\s*(\d+)")
    year_only_re = re.compile(r"(\d{4})")

    for jfile in sorted(DISK_JSONS_DIR.glob("*.json")):
        raw = json.loads(jfile.read_text())
        # Derive disk_key from filename
        fn = jfile.stem  # e.g. "Nibble One and Two Liners (1984)"
        m = year_part_re.search(fn)
        if m:
            disk_key = f"{m.group(1)}_PT{m.group(2)}"
        else:
            m2 = year_only_re.search(fn)
            if not m2:
                continue
            disk_key = f"{m2.group(1)}_PT1"

        disks = raw.get("disks", [])
        for disk in disks:
            for entry in disk.get("files", []):
                if entry.get("type") != "B":
                    continue
                addr_str = entry.get("address", "A=$0000")
                # Strip leading "A=" if present
                addr_str = addr_str.replace("A=", "").strip()
                try:
                    addr = int(addr_str, 16)
                except ValueError:
                    addr = 0
                table[(disk_key, entry["name"])] = addr

    return table


# ─── Task 4: Populate Programs ───────────────────────────────────────────────

def find_source_file(disk_key: str, original_name: str) -> Optional[Path]:
    """
    Returns path to the source file. Checks patched first, then extracted.
    Filenames on disk use underscores for spaces.
    """
    safe = safe_filename(original_name)
    for base_dir in [EXTRACTED_PATCHED, EXTRACTED]:
        candidate = base_dir / disk_key / safe
        if candidate.exists():
            return candidate
    return None


def get_file_type(disk_key: str, original_name: str, manifest_by_disk: dict) -> str:
    """Returns 'A' (Applesoft), 'B' (Binary), or 'T' (Text)."""
    disk_files = manifest_by_disk.get(disk_key, {})
    return disk_files.get(original_name, {}).get("type", "A")


def build_manifest_lookup(manifest: dict) -> dict[str, dict[str, dict]]:
    """Returns { disk_key: { original_name: file_entry } }."""
    lookup = {}
    for disk in manifest["disks"]:
        key = f"{disk['year']}_PT{disk['part']}"
        lookup[key] = {f["name"]: f for f in disk["files"]}
    return lookup


def populate_programs(
    programs: list[dict],
    manifest_by_disk: dict,
    load_addr_table: dict,
):
    """
    Writes each canonical program to the image under /Y{YEAR}/{PRODOS_NAME}.
    Returns (success_count, skip_count, error_list).
    """
    success = 0
    skipped = 0
    errors = []

    for prog in programs:
        disk_key = prog["disk_key"]
        orig_name = prog["original_name"]
        prodos_name = prog["prodos_name"]
        year = prog["year"]

        # Skip launcher files
        if orig_name in SKIP_NAMES or prodos_name in SKIP_NAMES:
            skipped += 1
            continue

        # Only include canonical (best=True) programs
        if not prog.get("best", True):
            skipped += 1
            continue

        # Skip DOCS BASIC files — they're instruction text converted to .T files.
        # DOCS BIN files (pics) are still needed for BLOAD by the parent program.
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
            ac_type = "BAS"
            load_addr = "0x0801"
        elif file_type == "B":
            ac_type = "BIN"
            raw_addr = load_addr_table.get((disk_key, orig_name), 0)
            # .PIC and .PICn files always load at $4000
            if (re.search(r'\.PIC\d*$', orig_name.upper()) or
                    re.search(r'\.PIC\d*$', prodos_name.upper())):
                raw_addr = 0x4000
            load_addr = hex(raw_addr) if raw_addr else "0x2000"
        else:
            ac_type = "TXT"
            load_addr = "0x0000"

        image_path = f"Y{year}/{prodos_name}"
        src_data = src.read_bytes()

        rc, _, err = ac(
            "-p", str(OUTPUT_IMAGE), image_path, ac_type, load_addr,
            stdin_bytes=src_data,
        )
        if rc != 0:
            msg = f"WRITE FAIL: {image_path}: {err.strip()}"
            errors.append(msg)
            print(f"  {msg}")
        else:
            success += 1
            if success % 50 == 0:
                print(f"  Written {success} files…")

    return success, skipped, errors


# ─── Task 5: Build TOPIC.INDEX ────────────────────────────────────────────────

def build_topic_index(programs: list[dict]) -> str:
    """
    Builds TOPIC.INDEX lines: YEAR\tPRODOS_NAME\tPRIMARY\tSECONDARY\tDISPLAY_NAME
    Only includes canonical programs (best=True, not skip names).
    """
    lines = []
    for prog in programs:
        if not prog.get("best", True):
            continue
        orig = prog["original_name"]
        if orig in SKIP_NAMES:
            continue
        year = str(prog["year"])
        prodos_name = prog["prodos_name"]
        topics = prog.get("topics") or []
        primary = topics[0] if topics else ""
        secondary = topics[1] if len(topics) > 1 else ""
        display = orig[:30]
        lines.append(f"{year}\t{prodos_name}\t{primary}\t{secondary}\t{display}")
    return "\n".join(lines) + "\n"


# ─── Task 6: Verify & Report ─────────────────────────────────────────────────

def verify_and_report(success: int, skipped: int, errors: list[str]) -> None:
    print("\nVerifying image contents…")
    rc, _, err = ac("-i", str(OUTPUT_IMAGE))
    rc2, listing, err2 = ac("-ll", str(OUTPUT_IMAGE))

    # Count files per year
    year_counts: dict[str, int] = {}
    current_dir = ""
    for line in listing.decode("utf-8", errors="replace").splitlines():
        # AppleCommander indents subdir entries with leading spaces
        stripped = line.strip()
        if stripped.startswith("Y") and "DIR" in line and not stripped.startswith(" "):
            # Top-level directory line
            m = re.search(r"\bY(\d{4})\b", stripped)
            if m:
                current_dir = m.group(1)
                year_counts[current_dir] = 0
        elif stripped and not stripped.startswith("Y") and current_dir:
            # File inside current year dir
            if not stripped.startswith("ProDOS format") and "DIR" not in line:
                year_counts[current_dir] = year_counts.get(current_dir, 0) + 1

    image_size = OUTPUT_IMAGE.stat().st_size

    report_lines = [
        "NIBBLE.LIBRARY Build Report",
        "=" * 50,
        f"Image: {OUTPUT_IMAGE}",
        f"Image size: {image_size:,} bytes ({image_size // 1024} KB)",
        f"",
        f"Programs written: {success}",
        f"Programs skipped (launchers/not-best): {skipped}",
        f"Errors: {len(errors)}",
        f"",
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
    report_lines.append("Image directory listing (root):")
    for line in listing.decode("utf-8", errors="replace").splitlines():
        report_lines.append(f"  {line}")

    report_text = "\n".join(report_lines)
    BUILD_REPORT_OUT.write_text(report_text)
    print(f"Build report written to {BUILD_REPORT_OUT}")
    print(report_text)


# ─── Main ─────────────────────────────────────────────────────────────────────

def add_menu_files() -> int:
    """
    Add generated menu BASIC programs, data files, and instruction .T files
    to the image. These are produced by generate_menus.py into dist/.
    Returns count of files added.
    """
    added = 0
    errors = []

    # Add menu BASIC programs (tokenized)
    print("\nAdding menu BASIC programs...")
    for name in ['STARTUP', 'MENU', 'BY.YEAR', 'BY.NAME', 'BY.TOPIC']:
        bas_path = DIST_DIR / f'{name}.bas'
        if not bas_path.exists():
            errors.append(f"MISSING menu file: {bas_path}")
            print(f"  MISSING: {bas_path}")
            continue
        bas_text = bas_path.read_bytes()
        rc, _, err = ac('-bas', str(OUTPUT_IMAGE), name, stdin_bytes=bas_text)
        if rc != 0:
            errors.append(f"WRITE FAIL {name}: {err.strip()}")
            print(f"  ERROR adding {name}: {err.strip()[:80]}")
        else:
            print(f"  Added: {name}")
            added += 1

    # Add data files (NAME.DATA, YEAR.DATA, TOPIC.DATA)
    print("\nAdding data files...")
    for fname in ['NAME.DATA', 'YEAR.DATA', 'TOPIC.DATA']:
        data_path = DIST_DIR / fname
        if not data_path.exists():
            errors.append(f"MISSING data file: {data_path}")
            print(f"  MISSING: {data_path}")
            continue
        data_bytes = data_path.read_bytes()
        rc, _, err = ac('-p', str(OUTPUT_IMAGE), fname, 'TXT', '0x0000', stdin_bytes=data_bytes)
        if rc != 0:
            errors.append(f"WRITE FAIL {fname}: {err.strip()}")
            print(f"  ERROR adding {fname}: {err.strip()[:80]}")
        else:
            print(f"  Added: {fname} ({len(data_bytes):,} bytes)")
            added += 1

    # Add instruction .T text files using the manifest from generate_menus.py
    instr_manifest_path = DIST_DIR / 'instr-manifest.json'
    if instr_manifest_path.exists():
        print("\nAdding instruction .T text files...")
        instr_manifest = json.loads(instr_manifest_path.read_text())
        added_txt = 0
        for entry in instr_manifest:
            year = entry['year']
            txt_name = entry['txt_name']
            local_path = entry['local_path']
            prodos_dest = f'Y{year}/{txt_name}'
            if not Path(local_path).exists():
                print(f"  MISSING .T file: {local_path}")
                continue
            data = Path(local_path).read_bytes()
            rc, _, err = ac('-p', str(OUTPUT_IMAGE), prodos_dest, 'TXT', '0x0000', stdin_bytes=data)
            if rc != 0:
                print(f"  ERROR adding {prodos_dest}: {err.strip()[:80]}")
            else:
                added_txt += 1
        print(f"  Added {added_txt} .T instruction files")
        added += added_txt
    else:
        print(f"\nWARNING: instr-manifest.json not found at {instr_manifest_path}")
        print("  Run generate_menus.py first to produce instruction files")

    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(f"FATAL: {len(errors)} menu file errors")

    return added


def main():
    print("=" * 60)
    print("Phase 5: Building NIBBLE.LIBRARY.po")
    print("=" * 60)

    # Load data files
    programs = json.loads(TOPIC_ASSIGNMENTS.read_text())
    manifest = json.loads((DATA_DIR / "file-manifest.json").read_text())
    manifest_by_disk = build_manifest_lookup(manifest)
    load_addr_table = build_load_addr_table()
    print(f"Loaded {len(programs)} program entries")
    print(f"Load address table: {len(load_addr_table)} binary file entries")

    # Step 1: Create image
    create_image()

    # Step 2: System files
    copy_system_files()

    # Step 3: Populate programs
    print(f"\nPopulating {len(programs)} programs…")
    success, skipped, errors = populate_programs(programs, manifest_by_disk, load_addr_table)
    print(f"Done: {success} written, {skipped} skipped, {len(errors)} errors")

    # Step 4: Add menu files generated by generate_menus.py
    menu_added = add_menu_files()
    print(f"\nMenu files added: {menu_added}")

    # Step 6: Verify & report
    verify_and_report(success, skipped, errors)


if __name__ == "__main__":
    main()
