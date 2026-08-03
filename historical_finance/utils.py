"""Shared logic for the historical statement extractor modules (income statement, balance sheet, cash flow)."""

import re

import pandas as pd

import sec_financials


def adjusted_date(raw_date) -> pd.Timestamp:
    """Shift back one month if day-of-month is 1-7 (EDGAR filing dates sometimes land just after period-end)."""
    ts = pd.Timestamp(raw_date)
    return ts - pd.offsets.MonthBegin(1) if ts.day <= 7 else ts


def format_period_label(filing_date) -> str:
    return adjusted_date(filing_date).strftime("%b %Y")


def extract_date_from_header(header_text) -> pd.Timestamp:
    """Pull a date out of a raw statement column header, e.g. 'Three Months Ended March 28, 2026'."""
    match = re.search(r"([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})", str(header_text))
    if not match:
        return None
    try:
        return pd.Timestamp(match.group(1))
    except (ValueError, TypeError):
        return None


def reformat_statement_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename the current/prior-period columns (2nd and 3rd) to 'MMM YYYY'."""
    if df is None or df.empty or len(df.columns) < 2:
        return df

    df = df.copy()
    rename_map = {}
    for col in df.columns[1:3]:
        parsed = extract_date_from_header(col)
        if parsed is not None:
            rename_map[col] = format_period_label(parsed)
    return df.rename(columns=rename_map)


def remove_ytd_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop columns whose header mentions 'YTD', keeping the label column and everything else."""
    if df is None or df.empty:
        return df

    keep_cols = [df.columns[0]]
    for col in df.columns[1:]:
        if "ytd" not in str(col).lower():
            keep_cols.append(col)
    return df[keep_cols]


def fiscal_year_start(selected_year: int, fiscal_year_end_month: int) -> pd.Timestamp:
    """First day of fiscal year `selected_year` given the month it ends in."""
    fiscal_year_end = pd.Timestamp(year=selected_year, month=fiscal_year_end_month, day=1) + pd.offsets.MonthEnd(0)
    return (fiscal_year_end - pd.DateOffset(months=11)).replace(day=1)


def filings_on_or_after(filings: list, cutoff: pd.Timestamp) -> list:
    return [f for f in filings if pd.Timestamp(f.filing_date) >= cutoff]


def _fetch_all_filings(symbol: str) -> tuple:
    return sec_financials.get_recent_filings(symbol, "10-Q"), sec_financials.get_recent_filings(symbol, "10-K")


def get_available_years(symbol: str) -> list:
    """Every distinct year across a company's 10-Q and 10-K filings, newest first."""
    quarterly_filings, annual_filings = _fetch_all_filings(symbol)
    years = {adjusted_date(f.filing_date).year for f in quarterly_filings + annual_filings}
    return sorted(years, reverse=True)


def extract_statements(symbol, fiscal_year_end_month, selected_year, fetch_fn, clean_fn, strip_ytd, on_progress=None):
    """
    Build one Excel workbook covering every 10-Q/10-K filing for
    `symbol` from the start of fiscal year `selected_year` onward.
    Shared by the income statement, balance sheet, and cash flow
    modules — each just supplies its own fetch/clean functions and
    whether YTD columns should be stripped (only income statement
    wants this; balance sheet and cash flow keep them).

    on_progress(current, total, period_label), if given, is called
    after each filing is processed — for driving a progress bar with
    a status label.

    Returns (workbook_bytes, sheet_names); workbook_bytes is None if
    nothing could be extracted.
    """
    quarterly_filings, annual_filings = _fetch_all_filings(symbol)

    start = fiscal_year_start(selected_year, fiscal_year_end_month)
    selected_quarterly = filings_on_or_after(quarterly_filings, start)
    selected_annual = filings_on_or_after(annual_filings, start)

    if not selected_quarterly and not selected_annual:
        return None, []

    # Interleave both filing types chronologically, newest first.
    combined = [(f, "10-Q") for f in selected_quarterly] + [(f, "10-K") for f in selected_annual]
    combined.sort(key=lambda pair: pair[0].filing_date, reverse=True)

    total = len(combined)
    all_sheets = {}
    for i, (f, form_type) in enumerate(combined):
        period_label = format_period_label(f.filing_date)
        if form_type == "10-K":
            period_label += " (FY)"

        try:
            raw = fetch_fn(f)
            cleaned = clean_fn(raw)
            if strip_ytd and form_type == "10-Q":
                cleaned = remove_ytd_columns(cleaned)
            cleaned = reformat_statement_columns(cleaned)
            all_sheets[period_label] = cleaned
        except Exception:
            pass  # skip this filing; caller can compare returned sheet_names to spot gaps

        if on_progress:
            on_progress(i + 1, total, period_label)

    if not all_sheets:
        return None, []

    return sec_financials.build_workbook_bytes(all_sheets), list(all_sheets.keys())