# Financial Data Extractor

A Streamlit app for pulling financial statements from SEC EDGAR and
exporting them to Excel.

## Features

- **Financial Statement Extraction** — select companies, a filing type
  (10-Q/10-K), and a period per company; extract Income Statement,
  Cash Flow Statement, and Balance Sheet as a single `.zip`.
- **Historical Financials** — pick a company and a starting fiscal
  year; download every 10-Q and 10-K income statement from that year
  to the present, one sheet per filing, in a single workbook.
- **Companies List** — read-only view of tracked companies, their
  latest reported quarter, and next expected earnings date.

## Project structure

```
financial_data_extractor/
├── app.py                          # Streamlit UI
├── sec_financials.py               # EDGAR fetching, cleaning, earnings lookups
├── companies_db.py                 # SQLite company database + CLI
├── historical_finance/
│   └── income_statement.py         # Multi-year income statement extractor
└── requirements.txt
```

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

Before running, open `sec_financials.py` and update the identity string
in `init()` — SEC EDGAR requires a name and email on every request.

## Managing companies

Companies are stored in `companies.db`, managed entirely through the
command line:

```bash
python companies_db.py
```

Add a company by symbol only — both the display name and fiscal year
end month are looked up automatically via `yfinance`. The same tool
lets you remove a company, list all companies, or refresh existing
entries.

The in-app "Companies List" page is read-only by design: Streamlit
Community Cloud's filesystem is ephemeral, so changes made through a
deployed app wouldn't persist. Update `companies.db` locally and push
it with your code.

## Deploying to Streamlit Community Cloud

1. Set up `companies.db` locally (see above).
2. Push the project, including `companies.db`, to a GitHub repo.
3. Create a new app on share.streamlit.io pointing at `app.py`.

To update the company list later, update `companies.db` locally and
push again.
