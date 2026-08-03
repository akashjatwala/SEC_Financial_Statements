"""Historical Cash Flow Statement Extractor (10-Q and 10-K)."""

import sec_financials
from historical_finance import utils


def fetch_cashflow_statement(filing):
    return filing.xbrl().statements.cashflow_statement(view="detailed").to_dataframe()


def extract_cashflow_statements(symbol: str, fiscal_year_end_month: int, selected_year: int, on_progress=None):
    return utils.extract_statements(
        symbol, fiscal_year_end_month, selected_year,
        fetch_fn=fetch_cashflow_statement,
        clean_fn=sec_financials.clean_cashflow_statement,
        strip_ytd=False,
        on_progress=on_progress,
    )