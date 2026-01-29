from datetime import datetime
from typing import Literal

FieldName = Literal[
    "date",
    "time",
    "timezone",
    "name",
    "description",
    "currency",
    "gross",
    "fee",
    "net",
    "balance",
    "txn_id",
    "from",
    "bank_name",
    "bank_account",
    "shipping_fee",
    "vat",
    "invoice_id",
    "reference_txn_id",
]


class Language:
    fields_map: dict[str, FieldName]
    bank_deposit_description: str
    date_format: str

    def identify(self, fields: list[str]) -> bool:
        raise NotImplementedError

    def parse_date(self, data: str) -> datetime:
        return datetime.strptime(data, self.date_format)

    def decimal(self, data: str) -> str:
        raise NotImplementedError

    def normalize_keys(self, row: dict[str, str]) -> dict[FieldName, str]:
        return {self.fields_map.get(k, k): row[k] for k in row}  # type: ignore


class de(Language):
    fields_map = {
        "Datum": "date",
        "Uhrzeit": "time",
        "Zeitzone": "timezone",
        "Beschreibung": "description",
        "Währung": "currency",
        "Brutto": "gross",
        "Entgelt": "fee",
        "Netto": "net",
        "Guthaben": "balance",
        "Transaktionscode": "txn_id",
        "Absender E-Mail-Adresse": "from",
        "Name": "name",
        "Name der Bank": "bank_name",
        "Bankkonto": "bank_account",
        "Versand- und Bearbeitungsgebühr": "shipping_fee",
        "Umsatzsteuer": "vat",
        "Rechnungsnummer": "invoice_id",
        "Zugehöriger Transaktionscode": "reference_txn_id",
    }

    def identify(self, fields: list[str]) -> bool:
        """Check if all fields are present."""
        return all(field in fields for field in self.fields_map.keys())

    date_format: str = "%d.%m.%Y"
    bank_deposit_description: str = "Bankgutschrift auf PayPal-Konto"

    def decimal(self, data: str) -> str:
        return data.replace(".", "").replace(",", ".")
