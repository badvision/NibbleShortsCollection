#!/usr/bin/env python3
"""
enhance_topics.py — Phase 4b: Add graphics_mode detection to topic-assignments.json

For BASIC programs (type A): scan extracted_text/ for GR/HGR Applesoft statements.
For binary programs (type B): scan extracted/ for known Apple II graphics softswitches.
.PIC files (type B, size 8184): always HI.RES (standard HGR picture data).

Replaces GRAPHICS primary_topic with HI.RES or LO.RES.
Splits GRAPHICS in topic-labels.json into HI.RES and LO.RES.
Writes graphics-detection-report.txt.
"""

import json
import os
import re
from collections import defaultdict

BASE = "/tmp/claude/nibble-prodos/iteration-1"

# ---------------------------------------------------------------------------
# BASIC graphics signal patterns
# ---------------------------------------------------------------------------

# Lo-res signals — matched as Applesoft statements (not inside strings/REMs)
LORES_PATTERNS = [
    # GR as a statement: after line number, colon, or at start of token run
    # Negative lookahead ensures GR is not part of longer word (e.g. PRINT, GRAPHICS)
    re.compile(r'(?:^|:)\s*GR\b(?!\s*[A-Z0-9$%])'),      # GR statement
    re.compile(r'\bCOLOR\s*='),                              # COLOR= (lo-res color)
    re.compile(r'(?<!\bH)(?<!\bS)(?<!\bHP)\bPLOT\b'),      # PLOT but not HPLOT
    re.compile(r'\bSCRN\s*\('),                              # SCRN( — read lo-res pixel
    re.compile(r'\bHLIN\b'),                                 # HLIN — lo-res horizontal line
    re.compile(r'\bVLIN\b'),                                 # VLIN — lo-res vertical line
]

# Hi-res signals
HIRES_PATTERNS = [
    re.compile(r'\bHGR2?\b'),                               # HGR or HGR2
    re.compile(r'\bHPLOT\b'),                               # HPLOT
    re.compile(r'\bHCOLOR\s*='),                            # HCOLOR=
    re.compile(r'\bDRAW\b'),                                 # DRAW (shape table)
    re.compile(r'\bXDRAW\b'),                                # XDRAW (shape table)
]

# Separate HPLOT counter to avoid double-counting with PLOT detection
HPLOT_PAT = re.compile(r'\bHPLOT\b')
PLOT_STANDALONE_PAT = re.compile(r'(?<![A-Z])PLOT\b')


def strip_basic_strings_and_remarks(source: str) -> str:
    """
    Return source with string literals and REM content replaced by spaces,
    so we can safely scan for statement keywords without false positives.
    """
    result = []
    i = 0
    length = len(source)
    while i < length:
        ch = source[i]
        if ch == '"':
            # Skip to closing quote or end of line
            result.append(' ')
            i += 1
            while i < length and source[i] not in ('"', '\n'):
                result.append(' ')
                i += 1
            if i < length and source[i] == '"':
                result.append(' ')
                i += 1
        elif source[i:i+3] == 'REM':
            # REM to end of logical line (semicolon doesn't continue, newline does)
            result.append('   ')
            i += 3
            while i < length and source[i] != '\n':
                result.append(' ')
                i += 1
        else:
            result.append(ch)
            i += 1
    return ''.join(result)


def count_basic_graphics(source: str) -> tuple[int, int]:
    """
    Returns (lores_count, hires_count) for BASIC source text.
    Strips strings and REMs before scanning.
    """
    clean = strip_basic_strings_and_remarks(source)

    lores = 0
    for pat in LORES_PATTERNS:
        matches = pat.findall(clean)
        lores += len(matches)

    # Count HPLOT separately first, then PLOT-not-HPLOT
    hplot_count = len(HPLOT_PAT.findall(clean))
    plot_all = len(PLOT_STANDALONE_PAT.findall(clean))
    # standalone PLOT = all PLOT minus those that are actually HPLOT
    standalone_plot = max(0, plot_all - hplot_count)
    lores += standalone_plot

    hires = 0
    for pat in HIRES_PATTERNS:
        hires += len(pat.findall(clean))
    # HPLOT is in HIRES_PATTERNS via \bHPLOT\b, but also add it explicitly
    # (it's already included via HIRES_PATTERNS[1])

    return lores, hires


# ---------------------------------------------------------------------------
# Binary graphics signal patterns (softswitch bytes, little-endian)
# ---------------------------------------------------------------------------

# Hi-res specific softswitches / ROM entry points
HIRES_BINARY_PATTERNS = [
    b'\x57\xC0',  # C057 — HIRES (set hi-res mode)
    b'\x54\xC0',  # C054 — PAGE1
    b'\x55\xC0',  # C055 — PAGE2
    b'\x57\xF4',  # F457 — HPLOT ROM routine
    b'\x3A\xF5',  # F53A — DRAW ROM routine
    b'\xE2\xF3',  # F3E2 — HPOSN ROM routine
]

# Lo-res specific softswitches / ROM entry points
LORES_BINARY_PATTERNS = [
    b'\x56\xC0',  # C056 — LORES (set lo-res mode)
    b'\x53\xC0',  # C053 — MIXSET/MIXCLR
    b'\x19\xF8',  # F819 — HLINE ROM routine
    b'\x28\xF8',  # F828 — VLINE ROM routine
    b'\x71\xF8',  # F871 — CLRSCR ROM routine
]
# Note: C050 (TXTCLR) b'\x50\xC0' and F800 (PLOT) b'\x00\xF8' are excluded
# because they appear too frequently as false positives in non-code data
# (F800 appears in Applesoft line link pointers; C050 is also used in text mode)

HGR_PAGE_SIZE = 8184  # Standard Apple II hi-res page is 8184 bytes
_PIC_PATTERN = re.compile(r'\.PIC\d*$', re.IGNORECASE)


def classify_binary(data: bytes, name: str) -> tuple[int, int]:
    """
    Returns (lores_count, hires_count) signal counts for binary data.
    .PIC files of standard HGR size are auto-classified as hi-res.
    Handles .PIC, .PIC1, .PIC2, etc. naming conventions.
    """
    # Standard HGR picture file (8192 bytes raw, but extracted as 8184)
    if _PIC_PATTERN.search(name) and len(data) == HGR_PAGE_SIZE:
        return 0, 1

    hires = sum(data.count(pat) for pat in HIRES_BINARY_PATTERNS)
    lores = sum(data.count(pat) for pat in LORES_BINARY_PATTERNS)
    return lores, hires


# ---------------------------------------------------------------------------
# Determine graphics_mode from counts
# ---------------------------------------------------------------------------

def determine_mode(lores: int, hires: int) -> str:
    """Convert signal counts to a graphics_mode string."""
    if hires > 0 and lores > 0:
        return "BOTH"
    if hires > 0:
        return "HI.RES"
    if lores > 0:
        return "LO.RES"
    return "TEXT.MODE"


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def main():
    # Load data
    with open(os.path.join(BASE, "topic-assignments.json")) as f:
        assignments = json.load(f)

    with open(os.path.join(BASE, "topic-labels.json")) as f:
        labels = json.load(f)

    with open(os.path.join(BASE, "file-manifest.json")) as f:
        manifest = json.load(f)

    # Build file-type lookup: (disk_key, original_name) -> type
    file_types = {}
    for disk in manifest["disks"]:
        disk_key = f"{disk['year']}_PT{disk['part']}"
        for finfo in disk.get("files", []):
            file_types[(disk_key, finfo["name"])] = finfo.get("type", "?")

    extracted_text_base = os.path.join(BASE, "extracted_text")
    extracted_base = os.path.join(BASE, "extracted")

    # Detection tracking
    detection_stats = {
        "HI.RES":   {"basic": 0, "binary": 0},
        "LO.RES":   {"basic": 0, "binary": 0},
        "BOTH":     {"basic": 0, "binary": 0},
        "TEXT.MODE": {"basic": 0, "binary": 0},
        "UNKNOWN":  {"basic": 0, "binary": 0},
    }
    both_mode_programs = []  # Interesting: programs using both modes

    # Programs where GRAPHICS topic gets resolved
    graphics_resolved = defaultdict(int)  # mode -> count

    # Per-entry processing
    for entry in assignments:
        disk_key = entry["disk_key"]
        original_name = entry["original_name"]
        fname_base = original_name.replace(" ", "_")

        file_type = file_types.get((disk_key, original_name), "?")

        graphics_mode = "UNKNOWN"
        detection_method = "unknown"

        if file_type == "A":
            # BASIC source — scan extracted_text/
            bas_path = os.path.join(extracted_text_base, disk_key, fname_base + ".bas")
            if os.path.exists(bas_path):
                with open(bas_path, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
                lores, hires = count_basic_graphics(source)
                graphics_mode = determine_mode(lores, hires)
                detection_method = "basic"
            else:
                graphics_mode = "UNKNOWN"
                detection_method = "basic"

        elif file_type == "B":
            # Binary / machine code — scan extracted/ raw bytes
            bin_path = os.path.join(extracted_base, disk_key, fname_base)
            if os.path.exists(bin_path):
                with open(bin_path, "rb") as f:
                    data = f.read()
                lores, hires = classify_binary(data, original_name)
                graphics_mode = determine_mode(lores, hires)
                detection_method = "binary"
            else:
                graphics_mode = "UNKNOWN"
                detection_method = "binary"

        else:
            # Type T, S, or other — no graphics detection
            graphics_mode = "TEXT.MODE"
            detection_method = "type_other"

        # Record stats
        entry["graphics_mode"] = graphics_mode
        if detection_method in ("basic", "binary"):
            detection_stats[graphics_mode][detection_method] += 1
        else:
            detection_stats["TEXT.MODE"]["basic"] += 1  # lump type T/S into TEXT.MODE

        if graphics_mode == "BOTH":
            both_mode_programs.append(
                f"{disk_key}/{original_name} (type={file_type}, method={detection_method})"
            )

        # Resolve GRAPHICS primary_topic first (in-place rename in all_topics)
        if entry["primary_topic"] == "GRAPHICS":
            if graphics_mode == "HI.RES":
                new_topic = "HI.RES"
            elif graphics_mode == "LO.RES":
                new_topic = "LO.RES"
            elif graphics_mode == "BOTH":
                new_topic = "HI.RES"  # Primary = dominant; BOTH -> HI.RES wins
            else:
                new_topic = "GRAPHICS"  # Keep as-is if UNKNOWN/TEXT.MODE

            if new_topic != "GRAPHICS":
                graphics_resolved[new_topic] += 1
                entry["primary_topic"] = new_topic
                # Replace GRAPHICS in all_topics with resolved topic
                entry["all_topics"] = [
                    new_topic if t == "GRAPHICS" else t
                    for t in entry["all_topics"]
                ]
                # Add LO.RES as secondary if BOTH
                if graphics_mode == "BOTH" and "LO.RES" not in entry["all_topics"]:
                    entry["all_topics"].append("LO.RES")

        # Update all_topics: add HI.RES or LO.RES if not already present
        if graphics_mode in ("HI.RES", "LO.RES"):
            if graphics_mode not in entry["all_topics"]:
                entry["all_topics"].append(graphics_mode)
            if entry.get("secondary_topic") is None and entry["primary_topic"] != graphics_mode:
                entry["secondary_topic"] = graphics_mode
        elif graphics_mode == "BOTH":
            for mode in ("HI.RES", "LO.RES"):
                if mode not in entry["all_topics"]:
                    entry["all_topics"].append(mode)

        # Deduplicate all_topics while preserving order
        seen = set()
        entry["all_topics"] = [
            t for t in entry["all_topics"]
            if not (t in seen or seen.add(t))
        ]

    # ---------------------------------------------------------------------------
    # Write updated topic-assignments.json
    # ---------------------------------------------------------------------------
    with open(os.path.join(BASE, "topic-assignments.json"), "w") as f:
        json.dump(assignments, f, indent=2)
    print(f"Wrote topic-assignments.json ({len(assignments)} entries)")

    # ---------------------------------------------------------------------------
    # Update topic-labels.json — split GRAPHICS into HI.RES and LO.RES
    # ---------------------------------------------------------------------------
    # Count per-topic
    topic_counts = defaultdict(int)
    topic_reps = defaultdict(list)
    for entry in assignments:
        t = entry["primary_topic"]
        topic_counts[t] += 1
        if len(topic_reps[t]) < 5:
            topic_reps[t].append(entry["original_name"])

    # Build a canonical topic list from topic_counts, ensuring all used topics have entries.
    # Start from existing labels to preserve descriptions, then add/update as needed.
    existing_by_name = {t["name"]: t for t in labels["topics"]}

    # Determine the desired set of topics after this pass
    # GRAPHICS is replaced by HI.RES and LO.RES; residual GRAPHICS kept if programs remain
    desired_topics_order = []
    for topic in labels["topics"]:
        name = topic["name"]
        if name == "GRAPHICS":
            # Replace with HI.RES and LO.RES
            for new_name, new_desc in [
                ("HI.RES", "Hi-res graphics programs (HGR/HPLOT/HCOLOR)"),
                ("LO.RES", "Lo-res graphics programs (GR/PLOT/HLIN/VLIN/COLOR=)"),
            ]:
                if new_name not in [t["name"] for t in desired_topics_order]:
                    desired_topics_order.append({
                        "id": topic["id"],
                        "name": new_name,
                        "description": existing_by_name.get(new_name, {}).get(
                            "description", new_desc
                        ),
                        "representative_programs": topic_reps[new_name][:5],
                        "program_count": topic_counts[new_name],
                    })
            # Residual GRAPHICS for text-mode visual programs
            if topic_counts.get("GRAPHICS", 0) > 0:
                desired_topics_order.append({
                    "id": topic["id"],
                    "name": "GRAPHICS",
                    "description": "Text-mode visual programs and display effects",
                    "representative_programs": topic_reps["GRAPHICS"][:5],
                    "program_count": topic_counts["GRAPHICS"],
                })
        else:
            # Update count; keep existing description and representative_programs
            topic["program_count"] = topic_counts.get(name, topic["program_count"])
            if topic_counts.get(name, 0) > 0:
                desired_topics_order.append(topic)

    # Ensure HI.RES and LO.RES are present even if they weren't in original labels
    # (idempotent re-run: GRAPHICS already gone, but HI.RES/LO.RES already added)
    present_names = {t["name"] for t in desired_topics_order}
    for new_name, new_desc in [
        ("HI.RES", "Hi-res graphics programs (HGR/HPLOT/HCOLOR)"),
        ("LO.RES", "Lo-res graphics programs (GR/PLOT/HLIN/VLIN/COLOR=)"),
    ]:
        if new_name not in present_names and topic_counts.get(new_name, 0) > 0:
            desired_topics_order.append({
                "id": 6,
                "name": new_name,
                "description": existing_by_name.get(new_name, {}).get("description", new_desc),
                "representative_programs": topic_reps[new_name][:5],
                "program_count": topic_counts[new_name],
            })
    # Residual GRAPHICS: ensure it's present if programs exist but label is missing
    if "GRAPHICS" not in present_names and topic_counts.get("GRAPHICS", 0) > 0:
        desired_topics_order.append({
            "id": 6,
            "name": "GRAPHICS",
            "description": "Text-mode visual programs and display effects",
            "representative_programs": topic_reps["GRAPHICS"][:5],
            "program_count": topic_counts["GRAPHICS"],
        })

    labels["topics"] = desired_topics_order

    with open(os.path.join(BASE, "topic-labels.json"), "w") as f:
        json.dump(labels, f, indent=2)
    print("Wrote topic-labels.json")

    # ---------------------------------------------------------------------------
    # Verify: no primary_topic == GRAPHICS remaining
    # ---------------------------------------------------------------------------
    remaining_graphics = [e for e in assignments if e["primary_topic"] == "GRAPHICS"]
    print(f"Remaining GRAPHICS entries: {len(remaining_graphics)}")
    if remaining_graphics:
        print("  (these have UNKNOWN/TEXT.MODE graphics_mode — kept as GRAPHICS)")
        for e in remaining_graphics[:5]:
            print(f"    {e['disk_key']}/{e['original_name']}: mode={e['graphics_mode']}")

    # ---------------------------------------------------------------------------
    # Topic distribution check (ensure no single topic > 45%)
    # ---------------------------------------------------------------------------
    topic_dist = defaultdict(int)
    for entry in assignments:
        topic_dist[entry["primary_topic"]] += 1
    total = len(assignments)
    print("\nFinal topic distribution:")
    for t, c in sorted(topic_dist.items(), key=lambda x: -x[1]):
        pct = 100 * c / total
        flag = " *** EXCEEDS 45%" if pct > 45 else ""
        print(f"  {t:12s}: {c:3d} ({pct:.1f}%){flag}")

    # ---------------------------------------------------------------------------
    # Write graphics-detection-report.txt
    # ---------------------------------------------------------------------------
    report_lines = []
    report_lines.append("Apple II Nibble One-Liners — Graphics Mode Detection Report")
    report_lines.append("=" * 60)
    report_lines.append("")

    # Overall counts
    mode_totals = {
        "HI.RES": 0, "LO.RES": 0, "BOTH": 0, "TEXT.MODE": 0, "UNKNOWN": 0
    }
    for entry in assignments:
        m = entry["graphics_mode"]
        if m in mode_totals:
            mode_totals[m] += 1

    report_lines.append("Overall graphics mode counts:")
    for mode, count in mode_totals.items():
        report_lines.append(f"  {mode:12s}: {count:4d}")
    report_lines.append(f"  {'TOTAL':12s}: {sum(mode_totals.values()):4d}")
    report_lines.append("")

    # By detection method
    report_lines.append("Counts by detection method (BASIC scan vs binary scan):")
    for mode, methods in detection_stats.items():
        total_m = methods["basic"] + methods["binary"]
        if total_m > 0:
            report_lines.append(
                f"  {mode:12s}: BASIC={methods['basic']:3d}  binary={methods['binary']:3d}  total={total_m:3d}"
            )
    report_lines.append("")

    # Programs using both modes (interesting finding)
    if both_mode_programs:
        report_lines.append(f"Programs using BOTH hi-res and lo-res signals ({len(both_mode_programs)}):")
        for p in both_mode_programs:
            report_lines.append(f"  {p}")
        report_lines.append("")

    # GRAPHICS topic resolution (from this run)
    report_lines.append("GRAPHICS topic resolution (this run):")
    if graphics_resolved:
        for new_topic, count in sorted(graphics_resolved.items()):
            report_lines.append(f"  GRAPHICS -> {new_topic}: {count}")
    else:
        report_lines.append("  (no resolutions in this run — data already processed)")
    report_lines.append(
        f"  Total primary_topic=HI.RES: {topic_dist.get('HI.RES', 0)}"
    )
    report_lines.append(
        f"  Total primary_topic=LO.RES: {topic_dist.get('LO.RES', 0)}"
    )
    if remaining_graphics:
        report_lines.append(
            f"  GRAPHICS kept (text-mode visual programs): {len(remaining_graphics)}"
        )
    report_lines.append("")

    # Final topic distribution
    report_lines.append("Final topic distribution (primary_topic):")
    for t, c in sorted(topic_dist.items(), key=lambda x: -x[1]):
        pct = 100 * c / total
        flag = " [EXCEEDS 45%]" if pct > 45 else ""
        report_lines.append(f"  {t:12s}: {c:3d} ({pct:.1f}%){flag}")
    report_lines.append("")

    # Notable findings
    report_lines.append("Notable findings:")
    # Programs tagged as DOCS that have graphics
    docs_with_graphics = [
        e for e in assignments
        if e["primary_topic"] == "DOCS" and e["graphics_mode"] in ("HI.RES", "LO.RES", "BOTH")
    ]
    report_lines.append(f"  DOCS programs with graphics signals: {len(docs_with_graphics)}")
    report_lines.append(
        "  (DOCS primary_topic preserved per spec — they are instruction files)"
    )
    # Distribution of graphics_mode among non-DOCS entries
    non_docs = [e for e in assignments if e["primary_topic"] != "DOCS"]
    non_docs_hires = sum(1 for e in non_docs if e["graphics_mode"] in ("HI.RES", "BOTH"))
    non_docs_lores = sum(1 for e in non_docs if e["graphics_mode"] in ("LO.RES", "BOTH"))
    report_lines.append(f"  Non-DOCS programs with HI.RES signals: {non_docs_hires}")
    report_lines.append(f"  Non-DOCS programs with LO.RES signals: {non_docs_lores}")
    report_lines.append("")

    # PIC file count
    pic_entries = [
        e for e in assignments
        if e["original_name"].upper().endswith(".PIC")
        and file_types.get((e["disk_key"], e["original_name"])) == "B"
    ]
    report_lines.append(f"Standard HGR picture files (.PIC, 8184 bytes): {len(pic_entries)}")
    report_lines.append("  (auto-classified as HI.RES — raw HGR page data)")

    report_text = "\n".join(report_lines) + "\n"
    report_path = os.path.join(BASE, "graphics-detection-report.txt")
    with open(report_path, "w") as f:
        f.write(report_text)
    print(f"\nWrote {report_path}")


if __name__ == "__main__":
    main()
