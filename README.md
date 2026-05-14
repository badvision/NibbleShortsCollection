# Nibble Magazine Apple II Library

471 BASIC and binary programs extracted from Nibble magazine disk images (1984–1992), packaged as a browseable ProDOS 2MB hard disk image.

## Build

```
make
```

Output: `dist/NIBBLE.LIBRARY.po` (~2MB ProDOS image)

Requirements: Python 3, Java, `cp2` (CiderPress II), ProDOS_2.4.2.dsk at `/Users/brobert/Desktop/Disks/ProDOS_2.4.2.dsk`

## Reclassify Programs

1. Edit `data/topic-assignments.json` — change `primary_topic`, `secondary_topic`, or `best` fields
2. Run `make` to regenerate the disk image

## Project Layout

```
data/                   Source data (version-controlled)
  topic-assignments.json    Primary editable file for reclassification
  extracted/                Raw program files from source disks
  instr_txt/                Instruction text files (.T) per program
  disk-jsons/               Disk catalog JSON files
src/                    Build scripts
tools/                  AppleCommander JAR
dist/                   Build output (not committed)
```
