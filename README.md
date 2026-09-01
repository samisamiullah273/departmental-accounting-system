# Departmental Accounting System

A local, reproducible departmental accounting application for student receipts and controlled expenditures. It implements double-entry vouchers, approval-before-posting, a cash book, a general ledger view, and an audit log.

## Included workflows

- Student master records and student-fee receipt vouchers.
- Payment vouchers for teaching materials, office costs, travel, and utilities.
- A chart of accounts with cash, bank, income, expense, and fund accounts.
- Balanced debit/credit validation on every voucher.
- Human approval queue: pending transactions do not affect income, expense, cash book, or ledger totals.
- Immutable transaction history in SQLite (records are not deleted by the UI) and audit events for creation/approval.
- Dashboard totals and browser-based cash book/general-ledger views.
- Clerk login with salted PBKDF2 password storage and HttpOnly session cookies (development account: `clerk` / `change-me`; change this before use).
- Supplier master data and configurable income-tax withholding, posted to `Income Tax Payable`.
- Policy heads transcribed from the supplied notification: paper, stationery, Boards/DTRC/Faculty, toner, generic consumables, and other expenses requiring approval.
- Bank-statement and income/receipt document retention for CSV, XLSX, and PDF uploads. CSV/XLSX row counts are detected; source documents remain review-only until a human posts them.

## Run on Windows

```powershell
python -m venv venv
.\venv\Scripts\activate
python -m src.app
```

Open <http://127.0.0.1:8000>. The first run creates `data/accounting.db`. To reset a development database, stop the server and remove that file after human confirmation.

## Development setup in VS Code

Install Microsoft Python, Jupyter, and Pylance extensions; install Markdown All in One when a written report is needed. Select `venv` using **Python: Select Interpreter**. The project uses only the Python standard library, so `requirements.txt` is intentionally empty of packages. Keep analysis notebooks in `notebooks/` and reusable code in `src/`.

## Accounting controls and limitations

This is a functional local foundation, not a jurisdiction-specific certified accounting package. The supplied notification was transcribed into policy-head metadata, but its legal/accounting interpretation and tax rates must be confirmed by the department. Configure fiscal periods, stronger production secrets, user administration, backups, bank reconciliation, exports, and local retention requirements before production use. Uploaded bank and receipt documents are deliberately not auto-posted; a human must review and create balanced vouchers.

## Suggested extension roadmap

Add authenticated roles (clerk/approver/auditor), supplier and budget modules, adjustment-voucher form, period closing, PDF/CSV reports, automated backups, and a deployment database. Any production deployment should receive explicit human authorization and an accounting review.