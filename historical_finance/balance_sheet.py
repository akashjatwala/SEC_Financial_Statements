"""Historical Balance Sheet Extractor (10-Q and 10-K)."""

import sec_financials
from historical_finance import utils


def fetch_balance_sheet(filing):
    return filing.xbrl().statements.balance_sheet(view="detailed").to_dataframe()


def extract_balance_sheets(symbol: str, fiscal_year_end_month: int, selected_year: int, on_progress=None):
    return utils.extract_statements(
        symbol, fiscal_year_end_month, selected_year,
        fetch_fn=fetch_balance_sheet,
        clean_fn=sec_financials.clean_balance_sheet,
        strip_ytd=False,
        on_progress=on_progress,
    )