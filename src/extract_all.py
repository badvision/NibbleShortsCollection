#!/usr/bin/env python3
"""
Phase 3: Extract all content files from Nibble magazine disk images.
Tasks:
  1. Read manifest
  2. Extract raw bytes + BASIC text exports
  3. Deduplicate by SHA-256 hash
  4. Build ProDOS-legal name mapping (dedup-aware)
  5. Scan for BLOAD/BRUN dependencies
  6. Patch BLOAD/BRUN references in binary files
"""

import json
import os
import re
import subprocess
import hashlib
from pathlib import Path
from collections import defaultdict

# ─── Configuration ────────────────────────────────────────────────────────────
JAVA = "/opt/homebrew/Cellar/openjdk/25.0.2/libexec/openjdk.jdk/Contents/Home/bin/java"
AC_JAR = "/tmp/claude/nibble-prodos/iteration-1/AppleCommander-ac.jar"
WORKSPACE = Path("/tmp/claude/nibble-prodos/iteration-1")
MANIFEST = WORKSPACE / "file-manifest.json"
EXTRACTED = WORKSPACE / "extracted"
EXTRACTED_TEXT = WORKSPACE / "extracted_text"
EXTRACTED_PATCHED = WORKSPACE / "extracted_patched"
DEDUP_REPORT_OUT = WORKSPACE / "dedup-report.json"
NAME_MAPPING_OUT = WORKSPACE / "name-mapping.json"
DEPENDENCY_MAP_OUT = WORKSPACE / "dependency-map.json"

# Files to exclude from extraction
EXCLUDE_NAMES = {"HELLO", "STARTUP", "INSTRUCTIONS", "README",
                 "PRODOS", "BASIC.SYSTEM"}

# BASIC file types (AppleCommander reports A for DOS3.3, BAS for ProDOS — manifest normalises to A)
BASIC_TYPES = {"A"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def disk_key(disk: dict) -> str:
    return f"{disk['year']}_PT{disk['part']}"


def safe_filename(name: str) -> str:
    """Convert a disk filename to a safe filesystem name."""
    return name.replace(" ", "_").replace("/", "_")


def run_ac(args: list) -> tuple:
    """Run AppleCommander. Returns (returncode, stdout_bytes, stderr_str)."""
    cmd = [JAVA, "-jar", AC_JAR] + args
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode, result.stdout, result.stderr.decode("utf-8", errors="replace")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ─── Task 2: File Extraction ──────────────────────────────────────────────────

def extract_files(manifest: dict) -> dict:
    """
    Extract all content files from all disks.
    Returns stats dict per disk.
    """
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    EXTRACTED_TEXT.mkdir(parents=True, exist_ok=True)
    stats = {}

    for disk in manifest["disks"]:
        key = disk_key(disk)
        disk_path = disk["full_path"]
        content_files = [f for f in disk["files"]
                         if f["name"].strip() not in EXCLUDE_NAMES]

        disk_dir = EXTRACTED / key
        text_dir = EXTRACTED_TEXT / key
        disk_dir.mkdir(parents=True, exist_ok=True)
        text_dir.mkdir(parents=True, exist_ok=True)

        ok = 0
        skipped = 0
        errors = []

        for file_info in content_files:
            orig_name = file_info["name"].strip()
            file_type = file_info["type"]
            fs_name = safe_filename(orig_name)
            raw_out = disk_dir / fs_name

            # Extract raw bytes (skip if already exists)
            if raw_out.exists() and raw_out.stat().st_size > 0:
                skipped += 1
            else:
                rc, stdout, stderr = run_ac(["-g", disk_path, orig_name])
                if rc != 0 or (len(stdout) == 0 and stderr.strip()):
                    errors.append(f"RAW {orig_name}: rc={rc} err={stderr.strip()[:100]}")
                raw_out.write_bytes(stdout)
                if rc == 0:
                    ok += 1

            # Export BASIC text (type A/BAS) — skip if exists
            if file_type in BASIC_TYPES:
                text_out = text_dir / (fs_name + ".bas")
                if not (text_out.exists() and text_out.stat().st_size > 0):
                    rc, stdout, stderr = run_ac(["-e", disk_path, orig_name])
                    if rc == 0 and stdout:
                        text_out.write_bytes(stdout)
                    else:
                        errors.append(f"TEXT {orig_name}: rc={rc} err={stderr.strip()[:100]}")

        stats[key] = {"ok": ok, "skipped": skipped, "errors": errors}
        total = ok + skipped
        print(f"  {key}: {total}/{len(content_files)} files "
              f"({ok} new, {skipped} cached, {len(errors)} errors)")
        for e in errors:
            print(f"    {e}")

    return stats


# ─── Task 3: Deduplication ────────────────────────────────────────────────────

def deduplicate(manifest: dict) -> dict:
    """
    Compute SHA-256 for every extracted file.
    Group by hash. Mark canonical (earliest year/part) vs duplicate.
    Returns dedup_info: {disk_key: {orig_name: {hash, best, duplicate_of, ...}}}
    Also returns dedup_report dict.
    """
    # Collect all (disk_key, orig_name, year, part, hash) tuples
    all_files = []
    for disk in manifest["disks"]:
        key = disk_key(disk)
        year = disk["year"]
        part = disk["part"]
        content_files = [f for f in disk["files"]
                         if f["name"].strip() not in EXCLUDE_NAMES]
        for file_info in content_files:
            orig_name = file_info["name"].strip()
            fs_name = safe_filename(orig_name)
            raw_path = EXTRACTED / key / fs_name
            if raw_path.exists() and raw_path.stat().st_size > 0:
                h = sha256(raw_path.read_bytes())
            else:
                h = None  # extraction failed
            all_files.append({
                "disk_key": key,
                "name": orig_name,
                "year": year,
                "part": part,
                "hash": h,
                "file_type": file_info["type"],
            })

    # Group by hash
    by_hash = defaultdict(list)
    for f in all_files:
        if f["hash"]:
            by_hash[f["hash"]].append(f)

    # For each hash group, sort by (year, part) to find canonical (earliest)
    dedup_sets = []
    # dedup_info: (disk_key, name) -> {best: bool, duplicate_of: str|None}
    dedup_info = {}

    for h, group in by_hash.items():
        if len(group) == 1:
            # Unique — mark as best
            f = group[0]
            dedup_info[(f["disk_key"], f["name"])] = {
                "hash": h,
                "best": True,
                "duplicate_of": None,
            }
        else:
            # Sort by (year, part) to find earliest
            group_sorted = sorted(group, key=lambda x: (x["year"], x["part"]))
            canonical = group_sorted[0]
            canonical_ref = f"{canonical['disk_key']}/{canonical['name']}"

            dedup_info[(canonical["disk_key"], canonical["name"])] = {
                "hash": h,
                "best": True,
                "duplicate_of": None,
            }

            duplicates = []
            for dup in group_sorted[1:]:
                dedup_info[(dup["disk_key"], dup["name"])] = {
                    "hash": h,
                    "best": False,
                    "duplicate_of": canonical_ref,
                }
                duplicates.append({
                    "disk_key": dup["disk_key"],
                    "name": dup["name"],
                    "year": dup["year"],
                    "suppressed": True,
                })

            dedup_sets.append({
                "hash": h,
                "canonical": {
                    "disk_key": canonical["disk_key"],
                    "name": canonical["name"],
                    "year": canonical["year"],
                    "best": True,
                },
                "duplicates": duplicates,
            })

    # Any file with hash=None (extraction failed) gets marked best=True (no comparison possible)
    for f in all_files:
        if f["hash"] is None:
            dedup_info[(f["disk_key"], f["name"])] = {
                "hash": None,
                "best": True,
                "duplicate_of": None,
                "note": "extraction_failed",
            }

    # Find same-name-different-content groups
    by_name = defaultdict(list)
    for (dk, name), info in dedup_info.items():
        by_name[name].append({"disk_key": dk, "hash": info["hash"], "best": info["best"]})

    same_name_diff_content = []
    for name, instances in by_name.items():
        hashes = {i["hash"] for i in instances if i["hash"]}
        if len(hashes) > 1:
            same_name_diff_content.append({
                "name": name,
                "instances": [
                    {
                        "disk_key": i["disk_key"],
                        "hash": i["hash"],
                        "note": "kept — unique content" if i["best"] else "kept — different content",
                    }
                    for i in instances
                ],
            })

    total_extracted = len([f for f in all_files if f["hash"] is not None])
    total_suppressed = len([v for v in dedup_info.values() if not v["best"]])
    unique_programs = total_extracted - total_suppressed

    dedup_report = {
        "total_extracted": total_extracted,
        "unique_programs": unique_programs,
        "duplicate_sets": dedup_sets,
        "same_name_different_content": same_name_diff_content,
    }

    return dedup_info, dedup_report


# ─── Task 4: ProDOS Name Normalization ────────────────────────────────────────

def normalize_to_prodos(name: str) -> str:
    """Normalize a DOS 3.3 filename to ProDOS-legal name (max 15, [A-Z0-9.], first=letter)."""
    name = name.strip().upper()
    name = name.replace(" ", ".").replace("-", ".")
    # Remove illegal chars
    name = re.sub(r"[^A-Z0-9.]", "", name)
    # Ensure first char is letter
    if name and not name[0].isalpha():
        name = "X" + name
    # Truncate to 15 chars, try at word boundary
    if len(name) > 15:
        truncated = name[:15]
        last_dot = truncated.rfind(".")
        if last_dot > 0:
            truncated = truncated[:last_dot]
        name = truncated
    return name if name else "UNKNOWN"


def build_name_mapping(manifest: dict, dedup_info: dict) -> dict:
    """
    Build per-disk mapping: original_name -> {prodos_name, best, duplicate_of}.
    ProDOS name collision resolution within each disk (across all files, not just canonical).
    The 'best' and 'duplicate_of' fields come from dedup_info.
    """
    mapping = {}

    for disk in manifest["disks"]:
        key = disk_key(disk)
        content_files = [f for f in disk["files"]
                         if f["name"].strip() not in EXCLUDE_NAMES]

        assigned_prodos = set()
        disk_map = {}

        for file_info in content_files:
            orig_name = file_info["name"].strip()
            prodos = normalize_to_prodos(orig_name)

            # Resolve collision within this disk
            if prodos not in assigned_prodos:
                assigned_prodos.add(prodos)
                final_prodos = prodos
            else:
                suffix = 2
                while True:
                    suffix_str = f".{suffix}"
                    max_base = 15 - len(suffix_str)
                    base = prodos[:max_base]
                    if len(base) < len(prodos) and base and base[-1] != ".":
                        last_dot = base.rfind(".")
                        if last_dot > 0:
                            base = base[:last_dot]
                    candidate = base + suffix_str
                    if candidate not in assigned_prodos:
                        break
                    suffix += 1
                assigned_prodos.add(candidate)
                final_prodos = candidate

            info = dedup_info.get((key, orig_name), {"best": True, "duplicate_of": None})
            entry = {
                "prodos_name": final_prodos,
                "best": info["best"],
            }
            if info.get("duplicate_of"):
                entry["duplicate_of"] = info["duplicate_of"]

            disk_map[orig_name] = entry

        mapping[key] = disk_map

    return mapping


# ─── Task 5: BLOAD/BRUN Dependency Scan ───────────────────────────────────────

def extract_bload_brun_refs(text: str) -> list:
    """
    Scan decompiled BASIC text for BLOAD/BRUN/CHAIN references.
    Returns list of (statement_type, referenced_file).
    Skips REM lines.
    Excludes ProDOS device paths (starting with /).
    Handles variable-appended RAM device paths (no closing quote = not a static name).

    Observed formats from AppleCommander -e output:
      PRINT D$"BLOADDRAGON 7.PIC,A$4000"   <- no space, comma-addr-terminated
      PRINT CHR$(4)"BLOADLIFE 2"            <- no space, quote-terminated
      PRINT CHR$(4)"BRUN KEYBOARD BUFFER"   <- space, quote-terminated
      PRINT CHR$(4);"BLOAD YES NO"          <- semicolon + space, quote-terminated
      PRINT CHR$(4)"BLOADVIDEO"             <- no space, quote-terminated
      PRINT CHR$(4)"BSAVE/RAM/P"M"..."      <- device path + variable: EXCLUDED
                                              (no closing " after name — " is before variable)
    """
    # Two-stage approach:
    # Stage 1: find quoted strings "BLOAD..." or "BRUN..." within CHR$(4) context
    # Stage 2: extract filename from the matched content
    LINE_CTX = re.compile(
        r'(?:D\$|CHR\$\s*\(\s*4\s*\))\s*;?\s*"(B(?:LOAD|RUN)[^"\r\n]*?)"',
        re.IGNORECASE
    )
    NAME_RE = re.compile(r'^B(LOAD|RUN)\s*([^,]+?)(?:,|$)', re.IGNORECASE)

    results = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip pure REM lines
        if re.match(r'^\d+\s+REM\b', stripped, re.IGNORECASE):
            continue

        for ctx_m in LINE_CTX.finditer(stripped):
            content = ctx_m.group(1)  # e.g. "BLOADDRAGON 7.PIC,A$4000"
            name_m = NAME_RE.match(content)
            if name_m:
                verb = name_m.group(1).upper()
                fname = name_m.group(2).strip()
                # Exclude ProDOS device paths (/RAM/, /DISK/, etc.)
                if fname and not fname.startswith("/"):
                    results.append(("B" + verb, fname))

        # CHAIN "filename" (static string)
        for match in re.finditer(r'\bCHAIN\s+"([^"]+)"', stripped, re.IGNORECASE):
            results.append(("CHAIN", match.group(1).strip()))

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for item in results:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def build_dependency_map(manifest: dict, name_mapping: dict, dedup_info: dict) -> list:
    """
    Scan all exported BASIC text files for BLOAD/BRUN/CHAIN dependencies.
    Only scan canonical (best=True) files.
    """
    deps = []

    for disk in manifest["disks"]:
        key = disk_key(disk)
        disk_map = name_mapping.get(key, {})
        text_dir = EXTRACTED_TEXT / key

        content_files = [f for f in disk["files"]
                         if f["name"].strip() not in EXCLUDE_NAMES
                         and f["type"] in BASIC_TYPES]

        for file_info in content_files:
            orig_name = file_info["name"].strip()

            # Only scan canonical files
            info = dedup_info.get((key, orig_name), {"best": True})
            if not info.get("best", True):
                continue

            fs_name = safe_filename(orig_name)
            text_file = text_dir / (fs_name + ".bas")
            if not text_file.exists():
                continue

            text = text_file.read_text(encoding="utf-8", errors="replace")
            refs = extract_bload_brun_refs(text)

            for stmt_type, ref_file in refs:
                ref_file_stripped = ref_file.strip()
                # Look up ProDOS name for the referenced file
                ref_entry = disk_map.get(ref_file_stripped)
                if ref_entry:
                    ref_prodos = ref_entry["prodos_name"]
                else:
                    ref_prodos = normalize_to_prodos(ref_file_stripped)
                needs_patch = (ref_file_stripped != ref_prodos)
                deps.append({
                    "disk_key": key,
                    "program": orig_name,
                    "statement_type": stmt_type,
                    "referenced_file": ref_file_stripped,
                    "referenced_file_prodos": ref_prodos,
                    "needs_patch": needs_patch,
                    "patch_status": "PENDING" if needs_patch else "NOT_NEEDED",
                })

    return deps


# ─── Task 6: Binary Patching ──────────────────────────────────────────────────

def patch_basic_binary(raw_bytes: bytes, old_name: str, new_name: str) -> tuple:
    """
    Patch Applesoft BASIC binary: replace old_name ASCII bytes with new_name.
    Returns (patched_bytes, status).
    """
    old_bytes = old_name.encode("ascii", errors="replace")
    new_bytes = new_name.encode("ascii", errors="replace")

    if len(new_bytes) > len(old_bytes):
        return raw_bytes, "SKIPPED_NAME_TOO_LONG"

    if old_bytes not in raw_bytes:
        return raw_bytes, "SKIPPED_NOT_FOUND"

    # Pad new with trailing spaces to match old length
    padded_new = new_bytes + b" " * (len(old_bytes) - len(new_bytes))
    count = raw_bytes.count(old_bytes)
    patched = raw_bytes.replace(old_bytes, padded_new)
    return patched, f"OK_PATCHED_{count}"


def apply_patches(manifest: dict, name_mapping: dict, dependency_map: list) -> list:
    """Apply patches to all files needing them. Updates dependency_map in place."""
    EXTRACTED_PATCHED.mkdir(parents=True, exist_ok=True)

    # Group deps by (disk_key, program)
    by_program = defaultdict(list)
    for i, dep in enumerate(dependency_map):
        if dep["needs_patch"]:
            by_program[(dep["disk_key"], dep["program"])].append(i)

    for (dkey, program), dep_indices in by_program.items():
        fs_name = safe_filename(program)
        raw_path = EXTRACTED / dkey / fs_name
        patch_dir = EXTRACTED_PATCHED / dkey
        patch_dir.mkdir(parents=True, exist_ok=True)
        patch_path = patch_dir / fs_name

        if not raw_path.exists():
            for i in dep_indices:
                dependency_map[i]["patch_status"] = "SKIPPED_SOURCE_NOT_FOUND"
            continue

        data = raw_path.read_bytes()

        for i in dep_indices:
            dep = dependency_map[i]
            data, status = patch_basic_binary(data, dep["referenced_file"],
                                              dep["referenced_file_prodos"])
            dependency_map[i]["patch_status"] = status
            if not status.startswith("OK"):
                print(f"    PATCH {dkey}/{program} -> '{dep['referenced_file']}': {status}")

        patch_path.write_bytes(data)

        # Verify each patch
        for i in dep_indices:
            dep = dependency_map[i]
            if dep["patch_status"].startswith("OK"):
                old_b = dep["referenced_file"].encode("ascii", errors="replace")
                new_b = dep["referenced_file_prodos"].encode("ascii", errors="replace")
                if old_b in data and old_b != new_b:
                    dependency_map[i]["patch_status"] = "VERIFY_FAIL_OLD_PRESENT"
                    print(f"    VERIFY FAIL {dkey}/{program}: old '{dep['referenced_file']}' still present")
                elif new_b not in data:
                    dependency_map[i]["patch_status"] = "VERIFY_FAIL_NEW_ABSENT"
                    print(f"    VERIFY FAIL {dkey}/{program}: new '{dep['referenced_file_prodos']}' not found")
                else:
                    dependency_map[i]["patch_status"] = "VERIFIED_OK"

    return dependency_map


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=== Phase 3: Nibble Disk Extraction ===\n")

    with open(MANIFEST) as f:
        manifest = json.load(f)
    print(f"Manifest: {len(manifest['disks'])} disks\n")

    # Task 2: Extract files
    print("[Task 2] Extracting files...")
    stats = extract_files(manifest)
    total_ok = sum(s["ok"] for s in stats.values())
    total_skipped = sum(s["skipped"] for s in stats.values())
    total_errors = sum(len(s["errors"]) for s in stats.values())
    print(f"\n  Done: {total_ok} newly extracted, {total_skipped} cached, {total_errors} errors\n")

    # Task 3: Deduplicate
    print("[Task 3] Deduplicating by SHA-256...")
    dedup_info, dedup_report = deduplicate(manifest)
    print(f"  Total extracted: {dedup_report['total_extracted']}")
    print(f"  Unique programs: {dedup_report['unique_programs']}")
    print(f"  Duplicate sets: {len(dedup_report['duplicate_sets'])}")
    print(f"  Same-name-different-content groups: {len(dedup_report['same_name_different_content'])}")

    with open(DEDUP_REPORT_OUT, "w") as f:
        json.dump(dedup_report, f, indent=2)
    print(f"  Written: {DEDUP_REPORT_OUT}\n")

    # Task 4: Build name mapping
    print("[Task 4] Building ProDOS name mapping...")
    name_mapping = build_name_mapping(manifest, dedup_info)

    collision_count = 0
    for key, disk_map in name_mapping.items():
        prodos_names = [v["prodos_name"] for v in disk_map.values()]
        if len(prodos_names) != len(set(prodos_names)):
            from collections import Counter
            dupes = {k: v for k, v in Counter(prodos_names).items() if v > 1}
            print(f"  WARNING: remaining collisions in {key}: {dupes}")
            collision_count += len(dupes)

    total_names = sum(len(v) for v in name_mapping.values())
    if collision_count == 0:
        print(f"  {total_names} names mapped, zero collisions")
    else:
        print(f"  {total_names} names mapped, {collision_count} unresolved collision groups")

    with open(NAME_MAPPING_OUT, "w") as f:
        json.dump(name_mapping, f, indent=2)
    print(f"  Written: {NAME_MAPPING_OUT}\n")

    # Task 5: Scan dependencies
    print("[Task 5] Scanning BLOAD/BRUN dependencies...")
    dependency_map = build_dependency_map(manifest, name_mapping, dedup_info)
    needs_patch = [d for d in dependency_map if d["needs_patch"]]
    no_patch = [d for d in dependency_map if not d["needs_patch"]]
    print(f"  {len(dependency_map)} references found: {len(needs_patch)} need patch, {len(no_patch)} ok")
    for d in dependency_map:
        flag = " [NEEDS PATCH]" if d["needs_patch"] else ""
        print(f"    {d['disk_key']}/{d['program']}: {d['statement_type']} \"{d['referenced_file']}\""
              f" -> \"{d['referenced_file_prodos']}\"{flag}")

    # Task 6: Patch
    if needs_patch:
        print(f"\n[Task 6] Patching {len(needs_patch)} references...")
        dependency_map = apply_patches(manifest, name_mapping, dependency_map)
        verified = [d for d in dependency_map if d.get("patch_status") == "VERIFIED_OK"]
        failed = [d for d in dependency_map if "FAIL" in d.get("patch_status", "")
                  or d.get("patch_status", "").startswith("SKIPPED")]
        print(f"  {len(verified)} verified OK, {len(failed)} failed/skipped")
    else:
        print("\n[Task 6] No patches needed.")

    with open(DEPENDENCY_MAP_OUT, "w") as f:
        json.dump(dependency_map, f, indent=2)
    print(f"  Written: {DEPENDENCY_MAP_OUT}\n")

    # Final counts
    total_files_extracted = sum(
        len(list((EXTRACTED / disk_key(d)).iterdir()))
        for d in manifest["disks"]
        if (EXTRACTED / disk_key(d)).exists()
    )
    patched_files = list(EXTRACTED_PATCHED.rglob("*")) if EXTRACTED_PATCHED.exists() else []
    patched_count = len([p for p in patched_files if p.is_file()])

    print("=== Final Summary ===")
    print(f"  Disks processed:       {len(manifest['disks'])}")
    print(f"  Files in extracted/:   {total_files_extracted}")
    print(f"  Unique programs:       {dedup_report['unique_programs']}")
    print(f"  Duplicate sets:        {len(dedup_report['duplicate_sets'])}")
    print(f"  BLOAD/BRUN deps:       {len(dependency_map)}")
    print(f"  Patched files:         {patched_count}")


if __name__ == "__main__":
    main()
