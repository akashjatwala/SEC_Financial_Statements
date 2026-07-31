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

if st.sidebar.button("🏠 Home", width='stretch'):
    st.session_state.page = "home"
    st.rerun()

if st.sidebar.button("🕰️ Historical Financials", width='stretch'):
    st.session_state.page = "historical_financials"
    st.rerun()

if st.sidebar.button("📋 Companies List", width='stretch'):
    st.session_state.page = "companies_list"
    st.rerun()

st.title("📊 Financial Data Extractor")

# ==================================================================
# Companies List page — read-only. Add/remove companies locally via
# `python companies_db.py add/remove/list` (see that file) — Streamlit
# Cloud's filesystem is ephemeral, so writes made through a deployed
# app wouldn't persist anyway.
# ==================================================================
if st.session_state.page == "companies_list":
    st.subheader("Companies List")

    companies_df = companies_db.load_companies()

    if companies_df.empty:
        st.info("No companies in the database yet. Add some locally — see companies_db.py.")
    else:
        display_rows = [
            {
                "Company Name": row["Company Name"],
                "Symbol": row["Symbol"],
                "Latest Earning Period": sec_financials.get_latest_earning_period(row["Symbol"]),
                "Next Earning Date": sec_financials.get_next_earnings_date(row["Symbol"]),
            }
            for _, row in companies_df.iterrows()
        ]
        st.dataframe(pd.DataFrame(display_rows), width='stretch', hide_index=True)

# ==================================================================
# Historical Financials page
# ==================================================================
elif st.session_state.page == "historical_financials":
    st.subheader("Historical Financials")

    hist_companies_df = companies_db.load_companies()

    if hist_companies_df.empty:
        st.info("No companies in the database yet. Add some locally — see companies_db.py.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            selected_company_name = st.selectbox(
                "Company Name",
                options=hist_companies_df["Company Name"].tolist(),
            )

        company_row = hist_companies_df[hist_companies_df["Company Name"] == selected_company_name].iloc[0]
        symbol = company_row["Symbol"]
        fiscal_year_end_month = companies_db.month_number(company_row["Fiscal Year End Month"])

        with col2:
            try:
                available_years = income_statement.get_available_years(symbol)
            except Exception as e:
                available_years = []
                st.warning(f"Could not fetch filing years for {symbol}: {e}")

            if available_years:
                selected_year = st.selectbox("Beginning Financial Year", options=available_years)
            else:
                st.selectbox("Beginning Financial Year", options=["—"], disabled=True)
                selected_year = None

        st.subheader("Download")
        dl_col1, dl_col2, dl_col3 = st.columns(3)

        with dl_col1:
            if st.button("Download Income Statements", width='stretch', disabled=(selected_year is None)):
                with st.spinner(f"Extracting income statements for {symbol}..."):
                    try:
                        workbook_bytes, sheet_names = income_statement.extract_income_statements(
                            symbol, fiscal_year_end_month, selected_year
                        )
                    except Exception as e:
                        workbook_bytes, sheet_names = None, []
                        st.error(f"Extraction failed: {e}")

                if workbook_bytes:
                    st.success(f"✅ {len(sheet_names)} sheet(s) ready.")
                    st.download_button(
                        "⬇️ Download",
                        data=workbook_bytes,
                        file_name=f"{symbol}_Income_Statements.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        width='stretch',
                    )
                elif workbook_bytes is None and not sheet_names:
                    st.error("No data extracted.")

        with dl_col2:
            if st.button("Download Balance Sheets", width='stretch'):
                st.info("This section is under development.")

        with dl_col3:
            if st.button("Download Cash Flow Statements", width='stretch'):
                st.info("This section is under development.")

# ==================================================================
# Home: Select Companies -> Filing Type/Period -> Extract
# ==================================================================
else:
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

    # ---------------------------------------------------------------- Extract
    # Only appears once at least one company and its filing period is selected.
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

                income_bytes = sec_financials.build_workbook_bytes(income_sheets)
                cashflow_bytes = sec_financials.build_workbook_bytes(cashflow_sheets)
                balance_bytes = sec_financials.build_workbook_bytes(balance_sheets)

                zip_bytes = sec_financials.build_zip_bytes({
                    f"All_{filing_type}_Income.xlsx": income_bytes,
                    f"All_{filing_type}_Cashflow.xlsx": cashflow_bytes,
                    f"All_{filing_type}_BalanceSheet.xlsx": balance_bytes,
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