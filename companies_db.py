import os
import sqlite3
import pandas as pd

# ==================================================================
# Companies database (SQLite)
#
# Single flat table: symbol (primary key), company_name,
# fiscal_year_end_month. No separate id column — symbol is naturally
# unique, so it's the key everywhere (add, remove, lookup).
#
# fiscal_year_end_month is stored as a 3-letter abbreviation ("Jan"
# .. "Dec") — the calendar month a company's fiscal year ends in, e.g.
# Apple = "Sep", most companies use the standard calendar year =
# "Dec". This is what lets a filing date later be translated into a
# fiscal quarter label (Q1/Q2/etc.) instead of just a calendar date.
#
# Note on deleting rows: SQLite doesn't leave a "blank row" behind
# after a DELETE — the row is fully gone from every query, the same
# as it would be in any relational database. The only thing a DELETE
# doesn't do automatically is shrink the .db file back down (freed
# space goes into an internal free-list for reuse, not back to the
# OS) — that's a disk-space detail, not something that ever shows up
# as an empty row. remove_company_by_symbol() runs VACUUM immediately
# after each delete anyway, so the file itself stays fully compacted.
#
# The Streamlit app only reads this (read-only "Companies List" page —
# Streamlit Cloud's filesystem is ephemeral, so writes made through a
# deployed app wouldn't persist anyway). All add/remove management is
# done locally by running this file directly:
#
#   python companies_db.py
#
# which opens an interactive menu (list / add / remove). Then push the
# updated companies.db alongside your code.
# ==================================================================

# Anchored to this file's own directory (the project root), not the
# current working directory — otherwise running a script from a
# subfolder (e.g. historical_finance/income_statement.py invoked with
# that as cwd) would silently create/read a second, empty companies.db
# inside that subfolder instead of the real one.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "companies.db")

_MONTH_ABBREVIATIONS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _normalize_month(value) -> str:
    """
    Accepts '9', 'sep', 'SEP', or 'September' and returns the
    canonical 3-letter form ('Sep'), or None if it isn't a valid month.
    Numeric input is accepted mainly so any leftover data from before
    this MMM-format change still converts cleanly.
    """
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
    """'Sep' (or '9', 'september', etc.) -> 9. Returns None if invalid."""
    normalized = _normalize_month(abbreviation)
    if normalized is None:
        return None
    return _MONTH_ABBREVIATIONS.index(normalized) + 1


def _get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db() -> None:
    """
    Create the companies table if it doesn't exist yet. Safe to call
    multiple times. Also migrates an existing companies.db:
      - adds fiscal_year_end_month (default 'Dec') if the column is
        missing entirely (pre-fiscal-year-tracking database), or
      - converts any leftover numeric values (from before the switch
        to MMM format) into their 'Jan'..'Dec' equivalent.
    """
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

    existing_columns = [row[1] for row in conn.execute("PRAGMA table_info(companies)").fetchall()]
    if "fiscal_year_end_month" not in existing_columns:
        conn.execute("ALTER TABLE companies ADD COLUMN fiscal_year_end_month TEXT NOT NULL DEFAULT 'Dec'")
        conn.commit()
    else:
        rows = conn.execute("SELECT symbol, fiscal_year_end_month FROM companies").fetchall()
        for symbol, value in rows:
            if value is not None and str(value).strip().isdigit():
                normalized = _normalize_month(value)
                if normalized:
                    conn.execute(
                        "UPDATE companies SET fiscal_year_end_month = ? WHERE symbol = ?",
                        (normalized, symbol),
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
    cursor = conn.execute(
        "SELECT company_name, symbol, fiscal_year_end_month FROM companies WHERE UPPER(symbol) = ?",
        (symbol,),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None
    return {"Company Name": row[0], "Symbol": row[1], "Fiscal Year End Month": row[2]}


def add_company(company_name: str, symbol: str, fiscal_year_end_month: str = "Dec") -> tuple:
    """Insert a company. Returns (success: bool, message: str)."""
    company_name = company_name.strip()
    symbol = symbol.strip().upper()

    if not company_name or not symbol:
        return False, "Company name and symbol are both required."

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


def remove_company_by_symbol(symbol: str) -> tuple:
    """Remove a company by symbol (case-insensitive), then reclaim the freed disk space."""
    symbol = symbol.strip().upper()
    conn = _get_connection()
    cursor = conn.execute("SELECT company_name FROM companies WHERE UPPER(symbol) = ?", (symbol,))
    match = cursor.fetchone()
    if match is None:
        conn.close()
        return False, f"No company found with symbol '{symbol}'."

    company_name = match[0]
    conn.execute("DELETE FROM companies WHERE UPPER(symbol) = ?", (symbol,))
    conn.commit()
    conn.close()

    # VACUUM rebuilds the file with the deleted row's space reclaimed.
    # Needs its own connection, run after the delete's transaction is
    # already committed and closed.
    vacuum_conn = _get_connection()
    vacuum_conn.execute("VACUUM")
    vacuum_conn.close()

    return True, f"Removed {company_name} ({symbol})."


# ==================================================================
# Interactive menu — run with no arguments for a simple numbered menu
# instead of remembering command syntax.
# ==================================================================
def _print_companies() -> None:
    df = load_companies()
    if df.empty:
        print("No companies in the database.")
    else:
        print(df.to_string(index=False))


def _run_interactive_menu() -> None:
    init_db()
    while True:
        print("\n=== Companies Database ===")
        print("1. List companies")
        print("2. Add a company")
        print("3. Remove a company")
        print("4. Exit")

        choice = input("Choose an option (1-4): ").strip()

        if choice == "1":
            print()
            _print_companies()

        elif choice == "2":
            name = input("Company Name: ").strip()
            symbol = input("Symbol: ").strip()
            month_input = input("Fiscal Year End Month (e.g. Sep, blank = Dec): ").strip()
            fiscal_year_end_month = month_input if month_input else "Dec"

            ok, message = add_company(name, symbol, fiscal_year_end_month)
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
            print("Done.")
            break

        else:
            print("Not a valid option — enter a number from 1 to 4.")


if __name__ == "__main__":
    _run_interactive_menu()