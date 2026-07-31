import io
import zipfile
import streamlit as st
import pandas as pd
import yfinance as yf
from edgar import set_identity, Company

import companies_db

# ==================================================================
# SEC Financials (SEC EDGAR filing fetch/clean + earnings-date lookup)
# ==================================================================

FILING_TYPES = ["10-Q", "10-K"]

_identity_set = False


def init() -> None:
    """One-time setup. Safe to call multiple times."""
    global _identity_set
    if not _identity_set:
        set_identity("Your Name your.email@example.com")   # ← CHANGE THIS
        companies_db.init_db()
        _identity_set = True


# ---------------------------------------------------------------- Companies

def load_companies() -> pd.DataFrame:
    """Companies come from the SQLite database — manage them locally via companies_db.py."""
    return companies_db.load_companies()


# ---------------------------------------------------------------- Earnings date

@st.cache_data(ttl=3600, show_spinner=False)
def get_next_earnings_date(symbol: str) -> str:
    """Next earnings date for `symbol` via yfinance, formatted as e.g. '05-Aug-26', or '-' if unavailable."""
    try:
        ticker = yf.Ticker(symbol)
        earnings = ticker.get_earnings_dates(limit=1)
        if not earnings.empty:
            earning_date = earnings.index[0].strftime("%d-%b-%y")
            return earning_date
    except Exception:
        pass
    return "-"


@st.cache_data(ttl=3600, show_spinner=False)
def get_latest_earning_period(symbol: str) -> str:
    """Most recent reported quarter for `symbol` via yfinance, formatted as e.g. 'Jun 2026', or '-' if unavailable."""
    try:
        ticker = yf.Ticker(symbol)
        quarterly = ticker.quarterly_financials
        if quarterly is not None and not quarterly.empty:
            latest_date = quarterly.columns[0]
            period = latest_date.strftime("%b %Y")
            return period
    except Exception:
        pass
    return "-"


# ---------------------------------------------------------------- Edgar fetching

def get_recent_filings(symbol: str, filing_type: str):
    """Return every available filing of `filing_type` for `symbol`."""
    company = Company(symbol)
    return list(company.get_filings(form=filing_type))


def get_statements(filing):
    """Pull the raw (uncleaned) income statement, cash flow, and balance sheet dataframes for a filing."""
    xbrl = filing.xbrl()
    income_raw = xbrl.statements.income_statement(view="detailed").to_dataframe()
    cashflow_raw = xbrl.statements.cashflow_statement(view="detailed").to_dataframe()
    balance_raw = xbrl.statements.balance_sheet(view="detailed").to_dataframe()
    return income_raw, cashflow_raw, balance_raw


# ---------------------------------------------------------------- Cleaning

_COLUMNS_TO_REMOVE = [
    'concept', 'standard_concept', 'level', 'abstract', 'dimension',
    'is_breakdown', 'dimension_axis', 'dimension_member', 'dimension_member_label',
    'dimension_label', 'balance', 'weight', 'preferred_sign',
    'parent_concept', 'parent_abstract_concept', 'value_millions',
]


def clean_income_statement(df: pd.DataFrame) -> pd.DataFrame:
    """Clean Income Statement — drop non-data columns, edit freely as needed."""
    if df is None or df.empty:
        return df

    df = df.copy()
    df = df.drop(columns=[c for c in _COLUMNS_TO_REMOVE if c in df.columns])
    df = df.dropna(how='all')
    return df


def clean_cashflow_statement(df: pd.DataFrame) -> pd.DataFrame:
    """Clean Cash Flow Statement — drop non-data columns, edit freely as needed."""
    if df is None or df.empty:
        return df

    df = df.copy()
    df = df.drop(columns=[c for c in _COLUMNS_TO_REMOVE if c in df.columns])
    df = df.dropna(how='all')
    return df


def clean_balance_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """Clean Balance Sheet — drop non-data columns, edit freely as needed."""
    if df is None or df.empty:
        return df

    df = df.copy()
    df = df.drop(columns=[c for c in _COLUMNS_TO_REMOVE if c in df.columns])
    df = df.dropna(how='all')
    return df


# ---------------------------------------------------------------- Excel / Zip

def build_workbook_bytes(sheets: dict) -> bytes:
    """
    Build an .xlsx file entirely in memory (no disk writes) so it can be
    handed straight to st.download_button.

    sheets: {sheet_name: dataframe}
    """
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    buffer.seek(0)
    return buffer.getvalue()


def build_zip_bytes(files: dict) -> bytes:
    """
    Bundle multiple in-memory files into a single .zip, so the user can
    get everything with one download-button click.

    files: {filename_in_zip: raw_bytes}
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, data in files.items():
            zf.writestr(filename, data)
    buffer.seek(0)
    return buffer.getvalue()