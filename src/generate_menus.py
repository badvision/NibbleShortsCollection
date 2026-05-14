#!/usr/bin/env python3
"""
generate_menus.py -- Generate ProDOS file I/O based menu system for the
Nibble One & Two Liners disk image.

Produces:
  STARTUP.bas   -- 1-liner boot chain (unchanged)
  MENU.bas      -- main selector (static, unchanged)
  BY.NAME       -- fixed-record text data file, records x 56 bytes
  BY.YEAR       -- fixed-record text data file, sorted by year then name
  BY.TOPIC      -- fixed-record text data file, sorted by topic then name
  BY.YEAR.bas   -- compact ~100-line BASIC shell (reads BY.YEAR data file)
  BY.NAME.bas   -- compact ~100-line BASIC shell (reads BY.NAME data file)
  BY.TOPIC.bas  -- compact ~100-line BASIC shell (reads BY.TOPIC data file)
  {PRODOS_NAME}.T -- instruction text files (one per program with instructions)

Record format (L=56, fixed-length, Apple II CR-terminated):
  YEAR,PRODOS_NAME,DISPLAY_NAME,FLAGS,{padding}\r
  Exactly 56 bytes: 55 chars + CR ($0D)
  Max field lengths: 4+1+15+1+30+1+2 = 54 chars + 1 padding + CR = 56
  BASIC derives filenames:
    Instruction text: LEFT$(PN$(SN), 13) + ".T"
    Picture:          LEFT$(PN$(SN), 11) + ".PIC"

FLAGS encoding:
  0  = BASIC, no instructions
  1  = BASIC, has instructions
  2  = binary (BRUN), no instructions
  3  = binary (BRUN), has instructions
  4  = standalone picture file (no parent program)
  8  = BASIC + has linked picture
  9  = BASIC + instructions + has linked picture
  10 = binary + has linked picture
  11 = binary + instructions + has linked picture
"""

import json
import os
import re
import sys
import textwrap
from pathlib import Path
from collections import defaultdict

# Repo root: parent of the src/ directory containing this script
REPO_ROOT = Path(__file__).parent.parent
WORKSPACE = str(REPO_ROOT)
DATA_DIR = REPO_ROOT / 'data'
DIST_DIR = REPO_ROOT / 'dist'
DIST_DIR.mkdir(exist_ok=True)

RECORD_LEN = 56    # 55 data chars + CR
PAGE_SIZE = 19     # entries per page

# Data file names on ProDOS (must not conflict with BASIC program names BY.YEAR, BY.NAME, BY.TOPIC)
DATA_FILE_NAME = 'NAME.DATA'
DATA_FILE_YEAR = 'YEAR.DATA'
DATA_FILE_TOPIC = 'TOPIC.DATA'

# ---------------------------------------------------------------------------
# Load raw data
# ---------------------------------------------------------------------------

with open(DATA_DIR / 'topic-assignments.json') as f:
    raw = json.load(f)

with open(DATA_DIR / 'file-manifest.json') as f:
    fm = json.load(f)

# ---------------------------------------------------------------------------
# Build file-type lookup: (disk_key, original_name) -> ("A"/"B", size_bytes)
# ---------------------------------------------------------------------------

file_type_lookup = {}
for disk in fm['disks']:
    dk = f"{disk['year']}_PT{disk['part']}"
    for fil in disk['files']:
        file_type_lookup[(dk, fil['name'])] = (fil['type'], fil.get('size', 0))

# ---------------------------------------------------------------------------
# Match DOCS files to parent programs
# ---------------------------------------------------------------------------

DOCS_SUFFIXES = [
    ' INSTRUCTIONS', ' INSTR', ' NOTES', ' README', ' INST',
    '.INSTR', '.INST',
]

docs_entries = [e for e in raw if e.get('topics', [''])[0] == 'DOCS' and e.get('best', True)]
non_docs_entries = [e for e in raw if e.get('topics', [''])[0] != 'DOCS' and e.get('best', True)]

non_docs_by_disk = defaultdict(dict)
for e in non_docs_entries:
    non_docs_by_disk[e['disk_key']][e['original_name'].upper()] = e

non_docs_all = {}
for e in non_docs_entries:
    non_docs_all[e['original_name'].upper()] = e

has_instructions = {}  # (disk_key, prodos_name) -> instr_prodos_name
linkage = []
unmatched_docs = []

for doc in docs_entries:
    doc_name_upper = doc['original_name'].upper()
    bare = None
    for suf in DOCS_SUFFIXES:
        if doc_name_upper.endswith(suf):
            bare = doc_name_upper[:len(doc_name_upper) - len(suf)].strip()
            break

    matched_parent = None
    if bare:
        disk_programs = non_docs_by_disk.get(doc['disk_key'], {})
        if bare in disk_programs:
            matched_parent = disk_programs[bare]
        if not matched_parent:
            for dk, progs in non_docs_by_disk.items():
                if dk.startswith(str(doc['year'])):
                    if bare in progs:
                        matched_parent = progs[bare]
                        break
        if not matched_parent and bare in non_docs_all:
            matched_parent = non_docs_all[bare]
        if not matched_parent:
            for prog_name, prog_entry in disk_programs.items():
                if prog_name.startswith(bare) or bare.startswith(prog_name):
                    matched_parent = prog_entry
                    break

    if matched_parent:
        key = (matched_parent['disk_key'], matched_parent['prodos_name'])
        if key not in has_instructions:
            has_instructions[key] = doc['prodos_name']
        linkage.append({'matched': True, 'docs': doc['original_name'],
                        'parent': matched_parent['original_name']})
    else:
        unmatched_docs.append(doc['original_name'])
        linkage.append({'matched': False, 'docs': doc['original_name']})

matched_count = sum(1 for l in linkage if l['matched'])
print(f"DOCS linkage: {matched_count} matched, {len(unmatched_docs)} unmatched out of {len(docs_entries)} total")
if unmatched_docs:
    print("Unmatched DOCS:", unmatched_docs[:5])

# ---------------------------------------------------------------------------
# Load dependency-map.json to find picture files with parent programs
# ---------------------------------------------------------------------------

with open(DATA_DIR / 'dependency-map.json') as f:
    dep_map = json.load(f)

# Picture-file size threshold: HGR2 images are 8184 bytes on these disks
PICTURE_SIZE_MIN = 8000

# Build file-size/type lookup for non-docs entries
def get_file_info(disk_key, original_name):
    return file_type_lookup.get((disk_key, original_name), ('A', 0))

# Build: (disk_key, pic_prodos_name) -> parent_original_name
# For each BLOAD in dep_map, check if the referenced file is a picture
pic_prodos_to_parent_orig = {}
for item in dep_map:
    ref_prodos = item['referenced_file_prodos']
    dk = item['disk_key']
    # Look up the referenced file's type/size by its original name
    ref_orig = item['referenced_file']
    ftype, fsize = get_file_info(dk, ref_orig)
    if ftype == 'B' and fsize >= PICTURE_SIZE_MIN:
        key = (dk, ref_prodos)
        if key not in pic_prodos_to_parent_orig:
            pic_prodos_to_parent_orig[key] = item['program']

print(f"Picture->parent mappings from dependency-map: {len(pic_prodos_to_parent_orig)}")
for k, v in pic_prodos_to_parent_orig.items():
    print(f"  {k} -> {v}")

# Build lookup: (disk_key, parent_original_name) -> [pic_prodos_name, ...]
# We only want the FIRST picture per parent program
parent_orig_to_pic = {}
for (dk, pic_pn), parent_orig in pic_prodos_to_parent_orig.items():
    key = (dk, parent_orig)
    if key not in parent_orig_to_pic:
        parent_orig_to_pic[key] = pic_pn

print(f"Parent programs with linked pictures: {len(parent_orig_to_pic)}")

# Build set of picture prodos names that have a parent (should not appear standalone)
pics_with_parent = set(pic_prodos_to_parent_orig.keys())  # set of (dk, pic_prodos_name)

# ---------------------------------------------------------------------------
# Build enriched program list (non-DOCS only)
# ---------------------------------------------------------------------------


def txt_name_for(parent_prodos_name):
    """Compute the .T instruction text filename from the parent ProDOS name.

    ProDOS max filename length = 15.  If parent_name + '.T' > 15, truncate
    parent to 13 chars before appending.
    """
    base = parent_prodos_name
    if len(base) + 2 > 15:
        base = base[:13]
    return base + '.T'


programs = []
skipped_pics = []
for p in non_docs_entries:
    ftype, fsize = file_type_lookup.get((p['disk_key'], p['original_name']), ('A', 0))
    is_picture = (ftype == 'B' and fsize >= PICTURE_SIZE_MIN)
    flags = 0
    ikey = (p['disk_key'], p['prodos_name'])

    if is_picture:
        # Check if this picture file has a parent program
        if ikey in pics_with_parent:
            # This picture is linked to a parent program -- skip as standalone
            skipped_pics.append((p['disk_key'], p['prodos_name'], pic_prodos_to_parent_orig[ikey]))
            continue
        # Standalone picture (no parent in dependency map)
        flags = 4
        # Display name: strip trailing .PIC/.PIC1/.PIC2/etc. suffix
        disp = p['original_name'].upper()
        disp = re.sub(r'\.PIC\d*$', '', disp).strip()
        display_name = disp
    else:
        display_name = p['original_name'].upper()
        if ikey in has_instructions:
            flags |= 1
        if ftype == 'B':
            flags |= 2
        # Check if this program has a linked picture
        parent_key = (p['disk_key'], p['original_name'])
        if parent_key in parent_orig_to_pic:
            flags += 8

    programs.append({
        'year': p['year'],
        'prodos_name': p['prodos_name'],
        'display_name': display_name,
        'flags': flags,
        'topic': p['topics'][0],
    })

print(f"\nLoaded {len(programs)} non-DOCS programs (skipped {len(skipped_pics)} picture files with parent programs)")
if skipped_pics:
    for dk, pn, parent in skipped_pics:
        print(f"  Skipped: {dk}/{pn} (parent: {parent})")
binary_count = sum(1 for p in programs if p['flags'] in (2, 3, 10, 11))
has_instr_count = sum(1 for p in programs if p['flags'] in (1, 3, 9, 11))
pic_count = sum(1 for p in programs if p['flags'] == 4)
has_pic_count = sum(1 for p in programs if p['flags'] in (8, 9, 10, 11))
print(f"  Binary: {binary_count},  Has instructions: {has_instr_count},  Standalone pics: {pic_count},  Has linked pic: {has_pic_count}")

# ---------------------------------------------------------------------------
# Extract instruction text from BASIC files and write .T files
# ---------------------------------------------------------------------------

EXTRACTED_TEXT_DIR = str(DATA_DIR / 'extracted_text')


def extract_instr_text(bas_path):
    """Parse a BASIC instruction file and return list of text lines.

    Rules:
    - Match lines of form: NNN PRINT "..."  (literal string)
    - PRINT with no argument -> blank line
    - Skip PRINT CHR$(...), PRINT D$..., PRINT A$, PRINT variable, etc.
    - Replace commas in extracted text with semicolons
    - Replace pipe | with hyphen -
    """
    lines = []
    with open(bas_path, errors='replace') as f:
        for raw in f:
            raw = raw.rstrip('\n').rstrip('\r')
            # Strip leading line number and whitespace
            m = re.match(r'^\s*\d+\s+(.*)', raw)
            if not m:
                continue
            stmt = m.group(1).strip()
            # Skip REM lines
            if stmt.upper().startswith('REM'):
                continue
            # Match PRINT with optional trailing spaces then a double-quoted string
            m2 = re.match(r'^PRINT\s+"(.*)"', stmt, re.IGNORECASE)
            if m2:
                text = m2.group(1)
                text = text.replace(',', ';').replace('|', '-')
                lines.append(text)
                continue
            # Match bare PRINT (no argument) -> blank line
            m3 = re.match(r'^PRINT\s*$', stmt, re.IGNORECASE)
            if m3:
                lines.append('')
                continue
            # Match PRINT followed by a colon (multiple statements on one line)
            # e.g. "PRINT : PRINT" -> two blank lines
            # Handle "PRINT : PRINT "..."" style
            if re.match(r'^PRINT\s*:', stmt, re.IGNORECASE):
                lines.append('')
                # recurse on the remainder after the colon
                remainder = stmt[stmt.index(':') + 1:].strip()
                sub = re.match(r'^PRINT\s+"(.*)"', remainder, re.IGNORECASE)
                if sub:
                    text = sub.group(1).replace(',', ';').replace('|', '-')
                    lines.append(text)
                elif re.match(r'^PRINT\s*$', remainder, re.IGNORECASE):
                    lines.append('')
                continue
    return lines


def wrap_instr_lines(lines, max_width=36):
    """Wrap lines longer than max_width at word boundaries."""
    result = []
    for line in lines:
        if len(line) <= max_width:
            result.append(line)
        else:
            wrapped = textwrap.wrap(line, width=max_width, break_long_words=True)
            result.extend(wrapped)
    return result


def write_txt_file(path, lines):
    """Write instruction text as Apple II sequential text file (CR-only endings)."""
    if not lines:
        lines = ['SEE PROGRAM SOURCE CODE']
    encoded = [ln.encode('ascii', errors='replace') for ln in lines]
    with open(path, 'wb') as f:
        f.write(b'\r'.join(encoded) + b'\r')
    print(f"  Wrote {path} ({len(lines)} lines)")


def find_bas_file(disk_key, original_name):
    """Find the extracted BASIC file for a given disk_key and original_name."""
    folder = f'{EXTRACTED_TEXT_DIR}/{disk_key}/'
    # Sanitize: spaces -> _, keep hyphens
    attempt1 = original_name.upper().replace(' ', '_') + '.bas'
    if os.path.exists(folder + attempt1):
        return folder + attempt1
    # Fallback: hyphens -> _ as well
    attempt2 = original_name.upper().replace(' ', '_').replace('-', '_') + '.bas'
    if os.path.exists(folder + attempt2):
        return folder + attempt2
    return None


# Load docs-linkage to know which instruction files map to which parent
with open(DATA_DIR / 'docs-linkage.json') as f:
    docs_linkage = json.load(f)

# Build lookup: (parent_disk_key, parent_prodos_name) -> docs entry
parent_to_docs = {}
for entry in docs_linkage:
    if entry.get('matched'):
        key = (entry['parent_disk_key'], entry['parent_prodos_name'])
        parent_to_docs[key] = entry

print(f"\nGenerating instruction .T files for {len(parent_to_docs)} matched docs entries...")
txt_files_written = []
txt_files_empty = []

for (parent_disk_key, parent_prodos_name), doc_entry in parent_to_docs.items():
    docs_orig = doc_entry['docs_original_name']
    parent_year = doc_entry['parent_year']
    bas_path = find_bas_file(doc_entry['docs_disk_key'], docs_orig)

    if bas_path is None:
        print(f"  WARNING: Could not find bas file for {doc_entry['docs_disk_key']}/{docs_orig}")
        lines = ['SEE PROGRAM SOURCE CODE']
    else:
        raw_lines = extract_instr_text(bas_path)
        lines = wrap_instr_lines(raw_lines)
        if not lines:
            lines = ['SEE PROGRAM SOURCE CODE']
            txt_files_empty.append(parent_prodos_name)

    txt_name = txt_name_for(parent_prodos_name)
    local_path = str(DATA_DIR / 'instr_txt' / parent_disk_key / txt_name)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    write_txt_file(local_path, lines)
    txt_files_written.append((parent_disk_key, parent_year, parent_prodos_name, txt_name, local_path))

print(f"  Written: {len(txt_files_written)}, Empty (fell back to placeholder): {len(txt_files_empty)}")
if txt_files_empty:
    print(f"  Empty files: {txt_files_empty[:10]}")

# ---------------------------------------------------------------------------
# Fixed-record file generation
# ---------------------------------------------------------------------------

def make_record(year, prodos_name, display_name, flags, L=RECORD_LEN):
    """
    Build a fixed-length record:
      YEAR,PRODOS_NAME,DISPLAY_NAME,FLAGS,{padding}\r
    Total = L bytes exactly (L-1 chars + CR).
    The trailing comma + padding ensures FLAGS has no trailing spaces
    when read by Applesoft INPUT (INPUT stops at comma, padding never read).
    BASIC derives filenames: .T = LEFT$(PN$,13)+".T", .PIC = LEFT$(PN$,11)+".PIC"
    """
    data = f"{year},{prodos_name},{display_name},{flags},"
    if len(data) > L - 1:
        raise ValueError(f"Record too long ({len(data)} > {L-1}): {data!r}")
    # Pad to L-1 chars, then add CR
    padded = data.ljust(L - 1, ' ') + '\r'
    assert len(padded) == L, f"Expected {L}, got {len(padded)}"
    return padded.encode('ascii')


def write_data_file(path, records_bytes):
    """Write list of byte-strings to binary file (Apple II CR newlines)."""
    with open(path, 'wb') as f:
        for rec in records_bytes:
            f.write(rec)
    total = len(records_bytes)
    size = os.path.getsize(path)
    print(f"Wrote {path} ({total} records, {size} bytes, {size // RECORD_LEN} x {RECORD_LEN} bytes/rec = L{RECORD_LEN})")
    assert size == total * RECORD_LEN, f"Size mismatch: {size} != {total * RECORD_LEN}"


# ---------------------------------------------------------------------------
# BY.NAME data file -- sorted alphabetically by display_name
# ---------------------------------------------------------------------------

by_name_sorted = sorted(programs, key=lambda p: p['display_name'])

by_name_records = []
for p in by_name_sorted:
    by_name_records.append(make_record(
        p['year'], p['prodos_name'], p['display_name'], p['flags']
    ))

write_data_file(str(DIST_DIR / DATA_FILE_NAME), by_name_records)

# ---------------------------------------------------------------------------
# BY.YEAR data file -- sorted by year then display_name
# ---------------------------------------------------------------------------

by_year_sorted = sorted(programs, key=lambda p: (p['year'], p['display_name']))

# Compute year start records and counts (for hard-coded DATA in BY.YEAR.bas)
years_seen = []
year_start = {}
year_count = {}
for i, p in enumerate(by_year_sorted):
    yr = p['year']
    if yr not in year_start:
        year_start[yr] = i
        year_count[yr] = 0
        years_seen.append(yr)
    year_count[yr] += 1

by_year_records = []
for p in by_year_sorted:
    by_year_records.append(make_record(
        p['year'], p['prodos_name'], p['display_name'], p['flags']
    ))

write_data_file(str(DIST_DIR / DATA_FILE_YEAR), by_year_records)

print("\nYear start records (for BY.YEAR.bas DATA):")
for yr in years_seen:
    print(f"  {yr}: start={year_start[yr]}, count={year_count[yr]}")

# ---------------------------------------------------------------------------
# BY.TOPIC data file -- sorted by topic then display_name
# ---------------------------------------------------------------------------

by_topic_sorted = sorted(programs, key=lambda p: (p['topic'], p['display_name']))

# Compute topic start records and counts (for hard-coded DATA in BY.TOPIC.bas)
topics_seen = []
topic_start = {}
topic_count = {}
for i, p in enumerate(by_topic_sorted):
    t = p['topic']
    if t not in topic_start:
        topic_start[t] = i
        topic_count[t] = 0
        topics_seen.append(t)
    topic_count[t] += 1

by_topic_records = []
for p in by_topic_sorted:
    by_topic_records.append(make_record(
        p['year'], p['prodos_name'], p['display_name'], p['flags']
    ))

write_data_file(str(DIST_DIR / DATA_FILE_TOPIC), by_topic_records)

print("\nTopic start records (for BY.TOPIC.bas DATA):")
for t in topics_seen:
    print(f"  {t}: start={topic_start[t]}, count={topic_count[t]}")

# ---------------------------------------------------------------------------
# Helpers for BASIC generation
# ---------------------------------------------------------------------------

def write_bas(path, lines):
    """Write list of (lineno, text) pairs as plain-text BASIC listing.
    Lines are sorted by line number before writing (required for Applesoft tokenizer).
    """
    sorted_lines = sorted(lines, key=lambda x: x[0])
    with open(path, 'w') as f:
        for lineno, text in sorted_lines:
            f.write(f"{lineno} {text}\n")
    lc = len(sorted_lines)
    sz = os.path.getsize(path)
    print(f"Wrote {path} ({lc} lines, {sz} bytes)")


def validate_bas(path):
    issues = []
    seen = {}
    with open(path) as f:
        for file_lineno, raw_line in enumerate(f, 1):
            raw_line = raw_line.rstrip('\n')
            if not raw_line.strip():
                continue
            parts = raw_line.split(' ', 1)
            if len(parts) < 2:
                issues.append(f"Line {file_lineno}: no content: {raw_line!r}")
                continue
            try:
                bas_lineno = int(parts[0])
            except ValueError:
                issues.append(f"Line {file_lineno}: bad line number: {raw_line!r}")
                continue
            if bas_lineno in seen:
                issues.append(f"Duplicate BASIC line {bas_lineno} at file lines {seen[bas_lineno]} and {file_lineno}")
            else:
                seen[bas_lineno] = file_lineno
            if len(raw_line) > 239:
                issues.append(f"BASIC line {bas_lineno}: length {len(raw_line)} > 239")
    return issues


# ---------------------------------------------------------------------------
# STARTUP.bas
# ---------------------------------------------------------------------------

startup_lines = [
    (10, 'PRINT CHR$(4)"RUN MENU"'),
]
write_bas(str(DIST_DIR / 'STARTUP.bas'), startup_lines)

# ---------------------------------------------------------------------------
# MENU.bas
# ---------------------------------------------------------------------------

non_docs_total = len(programs)
menu_lines = [
    (10,   'HOME'),
    (20,   'VTAB 4'),
    (30,   'PRINT "  NIBBLE ONE & TWO LINERS"'),
    (40,   'PRINT "  ========================"'),
    (50,   f'PRINT "  {non_docs_total} PROGRAMS, 1984-1992"'),
    (60,   'PRINT ""'),
    (70,   'PRINT "  1) BROWSE BY YEAR"'),
    (80,   'PRINT "  2) BROWSE BY NAME"'),
    (90,   'PRINT "  3) BROWSE BY TOPIC"'),
    (100,  'PRINT "  4) ABOUT"'),
    (110,  'PRINT ""'),
    (120,  'PRINT "  CHOOSE (1-4): ";'),
    (130,  'GET K$'),
    (140,  'IF K$="1" THEN PRINT CHR$(4)"RUN BY.YEAR"'),
    (150,  'IF K$="2" THEN PRINT CHR$(4)"RUN BY.NAME"'),
    (160,  'IF K$="3" THEN PRINT CHR$(4)"RUN BY.TOPIC"'),
    (170,  'IF K$="4" THEN GOSUB 1000: GOTO 10'),
    (180,  'GOTO 130'),
    (1000, 'HOME: VTAB 8'),
    (1010, 'PRINT "  NIBBLE ONE & TWO LINERS"'),
    (1020, 'PRINT "  COMPLETE COLLECTION"'),
    (1030, f'PRINT "  {non_docs_total} PROGRAMS, 1984-1992"'),
    (1040, 'PRINT ""'),
    (1050, 'PRINT "  WHEN DONE WITH A PROGRAM,"'),
    (1060, 'PRINT "  TYPE:  RUN MENU"'),
    (1070, 'PRINT ""'),
    (1080, 'PRINT "  PRESS ANY KEY..."'),
    (1090, 'GET K$: RETURN'),
]
write_bas(str(DIST_DIR / 'MENU.bas'), menu_lines)

# ---------------------------------------------------------------------------
# Common page-browse subroutine generator
# Used by all three browse programs.
#
# Variables used:
#   D$    = CHR$(4) (DOS escape prefix)
#   SR    = start record (0-based) for current section
#   NR    = number of records in current section
#   PG    = current page (0-based page index)
#   FN$   = filename to open ("BY.NAME", "BY.YEAR", or "BY.TOPIC")
#   HDR$  = header string for display
#
# After page display and input:
#   SN    = selected item number (1-based within page)
#   RY    = year of selected item
#   PN$   = prodos name of selected item
#   FL    = flags of selected item
#   DN$   = display name (used in run dialog)
#   IT$   = derived instruction text filename (LEFT$(PN$(SN),13)+".T")
#
# The browse loop stores page items as arrays DIM'd to PAGE_SIZE and indexed with SN.
#
# Structure:
#   10-199:   init + section picker
#   200-499:  (section-specific dispatch)
#   500-599:  open file
#   600-699:  (section-specific pre-page setup if needed)
#   1000-1499: page display loop
#   1500-1999: navigation input
#   2000-2999: run/instructions dialog
#   9000-9099: trim trailing spaces from IN$ (used before RUN path)
# ---------------------------------------------------------------------------

def gen_browse_program(file_var, hdr_expr, init_lines):
    """
    Generate a compact browse BASIC program.

    file_var:         ProDOS data filename string (e.g. 'NAME.DATA')
    hdr_expr:         BASIC expression for page header (e.g. '"BROWSE BY NAME"')
    init_lines:       list of (lineno, text) for lines 10..499
                      Must set: D$, SR, NR, PG=0
                      Must end with GOTO 500

    Variable conventions:
      D$         = CHR$(4)
      SR         = start record for section (0-based)
      NR         = total records in section
      PG         = current page (0-based)
      NC         = count of items loaded on current page
      SN         = selected item index (1-based, within page)
      YR(1..19)  = year for each page item
      PN$(1..19) = prodos_name for each page item
      DN$(1..19) = display_name for each page item
      FL(1..19)  = flags for each page item
      HV         = 1 if selected item has linked picture, else 0
      IT$        = derived instruction text filename (LEFT$(PN$(SN),13)+".T")
      PY$        = full ProDOS path for run/picture (built at use time)

    Flags checked in BASIC (no bitwise AND in Applesoft):
      Has instructions: FL=1 OR FL=3 OR FL=9 OR FL=11
      Is binary:        FL=2 OR FL=3 OR FL=10 OR FL=11
      Has picture:      FL=8 OR FL=9 OR FL=10 OR FL=11
      Standalone pic:   FL=4

    Control flow:
      init -> GOTO 500 (open file, dim arrays) -> GOTO 1000
      1000: page read loop -> 1300: display + input -> 1500: navigate
      1100: normal close after full page -> GOTO 1300
      1200: EOF/error close -> GOTO 1300
      2000: run dialog -> 2200: prompt -> 2300: run or 2400: view picture

    Returns list of (lineno, text).
    """
    L = list(init_lines)

    # 500-599: init -- dim arrays, fall into page display (file opened per page)
    L.append((500, 'D$=CHR$(4)'))
    L.append((510, f'DIM YR({PAGE_SIZE}),PN$({PAGE_SIZE}),DN$({PAGE_SIZE}),FL({PAGE_SIZE})'))
    L.append((520, 'GOTO 1000'))

    # 1000-1299: open file, seek to page, read records, close file
    L.append((1000, 'REM READ PAGE'))
    L.append((1005, f'PRINT D$"OPEN {file_var},L{RECORD_LEN}"'))
    L.append((1010, f'PRINT D$"POSITION {file_var},R";SR+PG*{PAGE_SIZE}'))
    L.append((1020, f'PRINT D$"READ {file_var}"'))
    L.append((1030, 'ONERR GOTO 1200'))
    L.append((1040, 'NC=0'))
    L.append((1050, f'FOR I=1 TO {PAGE_SIZE}'))
    L.append((1060, '  INPUT YR(I),PN$(I),DN$(I),FL(I)'))
    L.append((1070, '  IF YR(I)=0 THEN I=99: GOTO 1090'))
    L.append((1080, '  NC=NC+1'))
    L.append((1090, 'NEXT I'))
    # Normal end of loop: close file, clear error, go display
    L.append((1100, f'PRINT D$"CLOSE {file_var}"'))
    L.append((1110, 'POKE 216,0: GOTO 1300'))
    # EOF/error handler: close file (already may be closed), clear error, go display
    L.append((1200, 'POKE 216,0'))
    L.append((1210, f'PRINT D$"CLOSE {file_var}"'))
    L.append((1220, 'POKE 216,0'))

    # 1300-1499: display page
    L.append((1300, 'HOME'))
    L.append((1310, f'TP=INT((NR+{PAGE_SIZE-1})/{PAGE_SIZE})'))
    L.append((1320, f'PRINT "  ";{hdr_expr};"  PG ";PG+1;" OF ";TP'))
    L.append((1330, 'PRINT "  =============================="'))
    L.append((1340, 'PRINT ""'))
    L.append((1350, 'FOR I=1 TO NC'))
    L.append((1360, '  PRINT "  ";I;") ";LEFT$(DN$(I),26)'))
    L.append((1370, 'NEXT I'))
    L.append((1380, 'PRINT ""'))
    L.append((1390, f'PRINT "  N)EXT  P)REV  Q)UIT  1-{PAGE_SIZE} > ";'))
    # Use GET for single-char navigation; handle 1-digit and 2-digit numbers
    L.append((1410, 'GET K$'))
    L.append((1420, 'PRINT K$'))

    # 1500-1999: navigation (single-char, no RETURN needed)
    L.append((1500, 'IF K$="Q" OR K$="q" THEN PRINT D$"RUN MENU": END'))
    L.append((1510, f'IF (K$="N" OR K$="n") AND (PG+1)*{PAGE_SIZE}<NR THEN PG=PG+1: GOTO 1000'))
    L.append((1520, 'IF K$="N" OR K$="n" THEN GOTO 1300'))
    L.append((1530, 'IF (K$="P" OR K$="p") AND PG>0 THEN PG=PG-1: GOTO 1000'))
    L.append((1540, 'IF K$="P" OR K$="p" THEN GOTO 1300'))
    L.append((1550, 'SN=VAL(K$)'))
    # For 1: prompt for second digit; any non-digit key confirms selection 1
    # For SN=1: PRINT "1", then GET second key
    #   if K2$ is "0"-"8", SN becomes 10+VAL(K2$): handles 10-18
    #   if K2$ is "9", SN becomes 19
    L.append((1555, 'IF SN<>1 THEN GOTO 1575'))
    L.append((1560, 'GET K2$: PRINT K2$'))
    L.append((1565, 'IF K2$>="0" AND K2$<="8" THEN SN=10+VAL(K2$)'))
    L.append((1567, 'IF K2$="9" THEN SN=19'))
    L.append((1575, 'IF SN>=1 AND SN<=NC THEN GOTO 2000'))
    L.append((1580, 'GOTO 1410'))

    # 2000-2999: run dialog
    # FL=1 or FL=3 or FL=9 or FL=11 (has instructions): show instruction text inline
    # FL=4 (standalone picture): show V) VIEW  Q) BACK
    # FL=8,9,10,11 (has linked picture): show R) RUN  P) PICTURE  Q) BACK
    # FL=0,1,2,3 (no picture): show R) RUN  Q) BACK
    L.append((2000, 'REM RUN DIALOG'))
    L.append((2010, 'HOME'))
    L.append((2020, 'VTAB 2: PRINT "  ";DN$(SN)'))
    L.append((2030, 'PRINT "  =============================="'))
    # Inline instruction display for FL=1,3,9,11
    L.append((2040, 'IF FL(SN)<>1 AND FL(SN)<>3 AND FL(SN)<>9 AND FL(SN)<>11 THEN GOTO 2200'))
    L.append((2050, 'REM SHOW INLINE INSTRUCTIONS'))
    L.append((2060, 'IT$=LEFT$(PN$(SN),13)+".T"'))
    L.append((2080, 'IT$="Y"+STR$(YR(SN))+"/"+IT$'))
    L.append((2090, 'PRINT D$"OPEN ";IT$'))
    L.append((2100, 'PRINT D$"READ ";IT$'))
    L.append((2110, 'ONERR GOTO 2180'))
    L.append((2120, 'VI=5'))
    L.append((2130, 'INPUT LN$'))
    L.append((2140, 'VTAB VI: HTAB 3: PRINT LEFT$(LN$,36)'))
    L.append((2150, 'VI=VI+1: IF VI>20 THEN GOTO 2180'))
    L.append((2160, 'GOTO 2130'))
    L.append((2180, 'POKE 216,0'))
    L.append((2190, 'PRINT D$"CLOSE ";IT$'))
    # Show prompt
    L.append((2200, 'REM SHOW PROMPT'))
    L.append((2210, 'VTAB 22: PRINT "  =============================="'))
    L.append((2220, 'IF FL(SN)=4 THEN GOTO 2350'))
    # Determine if this program has a linked picture (HV=1 means has picture)
    L.append((2225, 'HV=0: IF FL(SN)=8 OR FL(SN)=9 OR FL(SN)=10 OR FL(SN)=11 THEN HV=1'))
    L.append((2230, 'PRINT "  R) RUN";'))
    L.append((2232, 'IF HV=1 THEN PRINT "  P) PICTURE";'))
    L.append((2234, 'PRINT "  Q) BACK"'))
    L.append((2235, 'VTAB 24: PRINT "  > ";'))
    L.append((2240, 'GET K$'))
    L.append((2250, 'IF K$="Q" OR K$="q" THEN GOTO 1000'))
    L.append((2260, 'IF K$="R" OR K$="r" THEN GOTO 2300'))
    L.append((2265, 'IF HV=1 AND (K$="P" OR K$="p") THEN GOTO 2400'))
    L.append((2270, 'GOTO 2240'))
    # Standalone picture prompt
    L.append((2350, 'PRINT "  V) VIEW   Q) BACK"'))
    L.append((2360, 'VTAB 24: PRINT "  > ";'))
    L.append((2370, 'GET K$'))
    L.append((2380, 'IF K$="Q" OR K$="q" THEN GOTO 1000'))
    L.append((2390, 'IF K$="V" OR K$="v" THEN GOTO 2400'))
    L.append((2396, 'GOTO 2380'))

    # Run program
    L.append((2300, 'REM RUN PROGRAM'))
    L.append((2310, 'PY$="Y"+STR$(YR(SN))+"/"+PN$(SN)'))
    L.append((2320, 'IF FL(SN)=2 OR FL(SN)=3 OR FL(SN)=10 OR FL(SN)=11 THEN PRINT D$"BRUN ";PY$: END'))
    L.append((2330, 'PRINT D$"RUN ";PY$: END'))

    # Picture viewer: for standalone (FL=4) use PN$, for linked (FL=8/9/10/11) derive from PN$
    L.append((2400, 'REM VIEW PICTURE'))
    L.append((2410, 'IF FL(SN)=4 THEN T$=PN$(SN): GOTO 2430'))
    L.append((2420, 'T$=LEFT$(PN$(SN),11)+".PIC"'))
    L.append((2430, 'PY$="Y"+STR$(YR(SN))+"/"+T$'))
    L.append((2440, 'PRINT D$"BLOAD ";PY$;",A$4000"'))
    L.append((2450, 'HGR2'))
    L.append((2460, 'GET K$'))
    L.append((2470, 'TEXT: HOME'))
    L.append((2480, 'GOTO 1000'))

    return L


# ---------------------------------------------------------------------------
# BY.NAME.bas
# ---------------------------------------------------------------------------

total_names = len(by_name_sorted)

name_init = [
    (10,  'HOME'),
    (20,  f'NR={total_names}: SR=0: PG=0'),
    (30,  'GOTO 500'),
]

by_name_lines = gen_browse_program(
    file_var=DATA_FILE_NAME,
    hdr_expr='"BROWSE BY NAME"',
    init_lines=name_init,
)
write_bas(str(DIST_DIR / 'BY.NAME.bas'), by_name_lines)

# ---------------------------------------------------------------------------
# BY.YEAR.bas
# ---------------------------------------------------------------------------
# Hard-coded DATA: year_start_record, year_count for each year (9 years)
# DATA line at 100: year1_start, year1_count, year2_start, year2_count, ...

year_data_vals = []
for yr in years_seen:
    year_data_vals.append(year_start[yr])
    year_data_vals.append(year_count[yr])
year_data_str = ",".join(str(v) for v in year_data_vals)

year_menu_lines_init = []
year_menu_lines_init.append((10,  'HOME'))
year_menu_lines_init.append((20,  'D$=CHR$(4)'))
year_menu_lines_init.append((30,  'VTAB 3: PRINT "  BROWSE BY YEAR"'))
year_menu_lines_init.append((40,  'PRINT "  ==============="'))
year_menu_lines_init.append((50,  'PRINT ""'))

ln = 60
for i, yr in enumerate(years_seen):
    cnt = year_count[yr]
    year_menu_lines_init.append((ln, f'PRINT "  {i+1}) {yr}  ({cnt})"'))
    ln += 10

year_menu_lines_init.append((ln,    'PRINT ""'))
year_menu_lines_init.append((ln+10, 'PRINT "  Q) BACK TO MENU"'))
year_menu_lines_init.append((ln+20, 'PRINT ""'))
year_menu_lines_init.append((ln+30, 'PRINT "  CHOOSE YEAR: ";'))
year_menu_lines_init.append((ln+40, 'GET K$'))
year_menu_lines_init.append((ln+50, 'IF K$="Q" OR K$="q" THEN PRINT D$"RUN MENU": END'))
year_menu_lines_init.append((ln+60, f'YI=VAL(K$): IF YI<1 OR YI>{len(years_seen)} THEN GOTO {ln+30}'))
# Read start record and count from DATA
year_menu_lines_init.append((ln+70, 'REM READ YEAR START/COUNT FROM DATA'))
# DATA layout: start1,count1,start2,count2,...
# For year YI: skip (YI-1)*2 values, then read SR, NR
# Use explicit GOTO to avoid IF...THEN FOR...NEXT parse problems in Applesoft
# RESTORE (no arg) resets to first DATA in program (line 400 is the only DATA)
year_menu_lines_init.append((ln+75, 'RESTORE'))
year_menu_lines_init.append((ln+80, f'SK=(YI-1)*2: IF SK=0 THEN GOTO {ln+90}'))
year_menu_lines_init.append((ln+85, 'FOR I=1 TO SK: READ XV: NEXT I'))
year_menu_lines_init.append((ln+90, 'READ SR,NR'))
# Set year display variable used in header
year_menu_lines_init.append((ln+95, f'RY=1983+YI: PG=0: GOTO 500'))

# DATA block at line 400
year_menu_lines_init.append((400, f'DATA {year_data_str}'))

# After OPEN (line 500+), no extra setup needed
# But we need to remove D$=CHR$(4) from gen_browse_program since we set it at line 20
# The gen_browse_program sets D$ at 500 -- that's fine (it just reassigns it)

year_browse_lines = gen_browse_program(
    file_var=DATA_FILE_YEAR,
    hdr_expr='"YEAR ";RY',
    init_lines=year_menu_lines_init,
)
write_bas(str(DIST_DIR / 'BY.YEAR.bas'), year_browse_lines)

# ---------------------------------------------------------------------------
# BY.TOPIC.bas
# ---------------------------------------------------------------------------
# Hard-coded DATA: topic_name, topic_start_record, topic_count (12 topics)

topic_data_lines = []
# 12 topics * 10 = 120 lines; start at 700 to avoid collision with gen_browse_program's 500-599
tln = 700
for t in topics_seen:
    topic_data_lines.append((tln, f'DATA "{t}",{topic_start[t]},{topic_count[t]}'))
    tln += 10

topic_init = []
topic_init.append((10,  'HOME'))
topic_init.append((20,  'D$=CHR$(4)'))
topic_init.append((30,  'VTAB 3: PRINT "  BROWSE BY TOPIC"'))
topic_init.append((40,  'PRINT "  ================"'))
topic_init.append((50,  'PRINT ""'))

ln = 60
for i, t in enumerate(topics_seen):
    cnt = topic_count[t]
    topic_init.append((ln, f'PRINT "  {i+1:2}) {t:<12} ({cnt:3})"'))
    ln += 10

topic_init.append((ln,    'PRINT ""'))
topic_init.append((ln+10, 'PRINT "  Q) BACK TO MENU"'))
topic_init.append((ln+20, 'PRINT ""'))
topic_init.append((ln+30, f'PRINT "  CHOOSE (1-{len(topics_seen)}): ";'))
# GET-based single-char input (no RETURN needed)
topic_init.append((ln+35, 'GET K$: PRINT K$'))
topic_init.append((ln+40, 'IF K$="Q" OR K$="q" THEN PRINT D$"RUN MENU": END'))
topic_init.append((ln+45, 'TI=VAL(K$): IF TI<1 OR TI>9 THEN GOTO ' + str(ln+30)))
# For TI=1: could be 1, 10, 11, or 12 -- get second digit
topic_init.append((ln+50, f'IF TI=1 THEN GET K2$: PRINT K2$: IF K2$>="0" AND K2$<="2" THEN TI=10+VAL(K2$)'))
topic_init.append((ln+55, f'IF TI<1 OR TI>{len(topics_seen)} THEN GOTO {ln+30}'))
# Read topic info from DATA (3 fields per topic: name, start, count)
topic_init.append((ln+70, 'REM READ TOPIC FROM DATA'))
# RESTORE (no arg) resets to first DATA in program (line 700+ is the only DATA)
topic_init.append((ln+80, 'RESTORE: FOR I=1 TO TI: READ TT$,SR,NR: NEXT I'))
topic_init.append((ln+90, 'PG=0: GOTO 500'))

topic_init.extend(topic_data_lines)

topic_browse_lines = gen_browse_program(
    file_var=DATA_FILE_TOPIC,
    hdr_expr='TT$',
    init_lines=topic_init,
)
write_bas(str(DIST_DIR / 'BY.TOPIC.bas'), topic_browse_lines)

# ---------------------------------------------------------------------------
# Validate all generated .bas files
# ---------------------------------------------------------------------------

print("\nValidating generated files:")
all_ok = True
for fname in ['STARTUP.bas', 'MENU.bas', 'BY.YEAR.bas', 'BY.NAME.bas', 'BY.TOPIC.bas']:
    path = str(DIST_DIR / fname)
    issues = validate_bas(path)
    with open(path) as f:
        lc = sum(1 for _ in f)
    sz = os.path.getsize(path)
    if issues:
        print(f"  {fname}: {len(issues)} ISSUES:")
        for iss in issues[:10]:
            print(f"    {iss}")
        all_ok = False
    else:
        print(f"  {fname}: OK ({lc} lines, {sz} bytes)")

# Verify data file sizes
num_programs = len(programs)
print("\nVerifying data file sizes:")
for fname in [DATA_FILE_NAME, DATA_FILE_YEAR, DATA_FILE_TOPIC]:
    path = str(DIST_DIR / fname)
    sz = os.path.getsize(path)
    expected = num_programs * RECORD_LEN
    status = "OK" if sz == expected else f"MISMATCH (expected {expected})"
    print(f"  {fname}: {sz} bytes = {sz // RECORD_LEN} records x {RECORD_LEN} [{status}]")

if all_ok:
    print("\nAll generated files valid.")
else:
    print("\nFIXES NEEDED.")
    sys.exit(1)

# Write a manifest of generated instruction text files for build_image.py to consume
instr_manifest = []
for (parent_disk_key, parent_year, parent_prodos_name, txt_name, local_path) in txt_files_written:
    instr_manifest.append({
        'disk_key': parent_disk_key,
        'year': parent_year,
        'prodos_name': parent_prodos_name,
        'txt_name': txt_name,
        'local_path': local_path,
    })

import json as _json
manifest_path = DIST_DIR / 'instr-manifest.json'
with open(manifest_path, 'w') as f:
    _json.dump(instr_manifest, f, indent=2)
print(f"\nWrote instr-manifest.json ({len(instr_manifest)} entries) to {manifest_path}")
