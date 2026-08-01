import concurrent.futures

import streamlit as st
import pandas as pd

import sec_financials
import companies_db
from historical_finance import income_statement

st.set_page_config(page_title="Financial Data Extractor", page_icon="📊", layout="centered")
sec_financials.init()

if "page" not in st.session_state:
    st.session_state.page = "home"

# ==================================================================
# Sidebar
# ==================================================================
st.sidebar.title("Menu")

if st.sidebar.button("📊 Financial Statement Extraction", width='stretch'):
    st.session_state.page = "home"
    st.rerun()

if st.sidebar.button("📈 Historical Financials", width='stretch'):
    st.session_state.page = "historical_financials"
    st.rerun()

if st.sidebar.button("📋 Companies List", width='stretch'):
    st.session_state.page = "companies_list"
    st.rerun()

if st.sidebar.button("ℹ️ About", width='stretch'):
    st.session_state.page = "about"
    st.rerun()

# ==================================================================
# About
# ==================================================================
if st.session_state.page == "about":
    st.title("About")

    st.markdown("""
This app pulls financial statements directly from SEC EDGAR and lets you export them to Excel.

**Financial Statement Extraction** — pick one or more companies, choose 10-Q or 10-K,
select a filing period per company, then extract. Produces a `.zip` with three workbooks:
Income Statement, Cash Flow Statement, and Balance Sheet.

**Historical Financials** — pick a company and a starting fiscal year, then download a
single workbook covering every 10-Q and 10-K filed from that year to the present — one
sheet per filing, newest to oldest. Currently available for the Income Statement; Balance
Sheet and Cash Flow Statement are in development.

**Companies List** — a read-only view of every company in the database, along with their
latest reported quarter and next expected earnings date.

**Managing companies** — this app doesn't add or remove companies itself. Run
`python companies_db.py` from the project folder to add a company by symbol — the name and
fiscal year end month are looked up automatically via yfinance, and you'll only be asked to
enter either manually if that lookup fails. The same tool lets you remove a company, list
all companies, or refresh existing entries.
""")

# ==================================================================
# Companies List — read-only; manage entries via companies_db.py
# ==================================================================
elif st.session_state.page == "companies_list":
    st.title("Companies List")

    companies_df = companies_db.load_companies()

    if companies_df.empty:
        st.info("No companies in the database yet. Add some locally — see companies_db.py.")
    else:
        def _fetch_row(symbol, name):
            return {
                "Company Name": name,
                "Symbol": symbol,
                "Latest Earning Period": sec_financials.get_latest_earning_period(symbol),
                "Next Earning Date": sec_financials.get_next_earnings_date(symbol),
            }

        with st.spinner("Loading companies..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(_fetch_row, row["Symbol"], row["Company Name"])
                    for _, row in companies_df.iterrows()
                ]
                display_rows = [f.result() for f in futures]

        st.dataframe(pd.DataFrame(display_rows), width='stretch', hide_index=True)

# ==================================================================
# Historical Financials
# ==================================================================
elif st.session_state.page == "historical_financials":
    st.title("Historical Financials")

    hist_companies_df = companies_db.load_companies()

    if hist_companies_df.empty:
        st.info("No companies in the database yet. Add some locally — see companies_db.py.")
    else:
        col1, col2 = st.columns([2, 1])
        with col1:
            selected_company_name = st.selectbox(
                "Company Name",
                options=hist_companies_df["Company Name"].tolist(),
                index=None,
                placeholder="Select a company",
            )

        symbol = None
        fiscal_year_end_month = None
        available_years = []

        if selected_company_name:
            company_row = hist_companies_df[hist_companies_df["Company Name"] == selected_company_name].iloc[0]
            symbol = company_row["Symbol"]
            fiscal_year_end_month = companies_db.month_number(company_row["Fiscal Year End Month"])

            try:
                available_years = income_statement.get_available_years(symbol)
            except Exception as e:
                st.warning(f"Could not fetch filing years for {symbol}: {e}")

        with col2:
            if selected_company_name and available_years:
                selected_year = st.selectbox(
                    "Beginning Financial Year",
                    options=available_years,
                    index=None,
                    placeholder="Select a year",
                )
            else:
                st.selectbox(
                    "Beginning Financial Year",
                    options=[],
                    index=None,
                    placeholder="Select a company first" if not selected_company_name else "No years available",
                    disabled=True,
                )
                selected_year = None

        st.markdown("**Download**")
        dl_col1, dl_col2, dl_col3 = st.columns(3)

        with dl_col1:
            clicked_income = st.button(
                "Download Income Statements", width='stretch', disabled=(selected_year is None)
            )
        with dl_col2:
            clicked_balance = st.button(
                "Download Balance Sheets", width='stretch', disabled=(selected_year is None)
            )
        with dl_col3:
            clicked_cashflow = st.button(
                "Download Cash Flow Statements", width='stretch', disabled=(selected_year is None)
            )

        # Rendered outside the columns above, so these span the full width.
        if clicked_income:
            progress_bar = st.progress(0)
            status_text = st.empty()

            def _update_progress(current, total, period_label):
                status_text.text(f"Extracting {period_label}... ({current}/{total})")
                progress_bar.progress(current / total if total else 1.0)

            try:
                workbook_bytes, sheet_names = income_statement.extract_income_statements(
                    symbol, fiscal_year_end_month, selected_year, on_progress=_update_progress
                )
            except Exception as e:
                workbook_bytes, sheet_names = None, []
                st.error(f"Extraction failed: {e}")

            progress_bar.empty()
            status_text.empty()

            if workbook_bytes:
                st.success(f"Income Statements from {selected_year} is ready.")
                st.download_button(
                    "⬇️ Download",
                    data=workbook_bytes,
                    file_name=f"{symbol}_Income_Statements.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width='stretch',
                )
            elif workbook_bytes is None and not sheet_names:
                st.error("No data extracted.")

        if clicked_balance:
            st.info("This section is under development.")

        if clicked_cashflow:
            st.info("This section is under development.")

# ==================================================================
# Financial Statement Extraction
# ==================================================================
else:
    st.title("Financial Statement Extraction")

    companies_df = sec_financials.load_companies()

    st.subheader("Select Companies")
    selected_symbols = st.multiselect(
        "Search & Select Companies",
        options=companies_df["Symbol"].tolist() if not companies_df.empty else [],
        format_func=lambda x: companies_df[companies_df["Symbol"] == x]["Company Name"].iloc[0],
        placeholder="Type to search companies...",
    )

    selected_data = []

    if selected_symbols:
        st.subheader("Filing Type")
        filing_type = st.radio("Choose Filing Type", sec_financials.FILING_TYPES, horizontal=True)

        st.subheader("Select Filing Period")
        for symbol in selected_symbols:
            try:
                filings = sec_financials.get_recent_filings(symbol, filing_type)
                options = [f.filing_date.strftime("%b-%Y") for f in filings]
                company_name = companies_df[companies_df["Symbol"] == symbol]["Company Name"].iloc[0]

                chosen_formatted = st.selectbox(f"**{company_name}**", options, key=f"filing_{symbol}")
                chosen_filing = filings[options.index(chosen_formatted)]

                selected_data.append({
                    "Company": company_name,
                    "Symbol": symbol,
                    "Filing Type": filing_type,
                    "Filing Date": chosen_formatted,
                    "Filing": chosen_filing,
                })
            except Exception:
                st.warning(f"Could not load filings for {symbol}")

        if selected_data:
            st.subheader("Selected Companies & Filings")
            summary_df = pd.DataFrame(selected_data)[["Company", "Filing Type", "Filing Date"]]
            st.dataframe(summary_df, width='stretch', hide_index=True)

    if selected_data:
        st.subheader("Extract")

        if st.button("🚀 Extract Financial Data", type="primary", width='stretch'):
            income_sheets, cashflow_sheets, balance_sheets = {}, {}, {}
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, row in enumerate(selected_data):
                status_text.text(f"Extracting {row['Company']} — {row['Filing Date']}...")
                try:
                    income_raw, cashflow_raw, balance_raw = sec_financials.get_statements(row["Filing"])
                    income_sheets[row["Company"]] = sec_financials.clean_income_statement(income_raw)
                    cashflow_sheets[row["Company"]] = sec_financials.clean_cashflow_statement(cashflow_raw)
                    balance_sheets[row["Company"]] = sec_financials.clean_balance_sheet(balance_raw)
                except Exception as e:
                    st.warning(f"Skipped {row['Company']}: {e}")
                progress_bar.progress((i + 1) / len(selected_data))

            status_text.empty()

            if income_sheets and cashflow_sheets and balance_sheets:
                filing_type = selected_data[0]["Filing Type"]

                zip_bytes = sec_financials.build_zip_bytes({
                    f"All_{filing_type}_Income.xlsx": sec_financials.build_workbook_bytes(income_sheets),
                    f"All_{filing_type}_Cashflow.xlsx": sec_financials.build_workbook_bytes(cashflow_sheets),
                    f"All_{filing_type}_BalanceSheet.xlsx": sec_financials.build_workbook_bytes(balance_sheets),
                })

                st.success("✅ Extraction complete. Click below to save files.")
                st.download_button(
                    "⬇️ Download",
                    data=zip_bytes,
                    file_name=f"{filing_type}_Extract.zip",
                    mime="application/zip",
                    width='stretch',
                )
            else:
                st.error("No data extracted.")
