# app.py — NLP Cosmetics "Looks for My Kit" (Streamlit demo)
# Folder layout:
# demo_app/
#   app.py
#   data/
#     sku_catalog.csv
#     routine_per_video.csv    (or mentions.csv)
#
# Repo root must have requirements.txt with:
# streamlit==1.36.0
# pandas==2.2.2
# rapidfuzz==3.9.6

import io, re, math, pathlib
import pandas as pd
import streamlit as st

# --- RapidFuzz (self-heal if missing on the cloud) ---
try:
    from rapidfuzz import fuzz, process
except Exception:
    import sys, subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rapidfuzz==3.9.6"])
    from rapidfuzz import fuzz, process

# ---------- Paths ----------
APP_DIR  = pathlib.Path(__file__).parent
DATA_DIR = APP_DIR / "data"
CAT_CSV  = DATA_DIR / "sku_catalog.csv"
ROUT_CSV = DATA_DIR / "routine_per_video.csv"
MENT_CSV = DATA_DIR / "mentions.csv"

st.set_page_config(page_title="NLP Cosmetics — Looks for My Kit", layout="wide")

# ---------- Styles ----------
st.markdown("""
<style>
:root{--bg:#0b0d12;--card:#121623;--muted:#8b93a7;--text:#e9edf5;--accent:#7c9cff}
html, body, [class*="css"] { background-color: var(--bg) !important; color: var(--text) !important; }
.block-container { padding-top: 2rem; padding-bottom: 4rem; }
a { color: #7c9cff; text-decoration: none; }
a:hover { text-decoration: underline; }
.small { font-size: 0.85rem; color: var(--muted); }

/* Section title (pink/purple), video titles keep default color */
.section-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #d47ad4;
  margin: .25rem 0 .5rem 0;
}

/* Complementary products box — red left border */
.comps {
  border-left: 3px solid #ff4d4d;
  padding-left: 0.6rem;
  margin-top: 0.6rem;
}

/* Lighten Streamlit container borders and card feel */
div[data-testid="stVerticalBlock"] > div[style*="border: 1px solid rgba(49, 51, 63, 0.2)"] {
  border-color: #2f3547 !important;     /* light gray */
  border-radius: 16px !important;
  background: #121623 !important;
  padding: 16px !important;
}
</style>
""", unsafe_allow_html=True)

# ---------- Helpers ----------
def canon(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()

def keyify(brand, pname, ptype=""):
    return (str(brand or "") + "|" + str(pname or "") + "|" + str(ptype or "")).strip().lower()

def to_float(x):
    try: return float(x)
    except: return math.nan

def yt_link(vid, t):
    try:
        sec = int(float(t))
        return f"https://www.youtube.com/watch?v={vid}&t={sec}s"
    except Exception:
        return f"https://www.youtube.com/watch?v={vid}"

def section(title: str):
    st.markdown(f"<div class='section-title'>{title}</div>", unsafe_allow_html=True)

# ---------- Load data ----------
@st.cache_data
def load_catalog_and_content():
    assert CAT_CSV.exists(), f"Missing catalog: {CAT_CSV}"
    cat = pd.read_csv(CAT_CSV)

    # normalize catalog fields
    cat["Brand_n"]         = cat["Brand"].map(canon)
    cat["Product Name_n"]  = cat["Product Name"].map(canon)
    cat["Product Type_n"]  = cat["Product Type"].map(canon)
    cat["Category Group_n"]= cat["Category Group"].map(canon)
    cat["prod_l"]          = (cat["Product Name_n"] + " " + cat["Product Type_n"]).str.lower().map(canon)
    cat["brand_l"]         = cat["Brand_n"].str.lower()

    # choose routine or mentions
    if ROUT_CSV.exists():
        df = pd.read_csv(ROUT_CSV)
        source = "routine"
        df["videoId"] = df["videoId"].astype(str)
        df["key"] = df.apply(lambda r: keyify(r.get("brand",""),
                                             r.get("product",""),
                                             r.get("product_type","")), axis=1)
        df["time"] = df.get("time_start", None)
        if "title" not in df.columns: df["title"] = df["videoId"]
        if "step"  not in df.columns: df["step"]  = ""
        if "shade" not in df.columns: df["shade"] = ""
    elif MENT_CSV.exists():
        df = pd.read_csv(MENT_CSV)
        source = "mentions"
        df["videoId"] = df["videoId"].astype(str)
        df["key"]  = df.apply(lambda r: keyify(r.get("Brand",""),
                                              r.get("Product Name",""),
                                              r.get("Product Type","")), axis=1)
        df["time"] = df.get("chunk_start", None)
        if "title" not in df.columns: df["title"] = df["videoId"]
        if "step"  not in df.columns: df["step"]  = ""
        df.rename(columns={"Brand":"brand","Product Name":"product",
                           "Product Type":"product_type","Shade Name":"shade"}, inplace=True)
    else:
        raise FileNotFoundError("Missing both routine_per_video.csv and mentions.csv in /data")

    return cat, df, source

catalog, content_df, content_source = load_catalog_and_content()

# ---------- Sidebar: upload user's kit ----------
st.title("Looks for My Kit — Demo")
st.caption("Upload your kit CSV, match to catalog, and discover tutorials that use your products with jump-to timestamps.")

with st.sidebar:
    section("1) Upload your kit")
    st.write("CSV columns (case-insensitive): **Brand**, **Product Name** (required). Optional: **Product Type**, **Shade Name**.")
    # downloadable template
    tmpl = pd.DataFrame({
        "Brand": ["Urban Decay","Too Faced","KVD Beauty"],
        "Product Name": ["Naked3 Eyeshadow Palette","Better Than Sex Masacra","Tattoo Liner"],
        "Product Type": ["Eyeshadow Palette","Mascara","Liquid Eyeliner"],
        "Shade Name": ["","","Trooper Black"]
    })
    buf = io.StringIO(); tmpl.to_csv(buf, index=False)
    st.download_button("Download CSV template", data=buf.getvalue(),
                       file_name="my_kit_template.csv", mime="text/csv")
    kit_file = st.file_uploader("Drop your kit CSV here", type=["csv"])
    min_score = st.slider("Min match score", 50, 95, 70, 1)

# ---------- Kit → Catalog matching ----------
def find_col(df, names):
    # exact, then case-insensitive
    for n in names:
        if n in df.columns: return n
    low = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in low: return low[n.lower()]
    return None

def match_kit_to_catalog(kit_raw: pd.DataFrame, cat: pd.DataFrame, min_score=70):
    bcol = find_col(kit_raw, ["Brand"])
    pcol = find_col(kit_raw, ["Product Name","Product"])
    tcol = find_col(kit_raw, ["Product Type","Type"])
    scol = find_col(kit_raw, ["Shade Name","Shade"])
    if not bcol or not pcol:
        raise ValueError("Your CSV must include 'Brand' and 'Product Name' columns.")

    kit = kit_raw.copy()
    kit["Brand_n"]        = kit[bcol].map(canon)
    kit["Product Name_n"] = kit[pcol].map(canon)
    kit["Product Type_n"] = kit[tcol].map(canon) if tcol else ""
    kit["Shade Name_n"]   = kit[scol].map(canon) if scol else ""
    kit["query_l"]        = (kit["Product Name_n"] + " " + kit["Product Type_n"]).str.lower().map(canon)
    kit["brand_l"]        = kit["Brand_n"].str.lower()

    rows = []
    for _, r in kit.iterrows():
        pool = cat[cat["brand_l"] == r["brand_l"]]
        if pool.empty:
            pool = cat
        res = process.extractOne(r["query_l"], pool["prod_l"].tolist(), scorer=fuzz.token_set_ratio)
        if res:
            matched, score = res[0], int(res[1])
            crow = pool[pool["prod_l"] == matched].iloc[0]
            rows.append({
                "Brand": r["Brand_n"],
                "Product Name": r["Product Name_n"],
                "Product Type": r["Product Type_n"],
                "Shade Name": r["Shade Name_n"],
                "Matched Brand": crow["Brand_n"],
                "Matched Product Name": crow["Product Name_n"],
                "Matched Product Type": crow["Product Type_n"],
                "Matched Category Group": crow["Category Group_n"],
                "Match Score": score
            })
        else:
            rows.append({
                "Brand": r["Brand_n"], "Product Name": r["Product Name_n"],
                "Product Type": r["Product Type_n"], "Shade Name": r["Shade Name_n"],
                "Matched Brand": "", "Matched Product Name": "",
                "Matched Product Type": "", "Matched Category Group": "",
                "Match Score": 0
            })
    out = pd.DataFrame(rows)
    out["key"] = out.apply(lambda r: keyify(r["Matched Brand"], r["Matched Product Name"], r["Matched Product Type"]), axis=1)
    out_keep = out[out["Match Score"] >= min_score].copy()
    return out, out_keep

if kit_file is None:
    section("2) Kit → Catalog matching")
    st.info("Upload your kit CSV in the sidebar to run the demo.")
    st.stop()

kit_raw = pd.read_csv(kit_file)
matched_all, matched_keep = match_kit_to_catalog(kit_raw, catalog, min_score=min_score)

with st.expander("2) Kit → Catalog matching", expanded=True):
    c1, c2 = st.columns([2,1])
    with c1:
        st.dataframe(matched_keep[["Brand","Product Name","Product Type","Shade Name",
                                   "Matched Brand","Matched Product Name","Match Score"]])
    with c2:
        st.metric("Items recognized", len(matched_keep))
        st.caption("Tip: adjust the match score in the sidebar if recall is low.")

owned_keys = set(matched_keep["key"])

# ---------- Intersections with content ----------
df = content_df.copy()
df["sec"] = df["time"].map(to_float)
df["videoId"] = df["videoId"].astype(str)

hits = df[df["key"].isin(owned_keys)].copy()
if hits.empty:
    section("3) Videos that use your products")
    st.caption(f"Data source: {content_source}")
    st.warning("No overlaps between your kit and detected products yet. Try lowering the match score or expanding catalog coverage.")
    st.stop()

# Rank videos
agg_rows = []
for vid, g in hits.groupby("videoId", sort=False):
    title = g["title"].iloc[0]
    used  = g["key"].nunique()
    steps = g.get("step","").nunique() if "step" in g.columns else used
    coverage = used / max(1, len(owned_keys))
    early = g["sec"].dropna()
    early_boost = 1.15 if (not early.empty and early.median() < 600) else 1.0
    score = (0.7*coverage + 0.3*(steps/10)) * early_boost
    agg_rows.append({"videoId": vid, "title": title, "used_items": used, "used_steps": steps,
                     "coverage": round(coverage,3), "score": round(score,3)})

rank = pd.DataFrame(agg_rows).sort_values(["score","used_items"], ascending=[False,False]).reset_index(drop=True)

# Map: videoId -> all items (for complementary products)
all_items = df.groupby("videoId").apply(lambda g: g.to_dict("records")).to_dict()

# Render helper (no Ellipsis)
def render_item_line(vid, step, brand, prod, ptype, shade, sec):
    step  = str(step or ""); brand = str(brand or ""); prod = str(prod or "")
    ptype = str(ptype or ""); shade = str(shade or "")
    try:
        tsec = int(float(sec)); ttxt = f"{tsec}s"; link = yt_link(vid, tsec)
    except Exception:
        ttxt = "open"; link = yt_link(vid, None)
    meta = " · ".join([x for x in [ptype, f"Shade: {shade}" if shade else ""] if x])
    st.markdown(
        f"- **{brand} — {prod}**  \n"
        f"  <span class='small'>{step} {meta}</span> — "
        f"[Jump {ttxt}]({link})",
        unsafe_allow_html=True
    )

# ---------- Video grid (2 tiles per row) ----------
section("3) Videos that use your products")
st.caption(f"Data source: {content_source}")

videos = rank.head(30).to_dict("records")
for i in range(0, len(videos), 2):
    cols = st.columns(2)
    for col, R in zip(cols, videos[i:i+2]):
        with col:
            with st.container(border=True):  # true tile wrapping everything
                vid   = R["videoId"]
                title = R["title"]

                st.markdown(
                    f"### {title} &nbsp; "
                    f"[🔹 Open](https://www.youtube.com/watch?v={vid})",
                    unsafe_allow_html=True
                )

                k1, k2, k3 = st.columns(3)
                k1.metric("Coverage", f"{int(R['coverage']*100)}%")
                k2.metric("Items used", int(R["used_items"]))
                k3.metric("Steps", int(R["used_steps"]))

                # Your kit matches (chronological)
                st.write("**Your kit items in this video**")
                sub = hits[hits["videoId"] == vid].sort_values("sec")
                if sub.empty:
                    st.caption("No kit items detected in this video.")
                else:
                    for _, it in sub.iterrows():
                        render_item_line(
                            vid=vid,
                            step  = it.get("step",""),
                            brand = it.get("brand",""),
                            prod  = it.get("product",""),
                            ptype = it.get("product_type",""),
                            shade = it.get("shade",""),
                            sec   = it.get("sec", None),
                        )

                # Complementary products (red left border + de-duped)
                comps = [d for d in all_items.get(vid, []) if d["key"] not in owned_keys]
                if comps:
                    st.markdown("<div class='comps'>**Complementary products**</div>", unsafe_allow_html=True)
                    seen = set()
                    for d in sorted(comps, key=lambda x: (x.get("sec") if pd.notna(x.get("sec")) else 9e9)):
                        if d["key"] in seen: 
                            continue
                        seen.add(d["key"])
                        render_item_line(
                            vid=vid,
                            step  = d.get("step",""),
                            brand = d.get("brand",""),
                            prod  = d.get("product",""),
                            ptype = d.get("product_type",""),
                            shade = d.get("shade",""),
                            sec   = d.get("sec", None),
                        )
