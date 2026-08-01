import io
import zipfile

import streamlit as st
import pandas as pd
import yfinance as yf
from edgar import set_identity, Company

import companies_db

FILING_TYPES = ["10-Q", "10-K"]

_identity_set = False


def init() -> None:
    """One-time setup. Safe to call multiple times."""
    global _identity_set
    if not _identity_set:
        set_identity("Your Name your.email@example.com")   # ← CHANGE THIS
        companies_db.init_db()
        _identity_set = True


def load_companies() -> pd.DataFrame:
    return companies_db.load_companies()


@st.cache_data(ttl=3600, show_spinner=False)
def get_next_earnings_date(symbol: str) -> str:
    """Next earnings date via yfinance, e.g. '05-Aug-26', or '-' if unavailable."""
    try:
        earnings = yf.Ticker(symbol).get_earnings_dates(limit=1)
        if not earnings.empty:
            return earnings.index[0].strftime("%d-%b-%y")
    except Exception:
        pass
    return "-"


@st.cache_data(ttl=3600, show_spinner=False)
def get_latest_earning_period(symbol: str) -> str:
    """Most recent reported quarter via yfinance, e.g. 'Jun 2026', or '-' if unavailable."""
    try:
        quarterly = yf.Ticker(symbol).quarterly_financials
        if quarterly is not None and not quarterly.empty:
            return quarterly.columns[0].strftime("%b %Y")
    except Exception:
        pass
    return "-"


def get_recent_filings(symbol: str, filing_type: str):
    return list(Company(symbol).get_filings(form=filing_type))


def get_statements(filing):
    """Raw (uncleaned) income statement, cash flow, and balance sheet for a filing."""
    xbrl = filing.xbrl()
    return (
        xbrl.statements.income_statement(view="detailed").to_dataframe(),
        xbrl.statements.cashflow_statement(view="detailed").to_dataframe(),
        xbrl.statements.balance_sheet(view="detailed").to_dataframe(),
    )


_COLUMNS_TO_REMOVE = [
    "concept", "standard_concept", "level", "abstract", "dimension",
    "is_breakdown", "dimension_axis", "dimension_member", "dimension_member_label",
    "dimension_label", "balance", "weight", "preferred_sign",
    "parent_concept", "parent_abstract_concept", "value_millions",
]


def _clean_statement(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.copy()
    df = df.drop(columns=[c for c in _COLUMNS_TO_REMOVE if c in df.columns])
    return df.dropna(how="all")


def clean_income_statement(df: pd.DataFrame) -> pd.DataFrame:
    return _clean_statement(df)


def clean_cashflow_statement(df: pd.DataFrame) -> pd.DataFrame:
    return _clean_statement(df)


def clean_balance_sheet(df: pd.DataFrame) -> pd.DataFrame:
    return _clean_statement(df)


def build_workbook_bytes(sheets: dict) -> bytes:
    """Build an .xlsx file in memory from {sheet_name: dataframe}."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    buffer.seek(0)
    return buffer.getvalue()


def build_zip_bytes(files: dict) -> bytes:
    """Bundle multiple in-memory files into one .zip from {filename: bytes}."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, data in files.items():
            zf.writestr(filename, data)
    buffer.seek(0)
    return buffer.getvalue()
