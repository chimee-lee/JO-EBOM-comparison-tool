import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="BOM Comparison Tool", layout="wide")

st.title("🔍 BOM Comparison Tool")
st.markdown("Upload the **Job Order (JO)** and **Engineer BOM (EBOM)** to compare components side by side.")

def load_jo(file) -> pd.DataFrame:
    df = pd.read_excel(file, sheet_name=0)
    df = df[df["Component"].notna()]
    df = df[~df["Component Desc"].astype(str).str.contains("ANY ENGINEERING JOB", case=False, na=False)]
    keep = ["Component", "Rev", "Component Desc", "PO UOM", "JO Req Qty"]
    df = df[keep].copy()
    df.rename(columns={
        "Component":      "Item Code",
        "Component Desc": "JO Description",
        "PO UOM":         "JO UOM",
        "JO Req Qty":     "JO Qty",
        "Rev":            "JO Rev",
    }, inplace=True)
    df["Item Code"] = df["Item Code"].astype(str).str.strip()
    df["JO Rev"]    = df["JO Rev"].astype(str).str.strip().replace("nan", "")
    return df.reset_index(drop=True)

def load_ebom(file) -> pd.DataFrame:
    raw = pd.read_excel(file, sheet_name="BOM", header=None)
    header_row = None
    for i, row in raw.iterrows():
        if "Item Code" in row.values and "Component Part Description" in row.values:
            header_row = i
            break
    if header_row is None:
        st.error("Could not find the component table in the EBOM file.")
        return pd.DataFrame()
    df = pd.read_excel(file, sheet_name="BOM", header=header_row)
    keep = ["Item Code", "Rev", "Component Part Description", "UOM", "Qty"]
    df = df[keep].copy()
    df = df[df["Item Code"].notna()]
    df = df[df["Item Code"].astype(str).str.lower() != "item code"]
    df.rename(columns={
        "Component Part Description": "EBOM Description",
        "UOM":                        "EBOM UOM",
        "Qty":                        "EBOM Qty",
        "Rev":                        "EBOM Rev",
    }, inplace=True)
    df["Item Code"] = df["Item Code"].astype(str).str.strip()
    df["EBOM Rev"]  = df["EBOM Rev"].astype(str).str.strip().replace("nan", "")
    return df.reset_index(drop=True)

def compare(jo: pd.DataFrame, ebom: pd.DataFrame) -> pd.DataFrame:
    merged = pd.merge(jo, ebom, on="Item Code", how="outer", indicator=True)

    def flag(row):
        issues = []
        if row["_merge"] == "left_only":
            issues.append("Missing in EBOM")
        elif row["_merge"] == "right_only":
            issues.append("Missing in JO")
        else:
            jo_rev   = str(row.get("JO Rev", "")).strip()
            ebom_rev = str(row.get("EBOM Rev", "")).strip()
            if jo_rev and ebom_rev and jo_rev != ebom_rev:
                issues.append("Rev mismatch")
            jo_uom   = str(row.get("JO UOM", "")).strip().upper()
            ebom_uom = str(row.get("EBOM UOM", "")).strip().upper()
            if jo_uom and ebom_uom and jo_uom != ebom_uom:
                issues.append("UOM mismatch")
            try:
                jo_qty   = float(row.get("JO Qty", 0) or 0)
                ebom_qty = float(row.get("EBOM Qty", 0) or 0)
                if jo_qty != ebom_qty:
                    issues.append("Qty mismatch")
            except (ValueError, TypeError):
                issues.append("Qty mismatch")
        return ", ".join(issues) if issues else "✅ Match"

    merged["Status"] = merged.apply(flag, axis=1)
    merged.drop(columns=["_merge"], inplace=True)
    cols = [
        "Item Code",
        "JO Rev", "EBOM Rev",
        "JO Description", "EBOM Description",
        "JO UOM", "EBOM UOM",
        "JO Qty", "EBOM Qty",
        "Status",
    ]
    merged = merged[[c for c in cols if c in merged.columns]]
    return merged.reset_index(drop=True)

def style_table(df: pd.DataFrame):
    def row_style(row):
        s = row["Status"]
        if s == "✅ Match":
            color = "#d4edda"
        elif "Missing" in s:
            color = "#f8d7da"
        else:
            color = "#fff3cd"
        return [f"background-color: {color}"] * len(row)
    return df.style.apply(row_style, axis=1)

col1, col2 = st.columns(2)
with col1:
    jo_file = st.file_uploader("📋 Upload Job Order (JO)", type=["xlsx"])
with col2:
    ebom_file = st.file_uploader("📐 Upload Engineer BOM (EBOM)", type=["xlsx"])

if jo_file and ebom_file:
    with st.spinner("Parsing files…"):
        jo   = load_jo(jo_file)
        ebom = load_ebom(ebom_file)

    if jo.empty or ebom.empty:
        st.stop()

    result = compare(jo, ebom)

    total      = len(result)
    matches    = (result["Status"] == "✅ Match").sum()
    missing    = result["Status"].str.contains("Missing").sum()
    mismatches = total - matches - missing

    st.markdown("---")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Items",   total)
    m2.metric("✅ Matches",    matches)
    m3.metric("⚠️ Mismatches", mismatches)
    m4.metric("❌ Missing",    missing)

    st.markdown("### Filter")
    filter_opts = ["All", "Mismatches only", "Missing items only", "Matches only"]
    choice = st.radio("Show:", filter_opts, horizontal=True)

    if choice == "Mismatches only":
        view = result[~result["Status"].isin(["✅ Match"]) & ~result["Status"].str.contains("Missing")]
    elif choice == "Missing items only":
        view = result[result["Status"].str.contains("Missing")]
    elif choice == "Matches only":
        view = result[result["Status"] == "✅ Match"]
    else:
        view = result

    st.markdown(f"**Showing {len(view)} of {total} rows**")
    st.dataframe(style_table(view), use_container_width=True, height=520)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        result.to_excel(writer, index=False, sheet_name="BOM Comparison")
        issues = result[result["Status"] != "✅ Match"]
        if not issues.empty:
            issues.to_excel(writer, index=False, sheet_name="Discrepancies")
    buf.seek(0)

    st.download_button(
        label="⬇️ Download Full Comparison (.xlsx)",
        data=buf,
        file_name="BOM_Comparison_Result.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

else:
    st.info("👆 Please upload both files above to begin the comparison.")
    with st.expander("ℹ️ Column mapping used"):
        st.markdown("""
| JO File | EBOM File |
|---|---|
| Component | Item Code |
| Rev | Rev |
| Component Desc | Component Part Description |
| PO UOM | UOM |
| JO Req Qty | Qty |
        """)
