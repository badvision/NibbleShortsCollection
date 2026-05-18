# Nibble Magazine One and Two-liner Apple II Library

446 BASIC and binary programs extracted from Nibble magazine "One and Two Minute Programs" disk images (1984–1992), packaged as a browseable ProDOS 800KB hard disk image with menus by year, name, and topic.

## Try It Now — In Your Browser

[**▶ Launch in Apple2ts**](https://apple2ts.com/#https://github.com/badvision/NibbleShortsCollection/releases/download/v1.0/Nibble.1.and.2.liner.collection.po)

No installation needed — boots directly in the browser.

[**⬇ Download disk image (.po)**](https://github.com/badvision/NibbleShortsCollection/releases/download/v1.0/Nibble.1.and.2.liner.collection.po)

## Build

```
make
```

Output: `dist/Nibble 1 and 2 liner collection.po` (800KB ProDOS image, ~720KB used)

**Requirements:**
- Python 3
- `cp2` (CiderPress II) on PATH
- `ProDOS_2.4.2.dsk` at `/Users/brobert/Desktop/Disks/ProDOS_2.4.2.dsk`

The build runs in two phases:
1. `generate_menus.py` — produces BASIC menu programs, data files, and instruction `.T` text files into `dist/`
2. `build_image.py` — assembles the ProDOS disk image (~7 seconds)

## Using the Disk

Boot in any Apple II emulator or real hardware with a SmartPort-compatible hard drive interface. At the menu:

- **1) Browse by Year** — scroll through programs by year (1984–1992)
- **2) Browse by Name** — alphabetical listing across all years
- **3) Browse by Topic** — browse by category (GAMES, UTILITIES, HI.RES, etc.)
- **4) About** — usage notes

When a program has an instruction file, the menu shows it before running. Programs with hi-res pictures display them after running (press any key to advance).

Press `$` (Shift-4) for 40-column mode, `*` (Shift-8) for 80-column mode, from any browse screen.

To return to the menu from any program: `RUN MENU`

## Program Data

The canonical program list is `data/topic-assignments.json`. Each entry has:

```json
{
  "disk_key": "1985_PT2",
  "original_name": "MANDELBROT",
  "prodos_name": "MANDELBROT",
  "year": 1985,
  "best": true,
  "topics": ["HI.RES", "MATH"],
  "description": "...",
  "graphics_mode": "HGR2"
}
```

**Key fields:**
- `best: false` — excludes the entry from the disk image entirely
- `topics` — array of topics; a program appears in each topic's browse section. `topics[0]` is the primary topic.
- `"DOCS"` as `topics[0]` — marks instruction/pic-only support files excluded as executables
- `prodos_name` — ProDOS filename on disk (max 15 chars, no spaces)

### Topics

`ANIMATION`, `AUDIO`, `DEMOS`, `EDUCATION`, `GAMES`, `GRAPHICS`, `HI.RES`, `IIGS`, `LO.RES`, `MATH`, `PRODUCTIVITY`, `SCIENCE`, `TEXT`, `UTILITIES`

`PRODUCTIVITY` = serves a general non-computer real-world purpose (calendar, checkbook, document reader, navigation). `UTILITIES` = programming/systems tools (disk, memory, BASIC, DOS/ProDOS). Topics are built dynamically from the data — the topic menu reflects whatever categories are present. Programs with multiple topics appear under each one.

Special internal topic `DOCS` marks instruction BASIC files and standalone pic files linked to a parent program. DOCS BASIC files are excluded from the disk as executables; DOCS BIN files (pics) are included for BLOAD.

## Reclassifying Programs

1. Edit `data/topic-assignments.json` — change `topics`, `best`, or `prodos_name`
2. `make` to rebuild

To exclude a program entirely: set `"best": false`.
To recategorize: change `topics[0]` (and add/remove entries in the array as needed).

To fix a mislinked instruction file: edit `data/docs-linkage.json` directly — find the entry by `docs_original_name` and correct `parent_prodos_name`, `parent_disk_key`, and `parent_year`.

## Project Layout

```
data/
  topic-assignments.json    Canonical program list — primary editable file
  file-manifest.json        Original disk catalog (file types, load addresses)
  dependency-map.json       BLOAD/BRUN cross-references between programs
  docs-linkage.json         Maps instruction BASIC files to parent programs
  name-mapping.json         Original name → ProDOS name mapping
  disk-jsons/               Per-disk catalog JSON files from original images
  extracted/                Raw program binaries extracted from source disks
  extracted_text/           Text-format source files
  instr_txt/                Generated instruction .T text files (PRODOS_NAME[:13].T)

src/
  generate_menus.py         Phase 1: generate BASIC menus + data files
  build_image.py            Phase 2: assemble ProDOS disk image

tools/
  AppleCommander-ac.jar     Kept for reference; not used in build

dist/                       Build output (not committed)
  Nibble 1 and 2 liner collection.po   The assembled disk image
  *.bas                     Generated BASIC source listings
  *.DATA                    Fixed-record data files (L=55)
  instr-manifest.json       Maps parent programs to their .T instruction files
```

## Data File Format

The menu programs read fixed-length records (L=55) from `NAME.DATA`, `YEAR.DATA`, and `TOPIC.DATA`. Each record is 54 bytes of content plus a carriage return:

```
YEAR_OFFSET,PRODOS_NAME,DISPLAY_NAME,FLAGS,PC\r
```

- `YEAR_OFFSET` — year minus 1983 (1=1984 … 9=1992); value 0 is the end-of-data sentinel
- `PRODOS_NAME` — ProDOS filename, max 15 chars
- `DISPLAY_NAME` — original program name truncated to 30 chars
- `FLAGS` — 0=BASIC, 1=BASIC+instructions, 2=binary, 3=binary+instructions, 4=standalone pic
- `PC` — pic count (0–9); number of hi-res images linked to this program

`NAME.DATA` and `YEAR.DATA` contain one record per program (446 records). `TOPIC.DATA` contains one record per (program, topic) pair — programs with multiple topics appear once per topic (645 records total).

## Instruction Files

Programs with a companion instruction file in `docs-linkage.json` get their instructions extracted as a `.T` text file placed in the year directory on disk (e.g. `Y1985/MANDELBROT.T`). The menu BASIC reads and displays this before running the program.

Instruction `.T` filenames are derived at runtime: `LEFT$(PRODOS_NAME, 13) + ".T"`

## Hi-Res Pictures

Programs with linked hi-res pictures have `PC > 0`. The menu BASIC:
1. Switches to HGR2 (`HGR2`) — must come before BLOAD to avoid artifacts
2. BLOADs the picture to `$4000`
3. Waits for a keypress, then returns to the program detail screen

Picture filenames derived at runtime:
- PC=1: `LEFT$(PRODOS_NAME, 11) + ".PIC"`
- PC>1: `LEFT$(PRODOS_NAME, 11) + ".P" + STR$(pic_index)`

Multi-pic programs cycle through all images before returning to the menu.

## Disk Structure

```
NIBBLE.1AND2/
  PRODOS          SYS  — ProDOS kernel (load addr $0000)
  BASIC.SYSTEM    SYS  — Applesoft BASIC interpreter (load addr $2000)
  STARTUP         BAS  — auto-runs MENU on boot
  MENU            BAS  — main menu
  BY.YEAR         BAS  — browse by year
  BY.NAME         BAS  — browse by name
  BY.TOPIC        BAS  — browse by topic
  NAME.DATA       TXT  — L=55 records sorted by name (446 records)
  YEAR.DATA       TXT  — L=55 records sorted by year (446 records)
  TOPIC.DATA      TXT  — L=55 records sorted by topic (645 records)
  Y1984/               — 41 programs + instruction files + MENU stub
  Y1985/               — 120 programs + instruction files + MENU stub
  Y1986/               — 55 programs + instruction files + MENU stub
  Y1987/               — 48 programs + instruction files + MENU stub
  Y1988/               — 43 programs + instruction files + MENU stub
  Y1989/               — 43 programs + instruction files + MENU stub
  Y1990/               — 44 programs + instruction files + MENU stub
  Y1991/               — 38 programs + instruction files + MENU stub
  Y1992/               — 14 programs + instruction files + MENU stub
```

Each year directory contains a `MENU` stub that resets the ProDOS prefix to `/` and chains to the root `MENU` program, so `RUN MENU` works correctly after any program exits.
