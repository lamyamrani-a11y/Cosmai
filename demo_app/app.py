import io, re, math, pathlib, base64
import pandas as pd
import streamlit as st
from rapidfuzz import fuzz, process

import pathlib

APP_DIR  = pathlib.Path(__file__).parent
DATA_DIR = APP_DIR / "data"

CAT_CSV  = DATA_DIR / "sku_catalog.csv"
ROUT_CSV = DATA_DIR / "routine_per_video.csv"
MENT_CSV = DATA_DIR / "mentions.csv"

st.set_page_config(page_title="NLP Cosmetics — Looks for My Kit", layout="wide")

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

# ---------- UI: header ----------
st.markdown("""
<style>
:root{--bg:#0b0d12;--card:#121623;--muted:#8b93a7;--text:#e9edf5;--accent:#7c9cff}
html, body, [class*="css"] { background-color: var(--bg) !important; color: var(--text) !important; }
.block-container { padding-top: 2rem; padding-bottom: 4rem; }
h1, h2, h3 { color: var(--text) !important; }
div[data-testid="stMetricValue"] { color: var(--text); }
.small { font-size: 0.85rem; color: var(--muted); }
.card { padding: 1rem; background: #121623; border: 1px solid #22293b; border-radius: 16px; }
.badge { font-size: 0.8rem; padding: 0.15rem .5rem; border-radius: 999px; background:#1b2030; color:#8b93a7; border:1px solid #2a3146; }
a { color: #7c9cff; text-decoration: none; }
a:hover { text-decoration: underline; }
.hr { height: 1px; background: #2a3146; margin: .75rem 0; }
</style>
""", unsafe_allow_html=True)

st.title("Looks for My Kit — Demo")
st.caption("Upload your kit CSV, match to catalog, and discover tutorials that use your products (with jump-to timestamps).")

# ---------- Load data ----------
@st.cache_data
def load_catalog_and_content():
    assert CAT_CSV.exists(), f"Missing catalog: {CAT_CSV}"
    cat = pd.read_csv(CAT_CSV)

    # normalize catalog fields
    cat["Brand_n"]        = cat["Brand"].map(canon)
    cat["Product Name_n"] = cat["Product Name"].map(canon)
    cat["Product Type_n"] = cat["Product Type"].map(canon)
    cat["Category Group_n"]= cat["Category Group"].map(canon)
    cat["prod_l"]         = (cat["Product Name_n"] + " " + cat["Product Type_n"]).str.lower().map(canon)
    cat["brand_l"]        = cat["Brand_n"].str.lower()

    # choose routine or mentions
    df = None
    source = ""
    if ROUT_CSV.exists():
        df = pd.read_csv(ROUT_CSV)
        source = "routine"
        # normalize
        df["videoId"] = df["videoId"].astype(str)
        df["key"] = df.apply(lambda r: keyify(r.get("brand",""),
                                             r.get("product",""),
                                             r.get("product_type","")), axis=1)
        df["time"] = df.get("time_start", None)
        if "title" not in df.columns: df["title"] = df["videoId"]
        if "step" not in df.columns:  df["step"]  = ""
        df["shade"] = df.get("shade","")
    elif MENT_CSV.exists():
        df = pd.read_csv(MENT_CSV)
        source = "mentions"
        df["videoId"] = df["videoId"].astype(str)
        df["key"] = df.apply(lambda r: keyify(r.get("Brand",""),
                                             r.get("Product Name",""),
                                             r.get("Product Type","")), axis=1)
        df["time"]  = df.get("chunk_start", None)
        if "title" not in df.columns: df["title"] = df["videoId"]
        if "step" not in df.columns:  df["step"]  = ""
        # unify field names for downstream
        df.rename(columns={"Brand":"brand","Product Name":"product","Product Type":"product_type","Shade Name":"shade"}, inplace=True)
    else:
        raise FileNotFoundError("Missing both routine_per_video.csv and mentions.csv in /data")

    return cat, df, source

catalog, content_df, content_source = load_catalog_and_content()

# ---------- Sidebar: kit template + instructions ----------
with st.sidebar:
    st.header("1) Upload your kit")
    st.write("Accepted columns (case-insensitive): **Brand**, **Product Name** (required). Optional: **Product Type**, **Shade Name**.")

    # downloadable template
    tmpl = pd.DataFrame({
        "Brand": ["Urban Decay","Too Faced","KVD Beauty"],
        "Product Name": ["Naked3 Eyeshadow Palette","Better Than Sex Mascara","Tattoo Liner"],
        "Product Type": ["Eyeshadow Palette","Mascara","Liquid Eyeliner"],
        "Shade Name": ["","","Trooper Black"]
    })
    buf = io.StringIO(); tmpl.to_csv(buf, index=False)
    st.download_button("Download CSV template", data=buf.getvalue(), file_name="my_kit_template.csv", mime="text/csv")

    kit_file = st.file_uploader("Drop your kit CSV here", type=["csv"])

# ---------- Match kit to catalog ----------
def find_col(df, names):
    # exact then case-insensitive
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
        raise ValueError("Your CSV must include at least 'Brand' and 'Product Name' columns.")
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
                "Brand": r["Brand_n"], "Product Name": r["Product Name_n"], "Product Type": r["Product Type_n"], "Shade Name": r["Shade Name_n"],
                "Matched Brand": "", "Matched Product Name": "", "Matched Product Type": "", "Matched Category Group": "", "Match Score": 0
            })
    out = pd.DataFrame(rows)
    out["key"] = out.apply(lambda r: keyify(r["Matched Brand"], r["Matched Product Name"], r["Matched Product Type"]), axis=1)
    out_keep = out[out["Match Score"] >= min_score].copy()
    return out, out_keep

# ---------- If kit uploaded, run end-to-end ----------
if kit_file is None:
    st.info("Upload your kit CSV in the sidebar to run the demo.")
    st.stop()

kit_raw = pd.read_csv(kit_file)
matched_all, matched_keep = match_kit_to_catalog(kit_raw, catalog, min_score=st.sidebar.slider("Min match score", 50, 95, 70, 1))

st.subheader("2) Kit → Catalog matching")
c1, c2 = st.columns([2,1])
with c1:
    st.dataframe(matched_keep[["Brand","Product Name","Product Type","Shade Name","Matched Brand","Matched Product Name","Match Score"]])
with c2:
    st.metric("Items recognized", len(matched_keep))
    st.caption("Lower the match threshold in the sidebar if recall is low.")

owned_keys = set(matched_keep["key"])

# ---------- Build intersections with content ----------
df = content_df.copy()
df["sec"] = df["time"].map(to_float)
df["videoId"] = df["videoId"].astype(str)

hits = df[df["key"].isin(owned_keys)].copy()
if hits.empty:
    st.warning("No overlaps between your kit and detected products yet. Try lowering the match threshold or check your catalog coverage.")
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
    agg_rows.append({"videoId": vid, "title": title, "used_items": used, "used_steps": steps, "coverage": round(coverage,3), "score": round(score,3)})
rank = pd.DataFrame(agg_rows).sort_values(["score","used_items"], ascending=[False,False]).reset_index(drop=True)

st.subheader("3) Videos that use your products")
st.caption(f"Data source: **{content_source}**")

# Build mapping of complementary products per video
all_items = df.groupby("videoId").apply(lambda g: g.to_dict("records")).to_dict()

# Cards
for _, R in rank.head(30).iterrows():
    vid = R["videoId"]; title = R["title"]
    st.markdown(f"### {title} &nbsp;&nbsp; [:small_blue_diamond: Open](https://www.youtube.com/watch?v={vid})")
    k1, k2, k3 = st.columns(3)
    k1.metric("Coverage", f"{int(R['coverage']*100)}%")
    k2.metric("Items used", int(R["used_items"]))
    k3.metric("Steps", int(R["used_steps"]))

    # My kit matches (chronological)
    sub = hits[hits["videoId"]==vid].sort_values("sec")
    st.write("**Your kit items in this video**")
    for _, it in sub.iterrows():
        step   = it.get("step","")
        brand  = it.get("brand","")
        prod   = it.get("product","")
        ptype  = it.get("product_type","")
        shade  = it.get("shade","")
        sec    = it.get("sec", None)
        link   = yt_link(vid, sec)
        meta   = " · ".join([x for x in [ptype, f"Shade: {shade}" if shade else ""] if x])
        st.markdown(f"- **{brand} — {prod}**  \n  <span class='small'>{step} {meta}</span> — [Jump {int(sec) if pd.notna(sec) else 'open'}s]({link})", unsafe_allow_html=True)

    # Complementary products = all - owned
    comps = [d for d in all_items.get(vid, []) if d["key"] not in owned_keys]
    if comps:
        st.write("**Complementary products** (others used in this tutorial)")
        # de-dupe per key and keep earliest time
        seen = {}
        for d in sorted(comps, key=lambda x: (x.get("sec") if pd.notna(x.get("sec")) else 9e9)):
            key = d["key"]
            if key in seen: continue
            seen[key] = True
            brand = d.get("brand",""); prod = d.get("product",""); step = d.get("step","")
            ptype = d.get("product_type",""); shade = d.get("shade","")
            link  = yt_link(vid, d.get("sec"))
            meta  = " · ".join([x for x in [ptype, f"Shade: {shade}" if shade else ""] if x])
            st.markdown(f"- **{brand} — {prod}**  \n  <span class='small'>{step} {meta}</span> — [Jump]({link})", unsafe_allow_html=True)

    st.markdown("<div class='hr'></div>", unsafe_allow_html=True)

# ---------- Export: HTML report ----------
def build_html_report(rank_df, hits_df, all_df, owned_keys):
    css = """
    :root{--bg:#0b0d12;--card:#121623;--muted:#8b93a7;--text:#e9edf5;--accent:#7c9cff}
    body{background:var(--bg);color:var(--text);font:14px/1.45 system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px}
    .card{background:#121623;border:1px solid #22293b;border-radius:16px;padding:16px}
    .title{font-weight:600}
    .kpi{display:inline-block;margin-right:8px;font-size:12px;color:#8b93a7;padding:6px 8px;border:1px solid #2a3146;border-radius:10px;background:#0c101a}
    .item{display:flex;justify-content:space-between;gap:8px;padding:8px;border-bottom:1px dashed #2a3146}
    .item:last-child{border-bottom:none}
    a{color:#7c9cff;text-decoration:none}
    a:hover{text-decoration:underline}
    """
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Looks for My Kit</title><style>{css}</style></head><body><h1>Looks for My Kit — matching videos</h1><div class='grid'>"]
    # build mapping of complementary items
    all_map = all_df.groupby("videoId").apply(lambda g: g.to_dict("records")).to_dict()
    for _, R in rank_df.head(50).iterrows():
        vid = str(R["videoId"]); title = str(R["title"])
        parts.append(f"<div class='card'><div class='title'>{title} &nbsp; <a href='https://www.youtube.com/watch?v={vid}' target='_blank'>Open</a></div>"
                     f"<div class='kpi'>Coverage: {int(R['coverage']*100)}%</div>"
                     f"<div class='kpi'>Items used: {int(R['used_items'])}</div>"
                     f"<div class='kpi'>Steps: {int(R['used_steps'])}</div>"
                     f"<div style='margin-top:8px'>")
        # my kit matches
        sub = hits_df[hits_df["videoId"]==vid].sort_values("sec")
        for _, it in sub.iterrows():
            brand  = str(it.get("brand","")); prod = str(it.get("product",""))
            step   = str(it.get("step","")); ptype = str(it.get("product_type","")); shade = str(it.get("shade",""))
            sec    = it.get("sec", None); link = yt_link(vid, sec).replace("&","&amp;"); ttxt = f"{int(sec)}s" if pd.notna(sec) else "open"
            meta   = " · ".join([x for x in [ptype, f"Shade: {shade}" if shade else ""] if x])
            parts.append(f"<div class='item'><div><div><b>{brand} — {prod}</b></div><div style='color:#8b93a7'>{step} {meta}</div></div>"
                         f"<div><a href='{link}' target='_blank'>Jump {ttxt}</a></div></div>")
        # complementary
        comps = [d for d in all_map.get(vid, []) if d['key'] not in owned_keys]
        if comps:
            parts.append("<div style='margin-top:10px;margin-bottom:6px;color:#8b93a7'>Complementary products</div>")
            seen = set()
            for d in sorted(comps, key=lambda x: (x.get('sec') if pd.notna(x.get('sec')) else 9e9)):
                if d["key"] in seen: continue
                seen.add(d["key"])
                brand = str(d.get("brand","")); prod = str(d.get("product","")); step = str(d.get("step",""))
                ptype = str(d.get("product_type","")); shade = str(d.get("shade",""))
                link  = yt_link(vid, d.get("sec")).replace("&","&amp;")
                parts.append(f"<div class='item'><div><div><b>{brand} — {prod}</b></div>"
                             f"<div style='color:#8b93a7'>{step} {ptype} {'· Shade: '+shade if shade else ''}</div></div>"
                             f"<div><a href='{link}' target='_blank'>Jump</a></div></div>")
        parts.append("</div></div>")
    parts.append("</div></body></html>")
    return "\n".join(parts)

st.subheader("4) Export")
html_str = build_html_report(rank, hits, df, owned_keys)
st.download_button("Download HTML report", data=html_str, file_name="report_my_kit_uploaded.html", mime="text/html")
