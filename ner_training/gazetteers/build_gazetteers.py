#!/usr/bin/env python3
# build_gazetteers.py — Generate cosmetics gazetteers from sku_catalog.csv
# Outputs sorted, deduped TSV/TXT files for weak-labeling & NER bootstrapping.

import argparse, csv, re, unicodedata
from pathlib import Path
from collections import defaultdict

import pandas as pd

# -------------------------
# Seeds (edit here, not in the weak labeler)
# -------------------------

BRAND_ALIAS_SEEDS = {
    # existing common aliases
    "CT": ("Charlotte Tilbury", 0.6),
    "Tilbury": ("Charlotte Tilbury", 0.8),
    "ABH": ("Anastasia Beverly Hills", 0.9),
    "Kat Von D": ("KVD Beauty", 1.0),
    "UD": ("Urban Decay", 0.7),
    "RB": ("Rare Beauty", 0.7),
    # fixes from review
    "Bobby Brown": ("Bobbi Brown", 1.0),
    "two-faced": ("Too Faced", 1.0),
}

STEM_STOPWORDS = {
    # keep “shadow stick” as a phrase (see special-case below),
    # so don't list "shadow" or "stick" individually here.
    "the","a","an","by","for","of","and","with","to","in","on","at","all","over","face","skin",
    "powder","foundation","concealer","mascara","eyeliner","liner","brow","blush","bronzer",
    "contour","palette","eyeshadow","spray","mist","setting","lip","oil","pencil",
    "cream","liquid","gel","primer","tint","tinted","moisturizer","highlighter","highlight",
    "pressed","loose","translucent","compact","glow","matte","dewy","waterproof",
    "volumizing","lengthening"
}
STEM_MIN_TOK, STEM_MAX_TOK = 2, 5

TOOL_SEEDS = [
    ("beauty blender", "beauty blender", 1.0),
    ("sponge", "sponge", 0.8),
    ("powder puff", "powder puff", 0.8),
    ("kabuki brush", "kabuki brush", 1.0),
    ("stippling brush", "stippling brush", 1.0),
    ("angled brush", "angled brush", 0.9),
    ("crease brush", "crease brush", 0.9),
    ("blending brush", "blending brush", 0.9),
    ("brow brush", "brow brush", 0.9),
    ("spoolie", "spoolie", 1.0),
    ("eyelash curler", "eyelash curler", 0.9),
]

SHADE_PATTERNS = [
    r"\b(NC|NW)\s*\d{1,3}\b",
    r"\b\d{2,3}[A-Z]?\b",
    r"\b#\s?\d{2,3}\b",
    r"\b\d{1,2}(N|W|C|Y|R)\b",
]

TOOL_PATTERNS = [
    r"\b(M|E)\d{2,4}\b",
    r"\b(217|239|221|224|201)\b",
]

STOP_PHRASES = [
    "a bit of","gonna","i'm going to","like a","sort of","this is","we are going to","you guys"
]

# -------------------------
# Helpers
# -------------------------

def norm(s: str) -> str:
    s = str(s or "").strip()
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s)
    return s

def toks_name(s: str):
    return re.findall(r"[A-Za-z0-9#\-/&']+", norm(s))

def lower(s: str) -> str:
    return norm(s).lower()

def build_stem(product_name: str, brand_tokens: set) -> str:
    """Create a compact stem from product name, preserving 'shadow stick'."""
    tokens = toks_name(product_name)
    # special-case join 'shadow stick' into one unit if seen consecutively
    joined = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if i+1 < len(tokens) and lower(t) == "shadow" and lower(tokens[i+1]) == "stick":
            joined.append("shadow stick")
            i += 2
        else:
            joined.append(t)
            i += 1

    # remove brand tokens (lowercased), and generic stopwords
    out = []
    for t in joined:
        t_l = lower(t)
        if t_l in brand_tokens:             # drop brand words
            continue
        if t_l in STEM_STOPWORDS and t_l != "shadow stick":  # keep 'shadow stick' even if listed (it isn't)
            continue
        out.append(t)

    stem = norm(" ".join(out))
    return stem

def valid_stem(stem: str) -> bool:
    parts = stem.split()
    if not (STEM_MIN_TOK <= len(parts) <= STEM_MAX_TOK):
        return False
    if re.fullmatch(r"[0-9#]+", stem):  # numeric-only
        return False
    return True

# -------------------------
# Main
# -------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True, help="Path to sku_catalog.csv")
    ap.add_argument("--out", default="ner_training/gazetteers", help="Output dir")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.catalog)
    for col in ["Brand","Product Name","Product Type","Category Group","Shade Name"]:
        if col not in df.columns: df[col] = ""
        df[col] = df[col].map(norm)

    # -------- brands.tsv (sorted) --------
    brands = sorted({b for b in df["Brand"].dropna() if b})
    (out/"brands.tsv").write_text("\n".join(brands) + "\n", encoding="utf-8")

    # -------- brand_aliases.tsv (sorted by brand, then alias) --------
    alias_rows = []
    # seed aliases
    for alias, (brand, prio) in BRAND_ALIAS_SEEDS.items():
        alias_rows.append((brand, alias, float(prio)))
    # heuristic: last token of brand as alias if unique
    last_tok = defaultdict(set)
    for b in brands:
        tk = toks_name(b)
        if tk: last_tok[lower(tk[-1])].add(b)
    for lt, bset in last_tok.items():
        if len(bset) == 1 and lt not in {"beauty","cosmetics","makeup"}:
            bname = list(bset)[0]
            alias_rows.append((bname, bname.split()[-1], 0.7))

    # sort & dedup
    alias_rows = sorted({(b,a,prio) for (b,a,prio) in alias_rows}, key=lambda x: (lower(x[0]), lower(x[1])))
    with (out/"brand_aliases.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        for b,a,p in alias_rows:
            w.writerow([a,b,p])

    # -------- products_full.tsv (sorted) --------
    pf = set()
    for _, r in df.iterrows():
        b, pn, pt, cg = r["Brand"], r["Product Name"], r["Product Type"], r["Category Group"]
        if not b or not pn: continue
        pf.add((b,pn,pt,cg))
    pf = sorted(pf, key=lambda x: (lower(x[0]), lower(x[1]), lower(x[2])))
    with (out/"products_full.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        for row in pf: w.writerow(row)

    # -------- products_stems.tsv (sorted) --------
    brand_tok = {b: {lower(t) for t in toks_name(b)} for b in brands}
    stems = set()
    for _, r in df.iterrows():
        b, pn, pt, cg = r["Brand"], r["Product Name"], r["Product Type"], r["Category Group"]
        if not b or not pn: continue
        stem = build_stem(pn, brand_tok.get(b,set()))
        if not stem or not valid_stem(stem): continue
        weight = 0.7 if any(w in lower(stem) for w in ["tinted moisturizer","foundation","powder","palette","lip oil","lip gloss"]) else 1.0
        stems.add((b, stem, pt, cg, weight))
    stems = sorted(stems, key=lambda x: (lower(x[0]), lower(x[1])))
    with (out/"products_stems.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        for row in stems: w.writerow(row)

    # -------- shades_master.tsv (sorted) --------
    def norm_shade(s: str) -> str:
        s = norm(s).lower()
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        return re.sub(r"\s+", " ", s).strip()

    shades = set()
    for _, r in df.iterrows():
        b, pn, sh = r["Brand"], r["Product Name"], r["Shade Name"]
        if not b or not pn or not sh: continue
        shades.add((b, pn, sh, norm_shade(sh)))
    shades = sorted(shades, key=lambda x: (lower(x[0]), lower(x[1]), lower(x[2])))
    with (out/"shades_master.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        for row in shades: w.writerow(row)

    # -------- patterns & lists (sorted) --------
    Path(out/"shade_patterns.txt").write_text("\n".join(sorted(SHADE_PATTERNS)) + "\n", encoding="utf-8")
    Path(out/"tool_patterns.txt").write_text("\n".join(sorted(TOOL_PATTERNS)) + "\n", encoding="utf-8")
    Path(out/"stop_phrases.txt").write_text("\n".join(sorted(set(STOP_PHRASES))) + "\n", encoding="utf-8")

    tools_sorted = sorted({(t,n,w) for (t,n,w) in TOOL_SEEDS}, key=lambda x: (lower(x[0]), x[2], lower(x[1])))
    with (out/"tools.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        for t,n,wg in tools_sorted:
            w.writerow([t,n,wg])

    # -------- Summary --------
    print("✅ Gazetteers written to:", out.resolve())
    print("Counts:")
    print("  brands.tsv           :", len(brands))
    print("  brand_aliases.tsv    :", len(alias_rows))
    print("  products_full.tsv    :", len(pf))
    print("  products_stems.tsv   :", len(stems))
    print("  shades_master.tsv    :", len(shades))
    print("  shade_patterns.txt   :", len(SHADE_PATTERNS))
    print("  tools.tsv            :", len(tools_sorted))
    print("  tool_patterns.txt    :", len(TOOL_PATTERNS))
    print("  stop_phrases.txt     :", len(set(STOP_PHRASES)))

if __name__ == "__main__":
    main()
