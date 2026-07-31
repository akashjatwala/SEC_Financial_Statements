"""
Historical Income Statement Extractor (10-Q and 10-K)

Used by app.py's "Historical Financials" page via two functions:
  - get_available_years(symbol)
  - extract_income_statements(symbol, fiscal_year_end_month, selected_year)

Flow:
  1. Given a company symbol and its fiscal_year_end_month (looked up
     from companies.db by the caller).
  2. get_available_years() reports every year that has at least one
     10-Q or 10-K filing (deduplicated) — used to populate the
     "Beginning Financial Year" dropdown.
  3. Given a STARTING fiscal year, combined with the company's fiscal
     year end month, that becomes an actual start date — e.g. 2020 for
     a company whose fiscal year ends in September means "everything
     from the start of fiscal year 2020 (Oct 2019) onward".
  4. Every 10-Q and 10-K filing on/after that date through the latest
     available gets its income statement fetched, cleaned (via
     sec_financials.clean_income_statement), and has its current/
     prior-period column headers reformatted to 'MMM YYYY'. 10-Q
     filings additionally get their YTD columns stripped — 10-K
     filings don't need this, since an annual report has no
     quarterly-vs-year-to-date split to begin with.
  5. Returned as one in-memory Excel workbook: one sheet per filing
     (10-Q or 10-K), sorted purely chronologically newest to oldest —
     interleaved together rather than grouped by filing type. 10-K
     sheet names get an " (FY)" suffix, e.g. "Sep 2025 (FY)", to
     distinguish them from 10-Q quarters that might otherwise share
     the same MMM YYYY label.

IMPORTANT — the YTD-column heuristic below is unverified against a
real EDGAR response (no live network access while building this). 10-Q
filings typically carry both a current-quarter ("Three Months Ended")
and a year-to-date ("Six/Nine Months Ended") column side by side for
each period; _YTD_KEYWORDS is a best-effort keyword match against the
column headers edgartools produces. Once you've run this against a
real filing, inspect the printed column names and adjust
_YTD_KEYWORDS if the actual wording differs. The same caveat applies to
_extract_date_from_header(), used to reformat statement column headers
— it's a regex guess at the raw header wording, not yet verified. Also
worth checking once you have real data: 10-K income statements commonly
show three years of comparatives, not two — reformat_statement_columns()
currently only reformats columns 2 and 3 (matching 10-Q's current +
prior-year-comparative shape); widen that if a 10-K's third column also
needs reformatting.
"""

import re

import pandas as pd

import sec_financials

# Adjust these if a real fetch shows different column-header wording.
_YTD_KEYWORDS = [
    "six months", "nine months", "twelve months",
    "ytd", "year to date", "cumulative",
]


def _adjusted_date(raw_date) -> pd.Timestamp:
    """
    Shift a date back one month if its day-of-month is 1-7 — EDGAR
    filing dates sometimes land a few days into the month after the
    period they actually represent (e.g. a quarter or fiscal year
    conceptually ending in September gets stamped October 1).
    """
    ts = pd.Timestamp(raw_date)
    if ts.day <= 7:
        ts = ts - pd.offsets.MonthBegin(1)
    return ts


def format_period_label(filing_date) -> str:
    """Format a filing date as 'MMM YYYY', after the day-1-7 adjustment above."""
    return _adjusted_date(filing_date).strftime("%b %Y")


def _extract_date_from_header(header_text) -> pd.Timestamp:
    """
    Pull a date out of a raw statement column header, e.g.
    'Three Months Ended March 28, 2026' or an ISO-formatted date.
    Returns None if nothing date-shaped is found.
    """
    text = str(header_text)
    match = re.search(r"([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})", text)
    if not match:
        return None
    try:
        return pd.Timestamp(match.group(1))
    except (ValueError, TypeError):
        return None


def reformat_statement_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename columns 2 and 3 (the value columns just beside the label
    column) from their raw XBRL header text to 'MMM YYYY' format.
    Falls back to leaving a header unchanged if no date can be parsed
    out of it.
    """
    if df is None or df.empty or len(df.columns) < 2:
        return df

    df = df.copy()
    rename_map = {}
    for col in df.columns[1:3]:
        parsed = _extract_date_from_header(col)
        if parsed is not None:
            rename_map[col] = format_period_label(parsed)

    return df.rename(columns=rename_map)


def fetch_income_statement(filing) -> pd.DataFrame:
    """
    Pull only the income statement for a filing — deliberately not
    reusing sec_financials.get_statements(), which also fetches cash
    flow and balance sheet data we don't need here. Works the same way
    for 10-Q and 10-K filings.
    """
    xbrl = filing.xbrl()
    return xbrl.statements.income_statement(view="detailed").to_dataframe()


def remove_ytd_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop any column whose header suggests a cumulative/YTD period,
    keeping the label column and any quarterly ("Three Months Ended")
    columns. Only relevant for 10-Q filings — a 10-K's income statement
    has no quarterly-vs-YTD split to begin with. See the module
    docstring — this is a keyword heuristic, not verified against a
    live filing yet.
    """
    if df is None or df.empty:
        return df

    label_col = df.columns[0]
    keep_cols = [label_col]
    for col in df.columns[1:]:
        col_text = str(col).lower()
        if any(keyword in col_text for keyword in _YTD_KEYWORDS):
            continue
        keep_cols.append(col)

    return df[keep_cols]


def _fiscal_year_start(selected_year: int, fiscal_year_end_month: int) -> pd.Timestamp:
    """
    First day of fiscal year `selected_year`, given the month it ends
    in. E.g. selected_year=2020, fiscal_year_end_month=9 (Sep) ->
    2019-10-01 (Apple's FY2020 runs Oct 2019 - Sep 2020). For a
    standard calendar-year company (end month 12), this correctly
    resolves to Jan 1 of selected_year itself.
    """
    fiscal_year_end = pd.Timestamp(year=selected_year, month=fiscal_year_end_month, day=1) + pd.offsets.MonthEnd(0)
    return (fiscal_year_end - pd.DateOffset(months=11)).replace(day=1)


def _filings_on_or_after(filings: list, cutoff: pd.Timestamp) -> list:
    """Keep filings on/after `cutoff`, using the raw filing date (not the day-1-7-adjusted one)."""
    return [f for f in filings if pd.Timestamp(f.filing_date) >= cutoff]


# ==================================================================
# Public API — used by app.py
# ==================================================================

def get_available_years(symbol: str) -> list:
    """
    Every distinct year (after the day-1-7 adjustment used everywhere
    else) across a company's 10-Q and 10-K filings, newest first.
    """
    quarterly_filings = sec_financials.get_recent_filings(symbol, "10-Q")
    annual_filings = sec_financials.get_recent_filings(symbol, "10-K")
    years = {_adjusted_date(f.filing_date).year for f in quarterly_filings + annual_filings}
    return sorted(years, reverse=True)


def extract_income_statements(symbol: str, fiscal_year_end_month: int, selected_year: int, on_progress=None):
    """
    Fetch, clean, and combine every 10-Q/10-K income statement for
    `symbol` from the start of fiscal year `selected_year` through the
    latest available filing, into one in-memory Excel workbook — one
    sheet per filing, sorted newest to oldest, interleaved by type.

    on_progress, if given, is called with a short status string per
    step (e.g. the CLI passes `print`; callers that don't need a log
    can leave this as None).

    Returns (workbook_bytes, sheet_names). workbook_bytes is None if
    nothing could be extracted.
    """
    quarterly_filings = sec_financials.get_recent_filings(symbol, "10-Q")
    annual_filings = sec_financials.get_recent_filings(symbol, "10-K")

    fiscal_year_start = _fiscal_year_start(selected_year, fiscal_year_end_month)
    selected_quarterly = _filings_on_or_after(quarterly_filings, fiscal_year_start)
    selected_annual = _filings_on_or_after(annual_filings, fiscal_year_start)

    if not selected_quarterly and not selected_annual:
        return None, []

    # Merge both filing types into one list, tagged by form, then sort
    # newest to oldest by actual filing date — so sheets end up fully
    # interleaved chronologically rather than grouped by form type.
    combined = (
        [(f, "10-Q") for f in selected_quarterly]
        + [(f, "10-K") for f in selected_annual]
    )
    combined.sort(key=lambda pair: pair[0].filing_date, reverse=True)

    all_sheets = {}
    for f, form_type in combined:
        if form_type == "10-Q":
            period_label = format_period_label(f.filing_date)
        else:
            period_label = f"{format_period_label(f.filing_date)} (FY)"

        if on_progress:
            on_progress(f"Processing {form_type} {period_label}...")
        try:
            income_raw = fetch_income_statement(f)
            cleaned = sec_financials.clean_income_statement(income_raw)
            if form_type == "10-Q":
                cleaned = remove_ytd_columns(cleaned)
            cleaned = reformat_statement_columns(cleaned)  # 10-K has no YTD split, so nothing to strip there
            all_sheets[period_label] = cleaned
        except Exception as e:
            if on_progress:
                on_progress(f"  Skipped {period_label}: {e}")

    if not all_sheets:
        return None, []

    workbook_bytes = sec_financials.build_workbook_bytes(all_sheets)
    return workbook_bytes, list(all_sheets.keys())
