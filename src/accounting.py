"""Core double-entry accounting services for the departmental accounts system."""

from __future__ import annotations

import sqlite3
import hashlib
import secrets
import csv
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class AccountingError(ValueError):
    """Raised when an accounting transaction cannot be accepted."""


class AccountingDB:
    """Provide validated, auditable accounting operations backed by SQLite."""

    def __init__(self, path: str | Path = "data/accounting.db") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def initialize(self) -> None:
        """Create tables and the default chart of accounts if needed."""
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_no TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                account_type TEXT NOT NULL CHECK(account_type IN ('Asset','Income','Expense','Liability','Equity'))
            );
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                tax_number TEXT NOT NULL DEFAULT '', withholding_rate NUMERIC NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vouchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_no TEXT NOT NULL UNIQUE,
                voucher_type TEXT NOT NULL CHECK(voucher_type IN ('RECEIPT','PAYMENT','ADJUSTMENT')),
                voucher_date TEXT NOT NULL,
                description TEXT NOT NULL,
                student_id INTEGER REFERENCES students(id),
                supplier_id INTEGER REFERENCES suppliers(id),
                status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED','REJECTED')),
                created_by TEXT NOT NULL,
                approved_by TEXT,
                approved_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS voucher_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_id INTEGER NOT NULL REFERENCES vouchers(id),
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                debit NUMERIC NOT NULL DEFAULT 0,
                credit NUMERIC NOT NULL DEFAULT 0,
                memo TEXT NOT NULL DEFAULT '',
                CHECK ((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0))
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                details TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'CLERK', active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, kind TEXT NOT NULL,
                stored_path TEXT NOT NULL, imported_rows INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'REVIEW', uploaded_by TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS policy_heads (
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                limit_amount NUMERIC, limit_unit TEXT NOT NULL DEFAULT 'semester', notes TEXT NOT NULL DEFAULT ''
            );
            """
        )
        defaults = [
            ("1000", "Cash", "Asset"), ("1100", "Bank", "Asset"),
            ("4000", "Student Fees", "Income"), ("4100", "Other Student Income", "Income"),
            ("5000", "Teaching Materials", "Expense"), ("5100", "Office Expenses", "Expense"),
            ("5200", "Travel and Transport", "Expense"), ("5300", "Utilities", "Expense"),
            ("3000", "Department Fund", "Equity"),
            ("2100", "Income Tax Payable", "Liability"),
        ]
        self.connection.executemany("INSERT OR IGNORE INTO accounts(code,name,account_type) VALUES(?,?,?)", defaults)
        if not self.connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            self.connection.execute("INSERT INTO users(name,password_hash,role) VALUES(?,?,?)", ("clerk", self.password_hash("change-me"), "CLERK"))
        heads = [
            ("A", "Paper (up to 8 rims for 100 students)", 0, "semester", "Policy cap is 8 rims per 100 students."),
            ("B", "Stationery (except paper)", 10000, "semester", "Departmental contingency fund policy."),
            ("C", "Board of Studies, DTRC and Board of Faculty", 0, "semester", "Remuneration to external members and refreshments only."),
            ("D", "Printer toner purchase/refilling", 5000, "semester", "Revised policy limit."),
            ("E", "Generic consumables", 3000, "semester", "Cleaning items, soaps, toilet paper, etc."),
            ("F", "Other specified expenses", None, "approval", "Requires Vice Chancellor approval."),
        ]
        self.connection.executemany("INSERT OR IGNORE INTO policy_heads(code,name,limit_amount,limit_unit,notes) VALUES(?,?,?,?,?)", heads)
        try:
            self.connection.execute("ALTER TABLE vouchers ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id)")
        except sqlite3.OperationalError:
            pass
        self.connection.commit()

    @staticmethod
    def password_hash(password: str, salt: str | None = None) -> str:
        """Create a salted PBKDF2 password hash suitable for local authentication."""
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000).hex()
        return f"{salt}${digest}"

    def authenticate(self, name: str, password: str) -> dict[str, Any] | None:
        """Validate clerk credentials and return the user, without exposing the hash."""
        row = self.connection.execute("SELECT id,name,password_hash,role FROM users WHERE name=? AND active=1", (name.strip(),)).fetchone()
        if not row: return None
        salt, expected = row["password_hash"].split("$", 1)
        actual = self.password_hash(password, salt).split("$", 1)[1]
        return {"id": row["id"], "name": row["name"], "role": row["role"]} if secrets.compare_digest(actual, expected) else None

    def add_supplier(self, name: str, tax_number: str = "", withholding_rate: Any = 0) -> int:
        """Register a supplier and its income-tax withholding rate percentage."""
        if not name.strip(): raise AccountingError("Supplier name is required")
        rate = Decimal(str(withholding_rate or 0))
        if rate < 0 or rate > 100: raise AccountingError("Tax rate must be between 0 and 100")
        try:
            cur = self.connection.execute("INSERT INTO suppliers(name,tax_number,withholding_rate,created_at) VALUES(?,?,?,?)", (name.strip(), tax_number.strip(), str(rate), datetime.utcnow().isoformat()))
            self.connection.commit(); return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc: raise AccountingError("Supplier already exists") from exc

    def suppliers(self) -> list[dict[str, Any]]:
        """Return registered suppliers."""
        return [dict(x) for x in self.connection.execute("SELECT id,name,tax_number,withholding_rate FROM suppliers ORDER BY name").fetchall()]

    def upload(self, filename: str, kind: str, content: bytes, actor: str) -> dict[str, Any]:
        """Retain an uploaded bank/income document and count CSV/XLSX data rows."""
        if kind not in {"BANK", "INCOME"}: raise AccountingError("Upload type must be BANK or INCOME")
        safe = Path(filename).name
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        target = Path(self.path).parent / "uploads" / f"{stamp}_{safe}"
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
        rows = self._count_import_rows(safe, content)
        cur = self.connection.execute("INSERT INTO uploads(filename,kind,stored_path,imported_rows,uploaded_by,created_at) VALUES(?,?,?,?,?,?)", (safe, kind, str(target), rows, actor, datetime.utcnow().isoformat()))
        self._audit("UPLOAD", "document", int(cur.lastrowid), f"{kind}: {safe}; {rows} rows detected", actor)
        self.connection.commit(); return {"id": cur.lastrowid, "filename": safe, "kind": kind, "rows": rows, "status": "REVIEW"}

    @staticmethod
    def _count_import_rows(filename: str, content: bytes) -> int:
        """Count data rows in CSV or basic XLSX files; PDFs remain review-only."""
        suffix = Path(filename).suffix.lower()
        if suffix == ".csv": return max(0, sum(1 for _ in csv.reader(io.StringIO(content.decode("utf-8-sig", errors="replace")))) - 1)
        if suffix == ".xlsx":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as book:
                    xml = book.read("xl/worksheets/sheet1.xml")
                return max(0, len(ET.fromstring(xml).findall(".//{*}row")) - 1)
            except (KeyError, ET.ParseError, zipfile.BadZipFile): return 0
        return 0

    def close(self) -> None:
        """Close the database connection."""
        self.connection.close()

    @staticmethod
    def money(value: Any) -> str:
        """Normalize a numeric amount to two decimal places."""
        try:
            amount = Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            raise AccountingError("Amount must be a valid number")
        if amount <= 0:
            raise AccountingError("Amount must be greater than zero")
        return str(amount)

    def account_id(self, code: str) -> int:
        """Return an account id for a chart-of-accounts code."""
        row = self.connection.execute("SELECT id FROM accounts WHERE code=?", (code,)).fetchone()
        if not row:
            raise AccountingError(f"Unknown account code: {code}")
        return int(row[0])

    def add_student(self, student_no: str, name: str, department: str = "") -> int:
        """Create a student record and return its id."""
        if not student_no.strip() or not name.strip():
            raise AccountingError("Student number and name are required")
        try:
            cursor = self.connection.execute("INSERT INTO students(student_no,name,department,created_at) VALUES(?,?,?,?)", (student_no.strip(), name.strip(), department.strip(), datetime.utcnow().isoformat()))
            self.connection.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise AccountingError("Student number already exists") from exc

    def create_voucher(self, voucher_type: str, voucher_date: str, description: str, lines: list[dict[str, Any]], actor: str, student_id: int | None = None, supplier_id: int | None = None) -> int:
        """Create a balanced pending voucher; it has no report effect until approved."""
        if voucher_type not in {"RECEIPT", "PAYMENT", "ADJUSTMENT"} or not description.strip():
            raise AccountingError("Voucher type and description are required")
        if not lines or len(lines) < 2:
            raise AccountingError("A voucher requires at least two lines")
        debit = sum(Decimal(self.money(line.get("debit", 0))) if line.get("debit") else Decimal("0") for line in lines)
        credit = sum(Decimal(self.money(line.get("credit", 0))) if line.get("credit") else Decimal("0") for line in lines)
        if debit != credit:
            raise AccountingError("Debits and credits must balance")
        stamp = datetime.utcnow().isoformat()
        if voucher_type == "PAYMENT" and supplier_id:
            supplier = self.connection.execute("SELECT withholding_rate FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
            if not supplier: raise AccountingError("Supplier not found")
            gross = debit
            tax = (gross * Decimal(str(supplier[0] or 0)) / Decimal("100")).quantize(Decimal("0.01"))
            if tax:
                lines = list(lines)
                lines[-1] = dict(lines[-1], credit=str(gross - tax))
                lines.append({"account": "2100", "credit": str(tax), "memo": "Income-tax withholding"})
        try:
            cursor = self.connection.execute("INSERT INTO vouchers(voucher_no,voucher_type,voucher_date,description,student_id,supplier_id,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)", (f"{voucher_type[:3]}-{stamp.replace('-', '').replace(':', '').replace('.', '')}", voucher_type, voucher_date or date.today().isoformat(), description.strip(), student_id, supplier_id, actor.strip() or "system", stamp))
            voucher_id = int(cursor.lastrowid)
            for line in lines:
                debit_value = self.money(line["debit"]) if line.get("debit") else "0"
                credit_value = self.money(line["credit"]) if line.get("credit") else "0"
                self.connection.execute("INSERT INTO voucher_lines(voucher_id,account_id,debit,credit,memo) VALUES(?,?,?,?,?)", (voucher_id, self.account_id(line["account"]), debit_value, credit_value, line.get("memo", "")))
            self._audit("CREATE", "voucher", voucher_id, description, actor)
            self.connection.commit()
            return voucher_id
        except Exception:
            self.connection.rollback()
            raise

    def approve_voucher(self, voucher_id: int, approver: str) -> None:
        """Approve a pending voucher and write the approval to the audit trail."""
        if not approver.strip():
            raise AccountingError("An approving person is required")
        row = self.connection.execute("SELECT status FROM vouchers WHERE id=?", (voucher_id,)).fetchone()
        if not row:
            raise AccountingError("Voucher not found")
        if row[0] != "PENDING":
            raise AccountingError("Only pending vouchers can be approved")
        now = datetime.utcnow().isoformat()
        self.connection.execute("UPDATE vouchers SET status='APPROVED',approved_by=?,approved_at=? WHERE id=?", (approver.strip(), now, voucher_id))
        self._audit("APPROVE", "voucher", voucher_id, "Human approval recorded", approver)
        self.connection.commit()

    def _audit(self, action: str, entity: str, entity_id: int, details: str, actor: str) -> None:
        self.connection.execute("INSERT INTO audit_log(action,entity,entity_id,details,actor,created_at) VALUES(?,?,?,?,?,?)", (action, entity, entity_id, details, actor or "system", datetime.utcnow().isoformat()))

    def dashboard(self) -> dict[str, Any]:
        """Return approved totals and pending-work counts for the dashboard."""
        def total(sql: str) -> float:
            return float(self.connection.execute(sql).fetchone()[0] or 0)
        return {"income": total("SELECT COALESCE(SUM(l.credit-l.debit),0) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id WHERE v.status='APPROVED' AND a.account_type='Income'"), "expenses": total("SELECT COALESCE(SUM(l.debit-l.credit),0) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id WHERE v.status='APPROVED' AND a.account_type='Expense'"), "cash": total("SELECT COALESCE(SUM(l.debit-l.credit),0) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id WHERE v.status='APPROVED' AND a.code='1000'"), "pending": self.connection.execute("SELECT COUNT(*) FROM vouchers WHERE status='PENDING'").fetchone()[0]}

    def rows(self, report: str) -> list[dict[str, Any]]:
        """Return approved cash-book or ledger rows."""
        if report == "cash":
            where = "a.code='1000'"
        else:
            where = "1=1"
        return [dict(row) for row in self.connection.execute(f"SELECT v.voucher_no,v.voucher_date,v.voucher_type,v.description,a.code,a.name,l.debit,l.credit,v.status FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id WHERE v.status='APPROVED' AND {where} ORDER BY v.voucher_date,v.id,l.id DESC").fetchall()]

    def pending(self) -> list[dict[str, Any]]:
        """Return pending vouchers for human review."""
        return [dict(row) for row in self.connection.execute("SELECT id,voucher_no,voucher_type,voucher_date,description,created_by FROM vouchers WHERE status='PENDING' ORDER BY id DESC").fetchall()]

    def students(self) -> list[dict[str, Any]]:
        """Return student records for the income form."""
        return [dict(row) for row in self.connection.execute("SELECT id,student_no,name,department FROM students ORDER BY name").fetchall()]