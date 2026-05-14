#!/usr/bin/env python3
"""
Phase 4: Build topic categories for Nibble BASIC programs.
Tasks: program descriptions, embeddings, k-means clustering, topic labels.
"""

import json
import os
import re
import sys
import numpy as np
from pathlib import Path
from typing import Optional, Dict, List

WORKSPACE = Path("/tmp/claude/nibble-prodos/iteration-1")
EXTRACTED_TEXT = WORKSPACE / "extracted_text"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def load_json(path):
    with open(path) as f:
        return json.load(f)

def save_json(path, data, indent=2):
    with open(path, "w") as f:
        json.dump(data, f, indent=indent)
    print(f"  Wrote {path}")


def find_bas_file(disk_key: str, prog_name: str) -> Optional[str]:
    """
    Find the .bas file for a program.
    File naming: original name with spaces → underscores, uppercased.
    e.g. 'GRAPH PAPER' → GRAPH_PAPER.bas
    """
    base = EXTRACTED_TEXT / disk_key
    if not base.exists():
        return None

    # Primary: name with spaces→underscores
    candidate = prog_name.replace(" ", "_") + ".bas"
    p = base / candidate
    if p.exists():
        return str(p)

    # Uppercase variant (already uppercase usually, but be safe)
    candidate_up = prog_name.upper().replace(" ", "_") + ".bas"
    p = base / candidate_up
    if p.exists():
        return str(p)

    # Fuzzy: match files that start with the name prefix (handles truncation)
    prefix = prog_name.replace(" ", "_").upper()[:12]
    try:
        for f in base.iterdir():
            if f.name.upper().startswith(prefix) and f.suffix == ".bas":
                return str(f)
    except Exception:
        pass

    return None


def extract_rem_comments(bas_path: str, max_lines: int = 20) -> list:
    """
    Extract REM comment text from first max_lines of a BASIC file.
    Also extract PRINT statements that look like labels/titles.
    """
    rems = []
    try:
        with open(bas_path) as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                stripped = line.strip()
                # Match REM statements: optional line number, whitespace, REM, text
                m = re.match(r'^\s*\d+\s+(?:REM|rem)\s+(.*)', stripped)
                if m:
                    text = m.group(1).strip()
                    # Filter out date-only REMs like "4/20/08"
                    if text and len(text) > 5 and not re.match(r'^\d+/\d+/\d+$', text):
                        rems.append(text)
                # Also grab PRINT statements with quoted strings (program titles)
                pm = re.match(r'^\s*\d+\s+(?:PRINT|HOME\s*:.*PRINT)\s+"([^"]{10,})"', stripped)
                if pm and len(rems) == 0:
                    rems.append(pm.group(1).strip())
    except Exception:
        pass
    return rems


def infer_topic_from_code(bas_path: str) -> str:
    """
    Infer a topic category by scanning BASIC code for characteristic tokens.
    Returns a topic keyword or empty string.
    """
    try:
        with open(bas_path) as f:
            code = f.read(1000).upper()
    except Exception:
        return ""

    # Hi-res graphics: HGR, HPLOT, HCOLOR, HLINE
    hgr_count = code.count("HGR") + code.count("HPLOT") + code.count("HCOLOR")
    # Lo-res graphics: COLOR=, PLOT, GR
    lgr_count = code.count("COLOR=") + code.count(" PLOT ") + code.count(" GR ")
    # Sound: CALL -198, CALL -144, speaker POKE
    sound_count = code.count("CALL -198") + code.count("CALL-198") + code.count("CALL -144")
    # Text / screen manipulation: VTAB, HTAB, PRINT
    text_count = code.count("VTAB") + code.count("HTAB") + code.count("INVERSE") + code.count("FLASH")
    # Game indicators: PEEK(49152), GET, joystick PEEK
    game_count = code.count("PEEK(49152)") + code.count("PEEK( 49152)") + code.count("PEEK(49168)") + code.count("PDL(")
    # Math: SIN, COS, SQR, LOG, ATN
    math_count = code.count("SIN(") + code.count("COS(") + code.count("SQR(") + code.count("LOG(") + code.count(" ATN(")
    # Disk/DOS commands: CHR$(4), D$=, CATALOG, BLOAD, BSAVE
    disk_count = code.count("CHR$(4)") + code.count("CHR$(13)") + code.count("CATALOG") + code.count("BLOAD") + code.count("BSAVE")
    # Animation: page flipping POKE -16300 etc, CALL -198 in loop
    anim_count = code.count("POKE -16300") + code.count("POKE -16301") + code.count("POKE -16302") + code.count("PAGE")

    # Score-based decision
    if game_count >= 2 and game_count > hgr_count:
        return "GAMES"
    if hgr_count >= 3 and anim_count >= 1:
        return "ANIMATION"
    if hgr_count >= 3:
        return "GRAPHICS"
    if lgr_count >= 2 and anim_count >= 1:
        return "ANIMATION"
    if lgr_count >= 2:
        return "GRAPHICS"
    if sound_count >= 1:
        return "AUDIO"
    if disk_count >= 2:
        return "UTILITIES"
    if math_count >= 3:
        return "MATH"
    if text_count >= 3 and hgr_count == 0:
        return "UTILITIES"  # text manipulation utilities

    return ""


def title_case(s: str) -> str:
    """Convert PROGRAM NAME to Program Name."""
    return s.title()


def name_to_description(name: str) -> str:
    """
    Convert a program name like 'LUNAR LANDER' into a semantically useful description.
    Use keyword matching to produce meaningful topic hints rather than generic fallback.
    """
    name_lower = name.lower()
    words = name.replace("-", " ").replace(".", " ").replace("_", " ").split()
    pretty = " ".join(w.capitalize() for w in words)

    # Game keywords
    if any(kw in name_lower for kw in [
        "game", "blackjack", "poker", "chess", "maze", "dungeon", "quest",
        "adventure", "lander", "invader", "asteroid", "snake", "tetris",
        "hangman", "guess", "pinball", "tank", "fighter", "joust", "nim",
        "mine", "treasure", "dragon", "knight", "war", "battle", "race",
        "shoot", "target", "zombie", "stars", "space", "attack", "defender",
        "pac", "frog", "golf", "tennis", "baseball", "football", "bowling",
        "darts", "trivia", "quiz", "tic tac", "tic-tac", "checkers", "slots",
        "dice", "cards", "solitaire", "yahtzee", "craps", "roulette",
        "climb", "jump", "platform", "bounce", "trap", "escape", "rescue",
        "blitz", "blaster", "cannon", "missile", "torpedo", "lunar",
    ]):
        return f"{pretty}: interactive game program for Apple II"

    # Graphics / animation keywords
    if any(kw in name_lower for kw in [
        "graph", "kaleid", "pattern", "square", "circle", "ripple", "spin",
        "rotate", "color", "sine", "wave", "flash", "flicker", "animation",
        "animate", "scroll", "slide", "dissolve", "page flip", "hires",
        "hi-res", "lo-res", "lores", "fractal", "julia", "mandel", "plasma",
        "fireworks", "snow", "star", "galaxy", "spiral", "vortex", "tunnel",
        "3d", "three-d", "perspective", "draw", "sketch", "paint", "art",
        "picture", "image", "scene", "landscape", "portrait", "melt",
        "whirl", "swirl", "bounce ball", "demo", "display", "show",
        "visual", "screen saver",
    ]):
        return f"{pretty}: graphics and visual effects program"

    # Music / audio keywords
    if any(kw in name_lower for kw in [
        "music", "sound", "tone", "beep", "note", "song", "melody", "audio",
        "speaker", "frequency", "pitch", "chord", "scale", "instrument",
        "laser sound", "noise", "musical", "piano", "guitar", "drum",
        "organ", "synthesiz", "jingle",
    ]):
        return f"{pretty}: music and sound program for Apple II"

    # Utility / tool keywords
    if any(kw in name_lower for kw in [
        "util", "tool", "convert", "editor", "format", "backup", "catalog",
        "copy", "delete", "rename", "sort", "search", "find", "list",
        "print", "disk", "file", "directory", "dos", "prodos", "monitor",
        "debug", "patch", "boot", "memory", "loader", "install", "setup",
        "unnew", "renumber", "merge", "append", "extract", "viewer",
        "dump", "sector", "patcher", "fixer", "fix", "repair", "recover",
        "buffer", "cache", "speed", "fast", "quick", "macro",
    ]):
        return f"{pretty}: system utility program for Apple II"

    # Math / calculation keywords
    if any(kw in name_lower for kw in [
        "math", "calc", "number", "count", "statistic", "average",
        "mean", "deviation", "regression", "algebra", "trig", "sine",
        "cosine", "root", "prime", "factor", "equation", "formula",
        "matrix", "hex", "binary", "octal", "roman", "fibonacci",
        "pi ", " pi", "calculator", "base converter", "converter",
        "fraction", "decimal", "percent", "amortiz", "mortgage", "loan",
        "interest", "date", "calendar", "timer", "clock", "counter",
    ]):
        return f"{pretty}: math and calculation program"

    # Education keywords
    if any(kw in name_lower for kw in [
        "learn", "teach", "tutor", "quiz", "test", "lesson", "education",
        "spell", "vocab", "word", "language", "flash card", "drill",
        "practice", "study", "school", "student", "science", "history",
        "geography", "biology", "chemistry", "typing",
    ]):
        return f"{pretty}: educational learning program"

    # Business keywords
    if any(kw in name_lower for kw in [
        "business", "finance", "account", "budget", "expense", "income",
        "tax", "invoice", "inventory", "payroll", "balance", "ledger",
        "record", "database", "data base", "address", "mailing", "phone",
        "contact", "schedule", "appointment", "label", "envelope",
    ]):
        return f"{pretty}: business and productivity program"

    # Text / string processing keywords
    if any(kw in name_lower for kw in [
        "text", "string", "word process", "typing", "encrypt", "cipher",
        "encode", "decode", "compress", "tokenize", "parse", "anagram",
        "palindrome", "scramble", "mirror", "lower", "upper", "case",
        "print", "banner", "label",
    ]):
        return f"{pretty}: text processing program"

    # Instruction / documentation files
    if any(kw in name_lower for kw in [
        "instr", "instruction", "readme", "help", "info", "about",
        "manual", "guide", "doc", "note",
    ]):
        return f"{pretty}: program documentation and instructions file"

    # Picture / image files (non-BASIC data)
    if any(kw in name_lower for kw in [".pic", "pic", "image", "picture", "photo"]):
        return f"{pretty}: hi-res graphics picture file"

    # Default: produce a description based on the raw name words
    # This keeps each program semantically distinct rather than using a shared boilerplate
    return f"{pretty}: Nibble magazine Apple II BASIC program"


# ─────────────────────────────────────────────
# Task 1: Build program descriptions
# ─────────────────────────────────────────────

def build_descriptions():
    print("\n=== Task 1: Building program descriptions ===")

    name_mapping = load_json(WORKSPACE / "name-mapping.json")
    manifest = load_json(WORKSPACE / "enriched-manifest.json")

    # Build manifest lookup: (disk_key, name) -> entry
    manifest_lookup = {}
    for entry in manifest:
        disk_key = f"{entry['disk_year']}_PT{entry['disk_part']}"
        manifest_lookup[(disk_key, entry["name"])] = entry

    programs = []
    stats = {"pdf": 0, "rem": 0, "name_only": 0, "no_bas_file": 0}

    for disk_key, prog_map in name_mapping.items():
        # Parse year from disk_key like "1984_PT1"
        parts = disk_key.split("_")
        year = int(parts[0]) if parts else 0

        for prog_name, prog_data in prog_map.items():
            if not prog_data.get("best", False):
                continue  # skip duplicates

            prodos_name = prog_data.get("prodos_name", prog_name)

            # Check manifest for PDF description
            manifest_entry = manifest_lookup.get((disk_key, prog_name))
            pdf_desc = ""
            pdf_categories = []
            if manifest_entry:
                pdf_desc = manifest_entry.get("description", "").strip()
                pdf_categories = manifest_entry.get("categories", [])

            # Build description
            if pdf_desc:
                description = f"{title_case(prog_name)}: {pdf_desc}"
                desc_source = "pdf"
                stats["pdf"] += 1
            else:
                # Try BASIC source
                bas_file = find_bas_file(disk_key, prog_name)
                if bas_file:
                    rems = extract_rem_comments(bas_file, max_lines=20)
                    code_topic = infer_topic_from_code(bas_file)
                    if rems:
                        rem_text = "; ".join(rems[:3])
                        description = f"{title_case(prog_name)}: {rem_text}"
                        # Augment with code-inferred topic if not already in text
                        if code_topic and code_topic.lower() not in description.lower():
                            description += f" [{code_topic.lower()} program]"
                        desc_source = "rem"
                        stats["rem"] += 1
                    elif code_topic:
                        # Use code analysis to build a meaningful description
                        description = f"{name_to_description(prog_name)} [{code_topic.lower()} program]"
                        desc_source = "code"
                        stats["rem"] += 1  # count as rem-like (code-derived)
                    else:
                        description = name_to_description(prog_name)
                        desc_source = "name_only"
                        stats["name_only"] += 1
                else:
                    description = name_to_description(prog_name)
                    desc_source = "name_only"
                    stats["name_only"] += 1
                    stats["no_bas_file"] += 1

            programs.append({
                "disk_key": disk_key,
                "original_name": prog_name,
                "prodos_name": prodos_name,
                "year": year,
                "description": description,
                "description_source": desc_source,
                "pdf_categories": pdf_categories,
            })

    print(f"  Total canonical programs: {len(programs)}")
    print(f"  Description sources: {stats}")

    save_json(WORKSPACE / "program-descriptions.json", programs)
    return programs


# ─────────────────────────────────────────────
# Task 2: Generate embeddings
# ─────────────────────────────────────────────

def generate_embeddings(programs):
    print("\n=== Task 2: Generating embeddings ===")
    descriptions = [p["description"] for p in programs]

    embeddings = None

    # Try sentence-transformers first
    try:
        print("  Trying sentence-transformers (all-MiniLM-L6-v2)...")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = model.encode(descriptions, show_progress_bar=True)
        print(f"  sentence-transformers embeddings shape: {embeddings.shape}")
        method = "sentence-transformers/all-MiniLM-L6-v2"
    except Exception as e:
        print(f"  sentence-transformers failed: {e}")

    # Try nomic as fallback
    if embeddings is None:
        try:
            print("  Trying nomic embed...")
            import nomic
            from nomic import embed
            result = embed.text(descriptions, model="nomic-embed-text-v1")
            embeddings = np.array(result["embeddings"])
            print(f"  nomic embeddings shape: {embeddings.shape}")
            method = "nomic-embed-text-v1"
        except Exception as e:
            print(f"  nomic failed: {e}")

    # TF-IDF fallback
    if embeddings is None:
        print("  Using TF-IDF fallback...")
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD

        vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 2),
            stop_words="english",
            min_df=1,
        )
        tfidf = vectorizer.fit_transform(descriptions)
        # Reduce to 100 dimensions with LSA/SVD for better clustering
        n_components = min(100, tfidf.shape[1] - 1, len(descriptions) - 1)
        svd = TruncatedSVD(n_components=n_components, random_state=42)
        embeddings = svd.fit_transform(tfidf)
        print(f"  TF-IDF+SVD embeddings shape: {embeddings.shape}")
        method = "tfidf-svd"

    embeddings = np.array(embeddings, dtype=np.float32)
    npy_path = WORKSPACE / "embeddings.npy"
    np.save(str(npy_path), embeddings)
    print(f"  Saved embeddings to {npy_path}")
    print(f"  Embedding method: {method}")
    return embeddings, method


# ─────────────────────────────────────────────
# Task 3: K-means clustering with elbow detection
# ─────────────────────────────────────────────

def cluster_programs(embeddings):
    print("\n=== Task 3: K-means clustering ===")
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    k_values = [5, 8, 10, 12, 15, 18, 20]
    inertias = []
    silhouettes = []

    for k in k_values:
        print(f"  Fitting k={k}...")
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(embeddings)
        inertias.append(float(km.inertia_))
        sil = float(silhouette_score(
            embeddings, labels,
            sample_size=min(500, len(embeddings)),
            random_state=42
        ))
        silhouettes.append(sil)
        print(f"    k={k}: inertia={km.inertia_:.1f}, silhouette={sil:.4f}")

    # Elbow detection: largest drop in inertia
    deltas = [inertias[i] - inertias[i + 1] for i in range(len(inertias) - 1)]
    elbow_idx = deltas.index(max(deltas))
    optimal_k_elbow = k_values[elbow_idx + 1]

    # Also consider best silhouette score
    best_sil_idx = silhouettes.index(max(silhouettes))
    optimal_k_sil = k_values[best_sil_idx]

    # Pick the one that balances both (prefer silhouette if they disagree significantly)
    print(f"\n  Elbow method suggests k={optimal_k_elbow}")
    print(f"  Best silhouette suggests k={optimal_k_sil}")

    # Use silhouette as primary guide but cap at 20
    optimal_k = optimal_k_sil
    print(f"  Selected optimal k={optimal_k} (best silhouette={max(silhouettes):.4f})")

    elbow_data = {
        "k_values": k_values,
        "inertias": inertias,
        "silhouettes": silhouettes,
        "optimal_k_elbow": optimal_k_elbow,
        "optimal_k_silhouette": optimal_k_sil,
        "optimal_k": optimal_k,
        "method": "silhouette_score_maximization",
    }
    save_json(WORKSPACE / "elbow-analysis.json", elbow_data)

    # Final clustering with optimal k
    print(f"\n  Running final clustering with k={optimal_k}...")
    km_final = KMeans(n_clusters=optimal_k, random_state=42, n_init=10)
    labels = km_final.fit_predict(embeddings)
    print(f"  Label distribution: {dict(zip(*np.unique(labels, return_counts=True)))}")

    return km_final, labels, optimal_k


# ─────────────────────────────────────────────
# Task 4: Assign human-readable topic labels
# ─────────────────────────────────────────────

# Keyword-based rules for inferring topic from program names/descriptions
TOPIC_KEYWORDS = {
    "GAMES": [
        "interactive game", "game program", "game for apple",
        "game", "play", "score", "player", "win", "lose", "level", "enemy",
        "shoot", "battle", "war", "chess", "blackjack", "poker", "maze",
        "dungeon", "quest", "adventure", "lander", "space", "asteroid",
        "invader", "pac", "snake", "tetris", "hangman", "guessing",
        "trivia", "quiz", "pinball", "tank", "fighter", "arcade",
        "slots", "dice", "card", "board", "puzzle", "racer", "tic tac",
        "nim", "mines", "treasure", "dragon", "knight",
        "joust", "platformer", "jump", "climb", "bounce",
        "blaster", "cannon", "torpedo", "lunar", "rescue",
        "target", "zombie", "blitz",
    ],
    "GRAPHICS": [
        "graphics and visual", "visual effects",
        "graph paper", "hi-res", "hires", "lo-res", "lores",
        "fractal", "julia", "mandelbrot",
        "draw", "sketch", "paint", "art",
        "pattern generator", "kaleid", "shape",
        "circle", "polygon", "triangle",
        "pixel", "picture", "image",
    ],
    "ANIMATION": [
        "animation", "animate",
        "scroll", "page flip", "page-flip",
        "ripple", "spin", "rotate", "whirl", "swirl",
        "melt", "dissolve", "transition",
        "flicker", "alternate", "flashing",
        "bouncing ball", "walk", "move",
        "rolling", "sliding", "wave",
    ],
    "DEMOS": [
        "demo", "demonstration", "novelty", "show",
        "display", "showcase", "exhibit",
        "color demo", "visual demo", "music demo",
    ],
    "AUDIO": [
        "music", "sound", "tone", "beep", "note", "song", "melody",
        "audio", "speaker", "frequency", "pitch", "chord", "scale",
        "instrument", "keyboard music", "laser sound", "noise",
        "musical", "piano", "guitar", "drum", "organ", "synthesiz",
    ],
    "UTILITIES": [
        "utility", "system utility",
        "disk utility", "file utility",
        "convert", "converter", "editor", "format",
        "backup", "catalog", "copy", "delete", "rename",
        "search", "find", "disk", "file", "directory",
        "dos", "prodos", "monitor", "debug", "patch", "boot",
        "memory", "loader", "install", "setup", "configure",
        "unnew", "renumber", "merge", "append", "extract",
        "viewer", "dump", "patcher", "fixer",
    ],
    "MATH": [
        "math", "calc", "calculat", "number", "numeric", "count",
        "statistic", "average", "mean", "deviation", "regression",
        "algebra", "trigon", "sine", "cosine", "sqrt", "root",
        "prime", "factor", "equation", "formula", "matrix",
        "base converter", "hex converter", "binary", "octal",
        "roman numeral", "fibonacci", "sort algorithm",
        "bubble sort", "quick sort", "pi calculator",
        "fraction", "decimal", "percent",
    ],
    "EDUCATION": [
        "educational", "learning program", "tutor",
        "learn", "teach", "lesson",
        "spell", "vocab", "word", "language",
        "flash card", "drill", "practice", "study", "school",
        "student", "science", "history", "geography", "biology",
        "chemistry", "physics", "typing",
    ],
    "BUSINESS": [
        "business", "finance", "account", "budget", "expense",
        "income", "tax", "invoice", "inventory", "payroll",
        "amortiz", "mortgage", "loan", "interest", "depreci",
        "balance", "ledger", "record", "database", "data base",
        "address", "mailing", "phone", "contact", "schedule",
        "calendar", "appointment", "envelope", "label",
    ],
    "SCIENCE": [
        "science", "physic", "chemical", "biology", "astronomy",
        "planet", "orbit", "gravity", "electric", "circuit",
        "temperature", "weather", "climate", "population",
        "simulation model", "experiment", "lab",
        "genetic", "evolution", "ecology", "halley",
    ],
    "STRINGS": [
        "string", "text processing",
        "word process", "encrypt",
        "cipher", "encode", "decode", "compress", "tokenize",
        "parse", "anagram", "palindrome", "scramble",
        "lower case", "upper case", "text mirror",
    ],
    "DOCS": [
        "documentation", "program documentation", "instructions",
        "instruction", "readme", "help file", "manual",
        "instr", "how to", "guide",
    ],
    "PROGRAMMING": [
        "programming", "basic programming",
        "program tool", "code tool",
        "basic fix", "basic patch",
        "renumber", "unnew", "expression evaluator",
        "data statement", "auto number", "single step",
        "disassembl", "assembl", "machine language",
    ],
}

# Curated topic names to use in the final output
TOPIC_NAMES_ORDER = [
    "GAMES", "GRAPHICS", "ANIMATION", "AUDIO", "UTILITIES",
    "MATH", "EDUCATION", "BUSINESS", "SCIENCE", "STRINGS",
    "DEMOS", "SIMULATION", "PROGRAMMING",
]


def score_description_for_topic(text: str) -> Dict[str, float]:
    """Return keyword hit scores per topic for a description string."""
    text_lower = text.lower()
    scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[topic] = score
    return scores


def infer_topic_from_cluster(cluster_programs_list: List[dict]) -> str:
    """
    Given a list of programs in a cluster, infer the best topic name
    by aggregating keyword scores across all descriptions.
    """
    total_scores: Dict[str, float] = {}
    for prog in cluster_programs_list:
        scores = score_description_for_topic(prog["description"])
        for topic, score in scores.items():
            total_scores[topic] = total_scores.get(topic, 0) + score

    if not total_scores:
        return "MISC"

    return max(total_scores, key=total_scores.get)


# Mapping from internal/raw topic names to clean user-facing labels
TOPIC_NORMALIZE = {
    # Instruction/docs clusters → DOCS (separate from UTILITIES)
    "DOCS": "DOCS",
    "DOCUMENTATION": "DOCS",
    "INSTRUCTIONS": "DOCS",
    "INSTRUCTIONS 2": "DOCS",
    "INSTRUCTIONS 3": "DOCS",
    "INSTRUCTIONS 4": "DOCS",
    "INSTRUCTIONS 5": "DOCS",
    "INSTRUCTIONS 6": "DOCS",
    "INSTRUCTIONS 7": "DOCS",
    "INSTRUCTIONS 8": "DOCS",
    "INSTRUCTIONS 9": "DOCS",
    # Utilities sub-categories
    "MISC": "UTILITIES",
    "GENERAL": "UTILITIES",
    "OTHER": "UTILITIES",
    "TOOLS": "UTILITIES",
    "TEXT TOOLS": "UTILITIES",
    "PROGRAMMING": "UTILITIES",
    "SYSTEM TOOLS": "UTILITIES",
    "PRINT TOOLS": "UTILITIES",
    "DISK TOOLS": "UTILITIES",
    "DISK TOOLS 2": "UTILITIES",
    "DISK TOOLS 3": "UTILITIES",
    "DISK TOOLS 4": "UTILITIES",
    "CONVERTERS": "MATH",
    # Text/strings
    "STRINGS": "TEXT",
    "STRINGS 2": "TEXT",
    # Graphics sub-categories
    "DRAWING": "GRAPHICS",
    "PATTERNS": "GRAPHICS",
    "FRACTALS": "GRAPHICS",
    "HI-RES": "GRAPHICS",
    "LO-RES": "GRAPHICS",
    "DEMOS": "GRAPHICS",
    "ANIMATION": "ANIMATION",
    # Games sub-categories
    "ARCADE": "GAMES",
    "PUZZLES": "GAMES",
    "STRATEGY": "GAMES",
    "ADVENTURE": "GAMES",
    "CARDS": "GAMES",
    "SPORTS": "GAMES",
    # Direct passthrough
    "EDUCATION": "EDUCATION",
    "BUSINESS": "BUSINESS",
    "SCIENCE": "SCIENCE",
    "AUDIO": "AUDIO",
    "MATH": "MATH",
    "GAMES": "GAMES",
    "GRAPHICS": "GRAPHICS",
    "UTILITIES": "UTILITIES",
    "TEXT": "TEXT",
    "DOCS": "DOCS",
}

# Target topic set for the final output (all valid primary topics)
VALID_TOPICS = {
    "GAMES", "GRAPHICS", "ANIMATION", "AUDIO", "UTILITIES",
    "MATH", "EDUCATION", "BUSINESS", "SCIENCE", "TEXT", "DOCS",
}


def normalize_topic_name(topic: str) -> str:
    """Map any raw topic label to a clean, user-facing label."""
    return TOPIC_NORMALIZE.get(topic, topic)


def assign_topics(programs, embeddings, km_model, labels, optimal_k):
    print("\n=== Task 4: Assigning topic labels ===")
    from sklearn.metrics.pairwise import cosine_distances

    centroids = km_model.cluster_centers_
    # Compute all pairwise distances from programs to all centroids
    dists = cosine_distances(embeddings, centroids)  # shape: (N, k)

    # For each cluster, find representative programs (10 nearest to centroid for better analysis)
    cluster_representatives: Dict[int, List[dict]] = {i: [] for i in range(optimal_k)}
    for cluster_id in range(optimal_k):
        in_cluster = [i for i, lbl in enumerate(labels) if lbl == cluster_id]
        if not in_cluster:
            continue
        in_cluster_sorted = sorted(in_cluster, key=lambda i: dists[i, cluster_id])
        for prog_idx in in_cluster_sorted[:10]:
            cluster_representatives[cluster_id].append(programs[prog_idx])

    # For each cluster, gather ALL programs to score topic affinity
    cluster_topics: Dict[int, str] = {}
    for cluster_id in range(optimal_k):
        in_cluster = [i for i, lbl in enumerate(labels) if lbl == cluster_id]
        cluster_progs = [programs[i] for i in in_cluster]

        # Score using all programs in the cluster
        total_scores: Dict[str, float] = {}
        for prog in cluster_progs:
            scores = score_description_for_topic(prog["description"])
            for topic, score in scores.items():
                total_scores[topic] = total_scores.get(topic, 0) + score

        reps = cluster_representatives[cluster_id]
        rep_names = [r["original_name"] for r in reps[:5]]
        if total_scores:
            best_topic = max(total_scores, key=total_scores.get)
        else:
            best_topic = "MISC"
        cluster_topics[cluster_id] = best_topic
        print(f"  Cluster {cluster_id} ({len(cluster_progs)}): {best_topic} "
              f"(scores: {dict(sorted(total_scores.items(), key=lambda x: -x[1])[:3])}) "
              f"| reps: {rep_names}")

    # Resolve duplicates with sub-labeling
    print("\n  Resolving duplicate topic names...")
    cluster_topics = resolve_duplicate_topics(
        cluster_topics, cluster_representatives, programs, embeddings, dists, labels, optimal_k
    )

    for cluster_id in range(optimal_k):
        reps = cluster_representatives[cluster_id]
        rep_names = [r["original_name"] for r in reps[:5]]
        print(f"  Final cluster {cluster_id}: {cluster_topics[cluster_id]} | reps: {rep_names}")

    # Build topic-assignments output
    assignments = []
    for i, prog in enumerate(programs):
        cluster_id = int(labels[i])
        cluster_topic = cluster_topics[cluster_id]

        # For programs with weak semantic signal (name_only or code-inferred),
        # override with keyword-based topic derived directly from name + description.
        # Programs with PDF descriptions or rich REM comments trust the cluster assignment.
        desc_source = prog.get("description_source", "name_only")
        name_scores = score_description_for_topic(prog["description"])

        prog_name_lower = prog["original_name"].lower()
        # Treat as DOCS if the name ends with a documentation suffix
        is_instruction_file = (
            prog_name_lower.endswith(" instr") or
            prog_name_lower.endswith(" instructions") or
            prog_name_lower.endswith(".instr") or
            prog_name_lower.endswith(".inst") or
            prog_name_lower.endswith(" readme") or
            prog_name_lower.endswith(" help") or
            prog_name_lower.endswith(" instructions 2") or
            prog_name_lower.endswith(" instructions 3")
        )

        if is_instruction_file:
            # Instruction files always go to DOCS regardless of other signals
            primary_topic = "DOCS"
        elif desc_source in ("name_only", "code") and name_scores:
            # Use the best keyword match from the description (includes code-inferred tags)
            primary_topic = max(name_scores, key=name_scores.get)
        elif desc_source in ("name_only", "code") and not name_scores:
            # No keyword signal — check code-inferred topic in description brackets
            desc_lower = prog["description"].lower()
            if "[graphics program]" in desc_lower:
                primary_topic = "GRAPHICS"
            elif "[utilities program]" in desc_lower:
                primary_topic = "UTILITIES"
            elif "[games program]" in desc_lower:
                primary_topic = "GAMES"
            elif "[audio program]" in desc_lower:
                primary_topic = "AUDIO"
            else:
                # True unknown — use the cluster but only if it's a real topic
                norm = normalize_topic_name(cluster_topic)
                primary_topic = norm if norm in VALID_TOPICS - {"DOCS"} else "UTILITIES"
        elif desc_source in ("rem", "pdf"):
            # For programs with real content descriptions, use cluster topic
            # but prevent valid programs from being lumped into DOCS
            raw_cluster = cluster_topic
            norm_cluster = normalize_topic_name(raw_cluster)

            if norm_cluster == "DOCS":
                # This program has a real description but the cluster says DOCS.
                # Use keyword scoring to find a better topic.
                if name_scores:
                    # Exclude DOCS from candidates for non-instruction files
                    filtered_scores = {t: s for t, s in name_scores.items() if t != "DOCS"}
                    if filtered_scores:
                        primary_topic = max(filtered_scores, key=filtered_scores.get)
                    elif name_scores:
                        primary_topic = max(name_scores, key=name_scores.get)
                    else:
                        primary_topic = "UTILITIES"  # functional program, default to utilities
                else:
                    # No keyword signal at all — use the program type from description context
                    desc_lower = prog["description"].lower()
                    if any(kw in desc_lower for kw in ["game", "play", "score"]):
                        primary_topic = "GAMES"
                    elif any(kw in desc_lower for kw in ["graphic", "draw", "hires", "color"]):
                        primary_topic = "GRAPHICS"
                    elif any(kw in desc_lower for kw in ["music", "sound", "tone"]):
                        primary_topic = "AUDIO"
                    else:
                        primary_topic = "UTILITIES"
            else:
                primary_topic = norm_cluster
        else:
            primary_topic = cluster_topic

        # Final normalization: map internal scoring labels to user-facing topic names
        primary_topic = normalize_topic_name(primary_topic)

        # For any remaining unknown topics, fall back to UTILITIES
        if primary_topic not in VALID_TOPICS:
            primary_topic = "UTILITIES"

        # Determine secondary topic: second nearest centroid
        dist_row = dists[i]
        sorted_clusters = np.argsort(dist_row)
        primary_dist = dist_row[sorted_clusters[0]]
        secondary_topic = None
        if len(sorted_clusters) > 1:
            second_cluster = sorted_clusters[1]
            second_dist = dist_row[second_cluster]
            # Assign secondary if within 1.3x primary distance
            if second_dist < 1.3 * primary_dist + 1e-9:
                second_name = normalize_topic_name(cluster_topics[second_cluster])
                if second_name != primary_topic:
                    secondary_topic = second_name

        # Merge PDF categories as additional tags
        pdf_cats = [c.upper() for c in prog.get("pdf_categories", [])]
        all_topics = [primary_topic]
        if secondary_topic and secondary_topic not in all_topics:
            all_topics.append(secondary_topic)
        for cat in pdf_cats:
            cat_mapped = map_pdf_category(cat)
            if cat_mapped and cat_mapped not in all_topics:
                all_topics.append(cat_mapped)

        assignments.append({
            "disk_key": prog["disk_key"],
            "original_name": prog["original_name"],
            "prodos_name": prog["prodos_name"],
            "year": prog["year"],
            "best": True,
            "primary_topic": primary_topic,
            "secondary_topic": secondary_topic,
            "all_topics": all_topics,
            "description": prog["description"],
            "cluster_id": cluster_id,
            "description_source": desc_source,
        })

    return assignments, cluster_topics, cluster_representatives


def map_pdf_category(cat: str) -> Optional[str]:
    """Map PDF category strings to our topic vocabulary."""
    cat_lower = cat.lower()
    mapping = {
        "game": "GAMES",
        "games": "GAMES",
        "graphic": "GRAPHICS",
        "graphics": "GRAPHICS",
        "utility": "UTILITIES",
        "utilities": "UTILITIES",
        "math": "MATH",
        "mathematics": "MATH",
        "education": "EDUCATION",
        "business": "BUSINESS",
        "science": "SCIENCE",
        "music": "AUDIO",
        "audio": "AUDIO",
        "sound": "AUDIO",
        "animation": "ANIMATION",
        "novelty": "DEMOS",
        "string": "STRINGS",
        "simulation": "SIMULATION",
        "programming": "PROGRAMMING",
    }
    return mapping.get(cat_lower)


# More refined topic labels for second-pass resolution
CLUSTER_FALLBACK_TOPICS = [
    "GAMES", "GRAPHICS", "ANIMATION", "AUDIO", "UTILITIES",
    "MATH", "EDUCATION", "BUSINESS", "SCIENCE", "STRINGS",
    "DEMOS", "SIMULATION", "PROGRAMMING", "SORTING", "HI-RES",
    "MISC", "TOOLS", "PUZZLES", "STRATEGY", "ARCADE",
]


def resolve_duplicate_topics(
    cluster_topics, cluster_representatives, programs, embeddings, dists, labels, optimal_k
):
    """
    Where multiple clusters got the same topic name, re-examine each
    and try to find more specific labels using all cluster programs.
    """
    from collections import Counter
    name_counts = Counter(cluster_topics.values())
    duplicated = {name for name, cnt in name_counts.items() if cnt > 1}

    if not duplicated:
        return cluster_topics

    # Build cluster-to-programs mapping
    from collections import defaultdict
    cluster_all_progs: Dict[int, List[dict]] = defaultdict(list)
    for i, lbl in enumerate(labels):
        cluster_all_progs[lbl].append(programs[i])

    # Sub-label candidates per parent topic
    # Format: (sub_label, [keywords_in_descriptions])
    sublabels = {
        "GAMES": [
            ("ARCADE",    ["shoot", "invader", "space invader", "asteroid", "laser", "fire", "blaster", "attack"]),
            ("STRATEGY",  ["chess", "strategy", "board game", "card game", "checkers", "nim", "logic"]),
            ("ADVENTURE", ["dungeon", "quest", "adventure", "rpg", "role playing", "escape", "treasure"]),
            ("PUZZLES",   ["puzzle", "maze", "tetris", "logic", "guess", "hangman", "word game", "scramble"]),
            ("SIMULATION",["lander", "simulation", "physics", "model", "orbit", "comet", "robot"]),
            ("SPORTS",    ["sport", "tennis", "baseball", "football", "golf", "bowling", "race", "horse"]),
            ("CARDS",     ["blackjack", "poker", "card", "slots", "dice", "solitaire", "casino", "deal"]),
        ],
        "GRAPHICS": [
            ("FRACTALS",  ["fractal", "julia", "mandelbrot", "recursive", "complex plane"]),
            ("ANIMATION", ["animation", "animate", "scroll", "move", "spin", "rotate", "bounce", "walk",
                           "ripple", "wave", "melt", "dissolve", "flicker", "flash"]),
            ("DRAWING",   ["draw", "sketch", "paint", "editor", "cursor", "pixel", "brush"]),
            ("HI-RES",    ["hi-res", "hires", "hgr", "high resolution", "picture", "image"]),
            ("LO-RES",    ["lo-res", "lores", "low resolution", "color block", "lo res"]),
            ("PATTERNS",  ["pattern", "kaleid", "geometric", "shape", "tile", "mosaic"]),
            ("DEMOS",     ["demo", "visual effects", "color effects", "display", "show"]),
        ],
        "UTILITIES": [
            ("DISK TOOLS",    ["disk", "file", "catalog", "copy", "backup", "sector", "directory", "dos", "prodos"]),
            ("PROGRAMMING",   ["basic", "debug", "monitor", "disassembl", "assembl", "machine language",
                               "renumber", "unnew", "expression", "data statement", "auto number"]),
            ("PRINT TOOLS",   ["print", "printer", "dump", "label", "envelope", "format"]),
            ("TEXT TOOLS",    ["text", "word", "string", "format", "editor", "notepad", "typing"]),
            ("CONVERTERS",    ["convert", "converter", "hex", "binary", "base", "decimal", "octal"]),
            ("SYSTEM TOOLS",  ["memory", "patch", "poke", "call", "rom", "boot", "setup", "config"]),
        ],
        "DOCS": [
            ("INSTRUCTIONS",  ["instruction", "instr", "how to", "readme", "manual", "guide", "help"]),
        ],
        "MISC": [
            ("GAMES",     ["game", "play", "score", "player"]),
            ("GRAPHICS",  ["graphic", "draw", "color", "screen", "display"]),
            ("UTILITIES", ["utility", "tool", "convert", "disk", "file"]),
            ("AUDIO",     ["music", "sound", "tone", "beep", "note"]),
        ],
    }

    for dup_name in duplicated:
        dup_clusters = [cid for cid, name in cluster_topics.items() if name == dup_name]
        candidates = sublabels.get(dup_name, [])

        for cid in dup_clusters:
            all_progs = cluster_all_progs[cid]
            all_text = " ".join(p["description"].lower() for p in all_progs)

            best_sub = None
            best_score = 0
            for sub_name, sub_keys in candidates:
                score = sum(1 for kw in sub_keys if kw in all_text)
                if score > best_score:
                    best_score = score
                    best_sub = sub_name

            if best_sub and best_score > 0:
                cluster_topics[cid] = best_sub

    # Final pass: if still duplicated after sub-labeling, append ordinal
    name_counts2 = Counter(cluster_topics.values())
    duplicated2 = {name for name, cnt in name_counts2.items() if cnt > 1}
    seq_tracker: Dict[str, int] = {}
    for cid in sorted(cluster_topics.keys()):
        name = cluster_topics[cid]
        if name in duplicated2:
            seq_tracker[name] = seq_tracker.get(name, 0) + 1
            if seq_tracker[name] > 1:
                # Try to pick a better generic label before numbering
                ordinal_map = {
                    "MISC": ["TOOLS", "GENERAL", "OTHER"],
                    "GAMES": ["ENTERTAINMENT", "ARCADE", "LEISURE"],
                    "GRAPHICS": ["VISUAL", "IMAGES", "COLOR"],
                }
                alts = ordinal_map.get(name, [])
                alt_idx = seq_tracker[name] - 2
                if alt_idx < len(alts):
                    cluster_topics[cid] = alts[alt_idx]
                else:
                    cluster_topics[cid] = f"{name} {seq_tracker[name]}"

    return cluster_topics


# ─────────────────────────────────────────────
# Task 5: Write output files
# ─────────────────────────────────────────────

def write_output_files(assignments, cluster_topics, cluster_representatives, optimal_k):
    print("\n=== Task 5: Writing output files ===")

    # topic-assignments.json
    save_json(WORKSPACE / "topic-assignments.json", assignments)

    # topic-labels.json — build from the actual normalized primary topics in assignments
    from collections import Counter, defaultdict

    # Group assignments by normalized primary_topic
    topic_to_progs: Dict[str, List[dict]] = defaultdict(list)
    for a in assignments:
        topic_to_progs[a["primary_topic"]].append(a)

    topics_list = []
    for topic_name in sorted(VALID_TOPICS):
        progs_in_topic = topic_to_progs.get(topic_name, [])
        # Find representative programs: prefer those with pdf/rem descriptions
        reps = sorted(progs_in_topic, key=lambda x: (
            0 if x.get("description_source") == "pdf" else
            1 if x.get("description_source") == "rem" else 2
        ))[:5]
        rep_names = [r["original_name"] for r in reps]
        topics_list.append({
            "id": len(topics_list),
            "name": topic_name,
            "description": describe_topic(topic_name),
            "representative_programs": rep_names,
            "program_count": len(progs_in_topic),
        })

    topic_labels = {
        "k": optimal_k,
        "topics": topics_list,
    }
    save_json(WORKSPACE / "topic-labels.json", topic_labels)

    # Print distribution summary
    print("\n  Primary topic distribution:")
    total = len(assignments)
    for t in topics_list:
        pct = t["program_count"] / total * 100
        bar = "#" * int(pct / 2)
        print(f"    {t['name']:12s}: {t['program_count']:4d} ({pct:5.1f}%) {bar}")
    print(f"  Total: {total}")
    if topics_list:
        max_pct = max(t["program_count"] for t in topics_list) / total * 100
        print(f"  Max single topic: {max_pct:.1f}% (limit: 40%)")
        if max_pct > 40:
            print("  WARNING: Max topic exceeds 40% limit!")


def describe_topic(name: str) -> str:
    descs = {
        "GAMES": "Interactive games, puzzles, and entertainment programs",
        "GRAPHICS": "Graphics, drawing, hi-res/lo-res visual programs, and fractals",
        "ANIMATION": "Animation, scrolling, and moving visual effects",
        "AUDIO": "Music, sound effects, and audio tools",
        "UTILITIES": "System utilities, disk tools, programming aids, and converters",
        "MATH": "Mathematics, calculation, number conversion, and financial programs",
        "EDUCATION": "Educational and learning programs",
        "BUSINESS": "Business, accounting, and productivity programs",
        "SCIENCE": "Science and simulation programs",
        "TEXT": "Text processing, string manipulation, and word tools",
        "DOCS": "Program documentation, instructions, and readme files",
    }
    return descs.get(name, f"{name} programs")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    print("=== Phase 4: Building topic categories for Nibble BASIC programs ===")

    # Task 1
    programs = build_descriptions()

    # Task 2
    embeddings, embedding_method = generate_embeddings(programs)

    # Task 3
    km_model, labels, optimal_k = cluster_programs(embeddings)

    # Task 4
    assignments, cluster_topics, cluster_reps = assign_topics(
        programs, embeddings, km_model, labels, optimal_k
    )

    # Task 5
    write_output_files(assignments, cluster_topics, cluster_reps, optimal_k)

    print("\n=== Phase 4 complete ===")
    print(f"  Embedding method used: {embedding_method}")
    print(f"  Optimal k: {optimal_k}")
    print(f"  Programs processed: {len(programs)}")
    print(f"  Output files written to {WORKSPACE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
