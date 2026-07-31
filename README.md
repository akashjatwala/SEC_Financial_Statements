# Financial Data Extractor

## Structure

```
financial_data_extractor/
├── app.py                          # UI + orchestration (Home / Historical Financials / Companies List)
├── sec_financials.py               # SEC EDGAR: identity, filing lookup, cleaning, earnings-date lookup
├── companies_db.py                 # SQLite-backed company list — managed locally via CLI
├── historical_finance/
│   └── income_statement.py         # Multi-year 10-Q/10-K income statement extractor
└── requirements.txt
```

## Companies database

Companies live in a local SQLite file, `companies.db` (schema:
`symbol` as primary key, `company_name` — no separate id column, since
symbol is already unique), auto-created on first run via
`companies_db.init_db()` (called from `sec_financials.init()`).

**Managed entirely from the command line — not through the Streamlit
UI.** The "Companies List" sidebar page is read-only. This is
deliberate: once deployed to Streamlit Community Cloud, the server's
filesystem is ephemeral, so writes made through a running app wouldn't
persist anyway. Manage the list locally instead:

```bash
python companies_db.py
```
This opens an interactive menu — list, add, or remove a company by
following the numbered prompts.

Then push the updated `companies.db` alongside your code, or upload it
directly if deploying separately from git.

## Companies List page (in-app)

Read-only table: Company Name, Symbol, Latest Earning Period (most
recent reported quarter), and Next Earning Date (upcoming earnings
date) — both looked up live via `yfinance`, cached for an hour. Shows
`-` for either column if that data isn't available for the symbol.

## Navigation

Sidebar has three entries:
- **Home** — the main flow (Select Companies → Filing Type/Period → Extract).
  Extraction pulls Income Statement, Cash Flow Statement, and Balance
  Sheet for each selected filing, bundled into one `.zip`.
- **Historical Financials** — pick a company (from the database) and a
  starting fiscal year, then download a multi-year Income Statement
  workbook: one sheet per 10-Q/10-K filing from that year onward,
  sorted newest to oldest (`historical_finance/income_statement.py`).
  Balance Sheet and Cash Flow Statement downloads are placeholders for
  now — clicking either just shows "under development".
- **Companies List** — view companies + their latest/next earnings info.

## Local setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

`historical_finance/income_statement.py` can also be run standalone,
independent of the app, for testing:
```bash
python historical_finance/income_statement.py
```

**Before running**, open `sec_financials.py` and change the
`set_identity(...)` line inside `init()` to your own name and email —
SEC EDGAR requires this on every request.

## Deploying to Streamlit Community Cloud

1. Manage `companies.db` locally first (see above), so it already has
   the companies you want before deploying.
2. Push this folder — including `companies.db` — to a GitHub repo.
3. On share.streamlit.io, create a new app pointing at `app.py`.
4. Deploy.

To update the company list later, update `companies.db` locally and
push again — the deployed app can't write to it directly.

## Downloading files

There's no local-folder-picker on Cloud (the server has no access to
your filesystem, and no display to pop up a native dialog). Instead,
after extraction you get one `⬇️ Download` button — clicking it hands
a `.zip` to your browser, which saves it to your Downloads folder or
prompts you for a location, exactly like downloading anything else
from a website. This works the same way whether you're running locally
or on Cloud.# SEC_Financial_Statements
