from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from io import BytesIO
from typing import Any

import pandas as pd


@dataclass
class Transaction:
    date: date | str
    description: str
    amount: float
    bank: str
    source_file: str
    category: str
    confidence: str
    flag: str


@dataclass
class ParseResult:
    filename: str
    bank: str
    transactions: list[Transaction]
    warnings: list[str]
    safety_ok: bool | None
    parser: str


DINING_SIGNALS = (
    "food",
    "foodcou",
    "korean food",
    "malay food",
    "muslim",
    "fruit",
    "restaurant",
    "cafe",
    "coffee",
    "breadtalk",
    "kfc",
    "ramen",
    "delibowl",
    "luckin",
    "milan shokudo",
    "hainanes",
)

TRANSFER_SIGNALS = (
    "top up wallet",
    "top-up to paylah",
    "send money",
    "paynow transfer",
    "payment received",
    "incoming payment",
    "cash rebate",
    "funds transfer",
    "i-bank transfer",
    "fast payment",
    "giro",
)

PAYMENT_PROCESSORS = (
    "fomo pay",
    "qashier",
    "paynow",
    "sgqr",
    "grabpay",
    "nets",
    "stripe",
    "adyen",
    "paypal",
)


def parse_pdf_statement(
    filename: str,
    file_bytes: bytes,
    password: str | None = None,
    big_item_threshold: float = 500.0,
    allow_ocr: bool = True,
) -> ParseResult:
    """Parse a statement using monopoly-core when available, with a local fallback."""
    try:
        return _parse_with_monopoly(filename, file_bytes, password, big_item_threshold, allow_ocr)
    except ImportError as exc:
        result = _parse_with_fallback(filename, file_bytes, password, big_item_threshold)
        result.warnings.insert(
            0,
            "monopoly-core is not installed in this environment; used fallback parser. "
            "Install requirements.txt for StatementSensei-style bank detection.",
        )
        result.warnings.append(str(exc))
        return result


def results_to_dataframe(results: list[ParseResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        rows.extend(asdict(tx) for tx in result.transactions)
    if not rows:
        return pd.DataFrame(
            columns=["date", "description", "amount", "bank", "source_file", "category", "confidence", "flag"]
        )
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df.sort_values(["date", "source_file", "description"], na_position="last").reset_index(drop=True)


def _parse_with_monopoly(
    filename: str,
    file_bytes: bytes,
    password: str | None,
    big_item_threshold: float,
    allow_ocr: bool,
) -> ParseResult:
    from monopoly.banks import BankDetector, banks
    from monopoly.generic import GenericBank
    from monopoly.pdf import MissingOCRError, PdfDocument, PdfParser
    from monopoly.pipeline import Pipeline
    from monopoly.statements.base import SafetyCheckError
    from pydantic import SecretStr

    document = PdfDocument(file_bytes=file_bytes)
    document._name = filename
    warnings: list[str] = []

    if document.is_encrypted:
        if not password:
            return ParseResult(filename, "Encrypted", [], ["Password required."], None, "monopoly-core")
        document.authenticate(password)
        if document.is_encrypted:
            return ParseResult(filename, "Encrypted", [], ["Password is incorrect."], None, "monopoly-core")

    def build_pipeline(doc: Any) -> tuple[Any, Any]:
        analyzer = BankDetector(doc)
        bank = analyzer.detect_bank(banks) or GenericBank
        parser = PdfParser(bank, doc)
        pipeline = Pipeline(parser, passwords=[SecretStr(password)] if password else [])
        return pipeline, parser

    try:
        pipeline, parser = build_pipeline(document)
    except MissingOCRError:
        if not allow_ocr:
            return ParseResult(filename, "Unknown", [], ["No text found. OCR is required."], None, "monopoly-core")
        analyzer = BankDetector(document)
        bank = analyzer.detect_bank(banks) or GenericBank
        if cropbox := bank.pdf_config.page_bbox:
            for page in document:
                page.set_cropbox(cropbox)
        document = PdfParser.apply_ocr(document)
        pipeline, parser = build_pipeline(document)
        warnings.append("No text found initially; OCR layer was applied.")

    statement = pipeline.extract(safety_check=False)
    bank_name = parser.bank.__name__
    safety_ok: bool | None = None

    if statement.config.safety_check:
        try:
            statement.perform_safety_check()
            safety_ok = True
        except SafetyCheckError:
            safety_ok = False
            warnings.append("Safety check failed; transactions may be incorrect or incomplete.")
    else:
        warnings.append(f"{bank_name} {statement.config.statement_type} has no safety check; review totals.")

    if bank_name == "GenericBank":
        warnings.append("Unrecognized bank; used GenericBank parser.")

    transformed = pipeline.transform(statement)
    transactions = [
        _transaction_from_mapping(row, bank_name, filename, big_item_threshold)
        for row in transformed
        if row.get("date") and row.get("description") and row.get("amount") is not None
    ]
    return ParseResult(filename, bank_name, transactions, warnings, safety_ok, "monopoly-core")


def _parse_with_fallback(
    filename: str,
    file_bytes: bytes,
    password: str | None,
    big_item_threshold: float,
) -> ParseResult:
    from pypdf import PdfReader

    warnings: list[str] = []
    reader = PdfReader(BytesIO(file_bytes))
    if reader.is_encrypted:
        decrypted = 0
        try:
            decrypted = reader.decrypt("")
        except Exception:
            pass
        if decrypted == 0 and not password:
            return ParseResult(filename, "Encrypted", [], ["Password required."], None, "pypdf-fallback")
        if decrypted == 0 and reader.decrypt(password) == 0:
            return ParseResult(filename, "Encrypted", [], ["Password is incorrect."], None, "pypdf-fallback")

    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ParseResult(
            filename,
            "Unknown",
            [],
            ["No extractable text found. This is likely scanned/image-only; OCR is required."],
            None,
            "pypdf-fallback",
        )

    bank = _detect_fallback_bank(lines)
    rows = _parse_citi_lines(lines) if bank == "Citibank" else _parse_dbs_ledger_lines(lines)
    if not rows:
        rows = _parse_generic_lines(lines)
        bank = bank if bank != "Unknown" else "Generic"

    transactions = [
        _transaction_from_mapping(row, bank, filename, big_item_threshold)
        for row in rows
        if row.get("description") and row.get("amount") is not None
    ]
    return ParseResult(filename, bank, transactions, warnings, None, "pypdf-fallback")


def _transaction_from_mapping(
    row: dict[str, Any],
    bank: str,
    source_file: str,
    big_item_threshold: float,
) -> Transaction:
    amount = float(row["amount"])
    category, confidence = categorize(row.get("description", ""), amount)
    flag = "Big item" if amount > 0 and abs(amount) >= big_item_threshold else ""
    return Transaction(
        date=row["date"],
        description=str(row["description"]).strip(),
        amount=round(amount, 2),
        bank=bank,
        source_file=source_file,
        category=category,
        confidence=confidence,
        flag=flag,
    )


def categorize(description: str, amount: float = 0) -> tuple[str, str]:
    text = description.lower()
    if any(signal in text for signal in TRANSFER_SIGNALS) or amount < 0 and any(
        word in text for word in ("payment", "rebate", "refund", "credit")
    ):
        return "Transfers", "High"
    processor = any(signal in text for signal in PAYMENT_PROCESSORS)
    if any(signal in text for signal in DINING_SIGNALS) or re.search(r"paynow\s*fomo\s*pay\s*p", text):
        return "Dining", "Medium" if processor else "High"
    if any(signal in text for signal in ("bus/mrt", "transit", "taxi", "grab", "parking", "petrol", "shell")):
        return "Transport", "High"
    if any(signal in text for signal in ("apple.com", "amazon", "shop", "store", "mall")):
        return "Shopping", "High"
    if processor:
        return "Other", "Low"
    return "Other", "Low"


def _detect_fallback_bank(lines: list[str]) -> str:
    joined = "\n".join(lines[:80]).lower()
    if "citibank" in joined or "citi cash back" in joined:
        return "Citibank"
    if "dbs bank" in joined or "posb" in joined or "paylah" in joined:
        return "DBS/POSB"
    return "Unknown"


def _parse_citi_lines(lines: list[str]) -> list[dict[str, Any]]:
    rows = []
    date_re = re.compile(r"^(\d{1,2})\s*([A-Z]{3})\s+(.+?)\s+(\(?[\d,]+\.\d{2}\)?)$", re.I)
    for line in lines:
        match = date_re.match(_normalize_compact_month_line(line))
        if not match:
            continue
        day, month_name, description, raw_amount = match.groups()
        rows.append(
            {
                "date": _date_from_day_month(day, month_name),
                "description": description.strip(),
                "amount": parse_amount(raw_amount),
            }
        )
    return rows


def _parse_dbs_ledger_lines(lines: list[str]) -> list[dict[str, Any]]:
    rows = []
    current_balance: float | None = None
    pending: dict[str, Any] | None = None
    date_re = re.compile(r"^(\d{1,2}/\d{1,2}/\d{4})\s+(.+)$")

    for line in lines:
        balance = re.search(r"balance\s+(?:brought|carried)\s+forward\b.*?([\d,]+\.\d{2}-?)\s*$", line, re.I)
        if balance:
            current_balance = parse_amount(balance.group(1))
            continue

        date_match = date_re.match(line)
        if date_match:
            description = date_match.group(2)
            tokens = _money_tokens(description)
            if len(tokens) >= 2 and current_balance is not None:
                amount = abs(tokens[0])
                next_balance = tokens[-1]
                signed = amount if next_balance < current_balance else -amount
                rows.append(
                    {
                        "date": _normalize_slash_date(date_match.group(1)),
                        "description": re.sub(r"[\d,]+\.\d{2}-?\s+[\d,]+\.\d{2}-?\s*$", "", description).strip(),
                        "amount": signed,
                    }
                )
                current_balance = next_balance
                pending = None
            else:
                pending = {"date": _normalize_slash_date(date_match.group(1)), "description": description}
            continue

        if not pending:
            continue

        tokens = _money_tokens(line)
        if len(tokens) >= 2 and current_balance is not None:
            amount = abs(tokens[0])
            next_balance = tokens[-1]
            signed = amount if next_balance < current_balance else -amount
            rows.append(
                {
                    "date": pending["date"],
                    "description": pending["description"].strip(),
                    "amount": signed,
                }
            )
            current_balance = next_balance
            pending = None
        else:
            pending["description"] = f"{pending['description']} {line}".strip()
    return rows


def _parse_generic_lines(lines: list[str]) -> list[dict[str, Any]]:
    rows = []
    date_re = re.compile(
        r"^\s*(\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{1,2}\s*[A-Z]{3,9})\s+(.+?)\s+(\(?[\d,]+\.\d{2}\)?(?:\s*(?:CR|DR|DB))?)$",
        re.I,
    )
    for line in lines:
        match = date_re.match(_normalize_compact_month_line(line))
        if not match:
            continue
        raw_date, description, amount = match.groups()
        rows.append({"date": _normalize_date(raw_date), "description": description, "amount": parse_amount(amount)})
    return rows


def parse_amount(value: str) -> float:
    raw = str(value).strip()
    negative = raw.endswith("-") or raw.startswith("(") or "CR" in raw.upper()
    cleaned = re.sub(r"[^\d.]", "", raw)
    amount = float(cleaned) if cleaned else 0.0
    return -amount if negative else amount


def _money_tokens(line: str) -> list[float]:
    return [parse_amount(match.group(0)) for match in re.finditer(r"[\d,]+\.\d{2}-?", line)]


def _normalize_compact_month_line(line: str) -> str:
    return re.sub(r"^(\d{1,2})([A-Z]{3})(?=[A-Z0-9])", r"\1 \2 ", line.strip(), flags=re.I)


def _date_from_day_month(day: str, month_name: str) -> date:
    months = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    return date(2026, months[month_name[:3].lower()], int(day))


def _normalize_slash_date(raw: str) -> date:
    day, month, year = [int(part) for part in raw.split("/")]
    return date(year, month, day)


def _normalize_date(raw: str) -> date | str:
    raw = raw.strip()
    if re.match(r"\d{1,2}\s*[A-Z]{3,9}$", raw, re.I):
        match = re.match(r"(\d{1,2})\s*([A-Z]{3,9})", raw, re.I)
        if match:
            return _date_from_day_month(match.group(1), match.group(2))
    if re.match(r"\d{1,2}/\d{1,2}/\d{2,4}$", raw):
        return _normalize_slash_date(raw if len(raw.rsplit("/", 1)[-1]) == 4 else raw.rsplit("/", 1)[0] + "/2026")
    return raw
