from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from statement_parser import ParseResult, parse_pdf_statement, results_to_dataframe


st.set_page_config(page_title="Card Statement Analyzer", layout="wide")


def main() -> None:
    st.title("Card Statement Analyzer")
    st.caption("Upload bank statement PDFs, extract line items, categorize spend, and flag large charges.")

    with st.sidebar:
        st.header("Import")
        files = st.file_uploader(
            "Statement PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            help="Files are processed in memory and are not stored by this app.",
        )
        threshold = st.number_input("Big item threshold", min_value=0.0, value=500.0, step=50.0)
        allow_ocr = st.toggle("Try OCR when no text is found", value=True)
        st.caption("OCR requires the host to have OCR dependencies installed.")

        passwords: dict[str, str] = {}
        if files:
            with st.expander("PDF passwords"):
                for file in files:
                    passwords[file.name] = st.text_input(file.name, type="password")

        analyze = st.button("Analyze files", type="primary", use_container_width=True)

    if analyze and files:
        st.session_state["results"] = process_files(files, passwords, threshold, allow_ocr)

    results: list[ParseResult] = st.session_state.get("results", [])
    df = results_to_dataframe(results)
    show_warnings(results)
    show_dashboard(df)


def process_files(files: list, passwords: dict[str, str], threshold: float, allow_ocr: bool) -> list[ParseResult]:
    results: list[ParseResult] = []
    progress = st.progress(0, text="Processing statements")
    for index, file in enumerate(files, start=1):
        progress.progress((index - 1) / len(files), text=f"Processing {file.name}")
        password = passwords.get(file.name) or None
        results.append(parse_pdf_statement(file.name, file.getvalue(), password, threshold, allow_ocr))
    progress.progress(1.0, text="Done")
    progress.empty()
    return results


def show_warnings(results: list[ParseResult]) -> None:
    for result in results:
        if not result.transactions:
            st.error(f"{result.filename}: no transactions extracted.")
        for warning in result.warnings:
            st.warning(f"{result.filename}: {warning}")
        if result.safety_ok is False:
            st.error(f"{result.filename}: safety check failed.")


def show_dashboard(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Upload one or more statement PDFs and click Analyze files.")
        return

    charges = df[df["amount"] > 0]
    credits = df[df["amount"] < 0]
    big_items = df[df["flag"] == "Big item"]

    metric_cols = st.columns(4)
    metric_cols[0].metric("Total charges", f"${charges['amount'].sum():,.2f}")
    metric_cols[1].metric("Credits/payments", f"${credits['amount'].sum():,.2f}")
    metric_cols[2].metric("Transactions", f"{len(df):,}")
    metric_cols[3].metric("Big items", f"{len(big_items):,}")

    st.subheader("Line items")
    filtered = filter_dataframe(df)
    st.dataframe(
        filtered[
            ["date", "description", "amount", "bank", "source_file", "category", "confidence", "flag"]
        ].style.format({"amount": "{:,.2f}"}),
        hide_index=True,
        use_container_width=True,
    )

    summary_col, export_col = st.columns([1, 1])
    with summary_col:
        st.subheader("Category summary")
        summary = (
            charges.groupby("category", as_index=False)["amount"]
            .sum()
            .sort_values("amount", ascending=False)
            .reset_index(drop=True)
        )
        st.dataframe(summary.style.format({"amount": "{:,.2f}"}), hide_index=True, use_container_width=True)

    with export_col:
        st.subheader("Export")
        csv = filtered.to_csv(index=False).encode("utf-8")
        st.download_button("Download filtered CSV", csv, "statement-analysis.csv", "text/csv")
        all_csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Download all CSV", all_csv, "statement-analysis-all.csv", "text/csv")


def filter_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    with st.expander("Filters", expanded=True):
        cols = st.columns(4)
        search = cols[0].text_input("Search")
        category = cols[1].selectbox("Category", ["All", *sorted(df["category"].dropna().unique())])
        bank = cols[2].selectbox("Bank", ["All", *sorted(df["bank"].dropna().unique())])
        view = cols[3].selectbox("View", ["All", "Charges only", "Credits only", "Big items only"])

    filtered = df.copy()
    if search:
        mask = filtered.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
        filtered = filtered[mask]
    if category != "All":
        filtered = filtered[filtered["category"] == category]
    if bank != "All":
        filtered = filtered[filtered["bank"] == bank]
    if view == "Charges only":
        filtered = filtered[filtered["amount"] > 0]
    elif view == "Credits only":
        filtered = filtered[filtered["amount"] < 0]
    elif view == "Big items only":
        filtered = filtered[filtered["flag"] == "Big item"]
    return filtered


if __name__ == "__main__":
    main()
