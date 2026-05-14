# Agent Notes — Nibble Library Build System

Discoveries and constraints for automated agents working on this project. Read this before making changes to the build pipeline.

---

## Critical: AppleCommander Cannot Write SYS Files Correctly

**AppleCommander's `-p` flag corrupts the first $200 bytes (512 bytes) of SYS files**, writing zeros instead of the actual content. This breaks ProDOS boot because the PRODOS kernel's first block is zeroed out.

**Fix:** Use `cp2 copy` to transfer PRODOS and BASIC.SYSTEM from the source disk:

```python
run([CP2, "copy", str(BASE_DISK), "PRODOS", "BASIC.SYSTEM", str(OUTPUT_IMAGE)])
```

Never use `ac("-p", ..., "SYS", ...)` for PRODOS or BASIC.SYSTEM. AppleCommander `-p` is fine for BAS, BIN, and TXT files.

---

## PRODOS Load Address Must Be $0000

When ProDOS boots, it expects its kernel at load address `$0000` in the directory entry. AppleCommander and cp2 preserve the load address from the source file when using `cp2 copy`, so this is handled automatically. If you ever manually write PRODOS, pass `0x0000` not `0x2000`.

BASIC.SYSTEM loads at `$2000` — that is correct.

---

## Image Size: 800KB

The disk image target is 800KB (`cp2 create-disk-image ... 800kb prodos`). Current usage is ~708KB with ~111KB free. The fallback in `create_image()` uses AppleCommander `-pro800` which also produces an 800KB image.

Do not increase to 2MB without a reason — the data fits comfortably in 800KB.

---

## DOCS Entries in topic-assignments.json

`topics[0] == "DOCS"` marks two categories of support files:

1. **Instruction BASIC files** (file type `A`) — these are `.2` / `.INSTR` variants that contain usage instructions for a parent program. They are excluded from the disk as executables. Their content is extracted into `.T` text files in `data/instr_txt/` by `generate_menus.py` and placed in the year directory on disk.

2. **Standalone pic files** (file type `B`) — hi-res images linked to a parent program. These have `best: true` and ARE written to disk because the parent program BLOADs them. Examples: `THREED.PLT1.PIC`, `JULIA.FRACT.P1`.

The filter in `populate_programs()` (`build_image.py`) skips DOCS entries with file type `A`. It does not skip DOCS BIN files.

**Important:** All 192 DOCS entries currently have `best: true`. This is intentional — the `best` flag alone does not control DOCS exclusion. The `topics[0] == "DOCS"` + file-type check does.

---

## Renamed Pic Files

Several multi-pic programs had filenames renamed in `data/extracted/` to fit ProDOS 15-char limits and avoid naming collisions. The canonical names in `topic-assignments.json` reflect the new names:

| Original on source disk | Renamed to |
|-------------------------|------------|
| `THREE-D_PLOT_1.PIC` | `THREED.PLT1.PIC` |
| `THREE-D_PLOT_2.PIC` | `THREED.PLT2.PIC` |
| `THREE-D_PLOT_3.PIC` | `THREED.PLT3.PIC` |
| `MISSILE_HEAD_1.PIC` | `MISSILE.HD1.PIC` |
| `MISSILE_HEAD_2.PIC` | `MISSILE.HD2.PIC` |
| `JULIA_FRACTAL.PIC1` | `JULIA.FRACT.P1` |
| `JULIA_FRACTAL.PIC2` | `JULIA.FRACT.P2` |
| `JULIA_FRACTAL.PIC3` | `JULIA.FRACT.P3` |

The old filenames no longer exist in `data/extracted/`. Do not revert them.

---

## Multi-Pic Naming Convention

The menu BASIC derives pic filenames at runtime from `PRODOS_NAME`:

- **PC=1:** `LEFT$(PN$, 11) + ".PIC"`
- **PC>1:** `LEFT$(PN$, 11) + ".P" + STR$(pic_index)` (e.g. `.P1`, `.P2`, `.P3`)

This means the parent program's `prodos_name` must be chosen so that `LEFT$(name, 11)` is unique across all entries in the same year directory. The Three-D Plot rename (`THREED.PLT1/2/3`) was necessary because `LEFT$("THREE.D.PLT1", 11)` = `"THREE.D.PLO"` collided for all three.

---

## HGR2 Must Come Before BLOAD for Pics

The pic viewer sequence is:
```basic
HGR2
PRINT D$"BLOAD ";PY$;",A$4000"
```

`HGR2` switches display to hi-res page 2 (framebuffer at $4000) **before** loading the image data. If BLOAD runs first, the data loads correctly but the screen shows garbage until `HGR2` clears and switches — causing a visible flash of old screen content.

---

## Fixed-Record Data Files: L=55

The data files use ProDOS fixed-length record I/O with `L=55`. Record content is 54 bytes padded with spaces, followed by one carriage return (`\r`, byte value 13).

Max record content: `9,ABCDEFGHIJKLMNO,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,1,9` = 1+1+15+1+30+1+1+1+1 = 52 chars + 2 padding bytes + `\r` = 55. There is no risk of overflow with current data.

Year is stored as `year - 1983` (range 1–9). Value 0 is used as the end-of-data sentinel in the BASIC DIM/loop logic.

---

## Testing Boot with Jace

Use the Maven invocation, slot 7 (SmartPort), not slot 6 (Disk ][). Slot 6 takes ~600 real seconds to boot ProDOS from a hard disk image.

```bash
cd ~/Documents/code/jace
timeout 120 mvn -q exec:java -Dexec.mainClass="jace.JaceLauncher" -Dexec.args="--terminal" <<'EOF'
bootdisk d1 /path/to/NIBBLE.LIBRARY.po 7
run 10000000
showtext
qq
EOF
```

Expected screen after boot: the MENU program showing "NIBBLE ONE & TWO LINERS / 447 PROGRAMS, 1984-1992".

See `/Users/brobert/Documents/code/jace/CLAUDE.md` for full Jace automation reference.
