import os
import sqlite3

import pandas as pd
import yfinance as yf

# Anchored to this file's location (the project root), not the current
# working directory, so it resolves correctly regardless of where a
# script is run from.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "companies.db")

_MONTH_ABBREVIATIONS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _normalize_month(value) -> str:
    """Accepts '9', 'sep', or 'September' and returns the canonical 'Sep' form, or None if invalid."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    if text.isdigit():
        n = int(text)
        return _MONTH_ABBREVIATIONS[n - 1] if 1 <= n <= 12 else None

    candidate = text[:3].title()
    return candidate if candidate in _MONTH_ABBREVIATIONS else None


def month_number(abbreviation) -> int:
    """'Sep' -> 9. Returns None if invalid."""
    normalized = _normalize_month(abbreviation)
    return _MONTH_ABBREVIATIONS.index(normalized) + 1 if normalized else None


def _fetch_company_name(symbol: str) -> str:
    """Look up a company's display name via yfinance. Returns None if unavailable."""
    try:
        info = yf.Ticker(symbol).info
        return info.get("longName") or info.get("shortName")
    except Exception:
        return None


def _fetch_fiscal_year_end_month(symbol: str) -> str:
    """Derive fiscal year end month from the most recent column of yfinance's annual financials."""
    try:
        financials = yf.Ticker(symbol).financials
        if financials is not None and not financials.empty:
            return _MONTH_ABBREVIATIONS[financials.columns[0].month - 1]
    except Exception:
        pass
    return None


def _get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db() -> None:
    """Create the companies table if it doesn't exist. Safe to call multiple times."""
    conn = _get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            symbol TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            fiscal_year_end_month TEXT NOT NULL DEFAULT 'Dec'
        )
        """
    )
    conn.commit()
    conn.close()


def load_companies() -> pd.DataFrame:
    """Every company, as a DataFrame."""
    conn = _get_connection()
    df = pd.read_sql_query(
        """
        SELECT
            company_name AS "Company Name",
            symbol AS "Symbol",
            fiscal_year_end_month AS "Fiscal Year End Month"
        FROM companies
        ORDER BY company_name
        """,
        conn,
    )
    conn.close()
    return df


def get_company(symbol: str):
    """Return {'Company Name', 'Symbol', 'Fiscal Year End Month'} for one symbol, or None if not found."""
    symbol = symbol.strip().upper()
    conn = _get_connection()
    row = conn.execute(
        "SELECT company_name, symbol, fiscal_year_end_month FROM companies WHERE UPPER(symbol) = ?",
        (symbol,),
    ).fetchone()
    conn.close()

    if row is None:
        return None
    return {"Company Name": row[0], "Symbol": row[1], "Fiscal Year End Month": row[2]}


def resolve_company_details(symbol: str) -> tuple:
    """Try to fetch company name and fiscal year end month via yfinance. Returns (name_or_None, month_or_None)."""
    symbol = symbol.strip().upper()
    return _fetch_company_name(symbol), _fetch_fiscal_year_end_month(symbol)


def add_company(symbol: str, company_name: str, fiscal_year_end_month: str) -> tuple:
    """Insert a company with an explicit name and fiscal year end month. Returns (success, message)."""
    symbol = symbol.strip().upper()
    company_name = (company_name or "").strip()

    if not symbol or not company_name:
        return False, "Symbol and company name are both required."

    normalized_month = _normalize_month(fiscal_year_end_month)
    if normalized_month is None:
        return False, "Fiscal year end month must be a valid month, e.g. 'Sep' or 'September'."

    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO companies (symbol, company_name, fiscal_year_end_month) VALUES (?, ?, ?)",
            (symbol, company_name, normalized_month),
        )
        conn.commit()
        return True, f"Added {company_name} ({symbol}), fiscal year ends in {normalized_month}."
    except sqlite3.IntegrityError:
        return False, f"Symbol '{symbol}' already exists."
    finally:
        conn.close()


def refresh_companies() -> list:
    """Re-fetch every existing company's name and fiscal year end month via yfinance. Returns [(symbol, name_or_None, month_or_None, success)]."""
    conn = _get_connection()
    symbols = [row[0] for row in conn.execute("SELECT symbol FROM companies").fetchall()]

    results = []
    for symbol in symbols:
        name = _fetch_company_name(symbol)
        month = _fetch_fiscal_year_end_month(symbol)
        if name and month:
            conn.execute(
                "UPDATE companies SET company_name = ?, fiscal_year_end_month = ? WHERE symbol = ?",
                (name, month, symbol),
            )
        results.append((symbol, name, month, bool(name and month)))

    conn.commit()
    conn.close()
    return results


def remove_company_by_symbol(symbol: str) -> tuple:
    """Remove a company by symbol (case-insensitive), then reclaim the freed disk space."""
    symbol = symbol.strip().upper()
    conn = _get_connection()
    match = conn.execute("SELECT company_name FROM companies WHERE UPPER(symbol) = ?", (symbol,)).fetchone()
    if match is None:
        conn.close()
        return False, f"No company found with symbol '{symbol}'."

    company_name = match[0]
    conn.execute("DELETE FROM companies WHERE UPPER(symbol) = ?", (symbol,))
    conn.commit()
    conn.close()

    # VACUUM reclaims the deleted row's disk space; run in its own
    # connection, after the delete's transaction has been committed.
    vacuum_conn = _get_connection()
    vacuum_conn.execute("VACUUM")
    vacuum_conn.close()

    return True, f"Removed {company_name} ({symbol})."


# ==================================================================
# Interactive CLI menu
# ==================================================================

def _print_companies() -> None:
    df = load_companies()
    print("No companies in the database." if df.empty else df.to_string(index=False))


def _run_interactive_menu() -> None:
    init_db()
    while True:
        print("\n=== Companies Database ===")
        print("1. List companies")
        print("2. Add a company")
        print("3. Remove a company")
        print("4. Refresh companies from yfinance")
        print("5. Exit")

        choice = input("Choose an option (1-5): ").strip()

        if choice == "1":
            print()
            _print_companies()

        elif choice == "2":
            symbol = input("Symbol: ").strip()
            company_name, fiscal_year_end_month = resolve_company_details(symbol)

            if not company_name:
                print(f"Could not fetch a company name for '{symbol}' via yfinance.")
                company_name = input("Enter company name manually: ").strip()

            if not fiscal_year_end_month:
                print(f"Could not determine a fiscal year end month for '{symbol}' via yfinance.")
                fiscal_year_end_month = input("Enter fiscal year end month manually (e.g. Sep): ").strip()

            ok, message = add_company(symbol, company_name, fiscal_year_end_month)
            print(message)

        elif choice == "3":
            print()
            df = load_companies()
            if df.empty:
                print("No companies to remove.")
                continue
            _print_companies()
            symbol = input("\nEnter symbol to remove: ").strip()
            ok, message = remove_company_by_symbol(symbol)
            print(message)

        elif choice == "4":
            print("\nRefreshing companies from yfinance...")
            for symbol, name, month, ok in refresh_companies():
                print(f"{symbol}: {name}, fiscal year ends in {month}" if ok else f"{symbol}: could not refresh")
            print("Done refreshing.")

        elif choice == "5":
            print("Done.")
            break

        else:
            print("Not a valid option — enter a number from 1 to 5.")


if __name__ == "__main__":
    _run_interactive_menu()
