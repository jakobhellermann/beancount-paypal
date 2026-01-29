import csv
import mimetypes
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date as Date
from datetime import timedelta
from typing import Any, cast

from beancount.core import amount, data, flags
from beancount.core.number import D
from beangulp import Importer

from . import lang


@contextmanager
def csv_open(filename: str) -> Iterator[csv.DictReader]:
    with open(filename, newline="", encoding="utf-8-sig") as f:
        yield csv.DictReader(f, quotechar='"')


class PaypalImporter(Importer):
    def __init__(
        self,
        account_name: str,
        checking_account: str,
        commission_account: str,
        language: lang.Language,
        metadata_map: dict[str, lang.FieldName],
        fixme_account: str | None = None,
    ) -> None:
        self.account_name: str = account_name
        self.checking_account: str = checking_account
        self.commission_account: str = commission_account
        self.language: lang.Language = language
        self.metadata_map: dict[str, lang.FieldName] = metadata_map
        self.fixme_account: str | None = fixme_account

    def account(self, filepath: str) -> str:
        return self.account_name

    def identify(self, filepath: str) -> bool:
        filepath = cast(str, filepath.name) if hasattr(filepath, "name") else filepath

        if mimetypes.guess_type(filepath)[0] != "text/csv":
            return False

        with csv_open(filepath) as rows:
            try:
                row = next(rows)
                return self.language.identify(list(row.keys()))
            except StopIteration:
                return False

    def extract(
        self, filepath: str, existing: list | None = None
    ) -> list[data.Directive]:
        entries: list[data.Directive] = []

        with csv_open(filepath) as rows:
            for index, row in enumerate(rows):
                normalized: dict[lang.FieldName, Any] = self.language.normalize_keys(
                    row
                )

                # Parse decimal fields
                txn_date: Date = self.language.parse_date(normalized["date"]).date()
                gross: str = self.language.decimal(normalized["gross"])
                fee: str = self.language.decimal(normalized["fee"])
                net: str = self.language.decimal(normalized["net"])

                # Parse decimal fields in normalized row for metadata
                if "vat" in normalized:
                    normalized["vat"] = self.language.decimal(normalized["vat"])
                if "shipping_fee" in normalized:
                    normalized["shipping_fee"] = self.language.decimal(
                        normalized["shipping_fee"]
                    )

                metadata = {
                    k: normalized[v]
                    for k, v in self.metadata_map.items()
                    if v in normalized and normalized[v]
                }

                meta = data.new_metadata(filepath, index, metadata)

                txn = data.Transaction(
                    meta=meta,
                    date=txn_date,
                    flag=flags.FLAG_OKAY,
                    payee=normalized["name"],
                    narration=normalized["description"],
                    tags=frozenset(),
                    links=frozenset(),
                    postings=[],
                )

                if normalized["description"] == self.language.bank_deposit_description:
                    # Bank deposit: money from checking to PayPal (balanced)
                    txn.postings.extend(
                        [
                            data.Posting(
                                self.checking_account,
                                amount.Amount(-1 * D(gross), normalized["currency"]),
                                None,
                                None,
                                None,
                                None,
                            ),
                            data.Posting(
                                self.account_name,
                                amount.Amount(D(net), normalized["currency"]),
                                None,
                                None,
                                None,
                                None,
                            ),
                        ]
                    )
                else:
                    # Other transactions: incomplete, add balancing FIXME posting if configured
                    txn.postings.append(
                        data.Posting(
                            self.account_name,
                            amount.Amount(D(net), normalized["currency"]),
                            None,
                            None,
                            None,
                            None,
                        )
                    )
                    if D(fee) != 0:
                        txn.postings.append(
                            data.Posting(
                                self.commission_account,
                                amount.Amount(D(fee), normalized["currency"]),
                                None,
                                None,
                                None,
                                None,
                            )
                        )
                    if self.fixme_account:
                        txn.postings.append(
                            data.Posting(
                                self.fixme_account,
                                None,  # Auto-balanced by beancount
                                None,
                                None,
                                None,
                                None,
                            )
                        )

                entries.append(txn)

        # Add balance assertion from the last row if it has a balance field
        if "balance" in normalized:
            meta = data.new_metadata(filepath, index + 1)
            entries.append(
                data.Balance(
                    meta,
                    txn_date + timedelta(days=1),
                    self.account_name,
                    amount.Amount(
                        D(self.language.decimal(normalized["balance"])),
                        normalized["currency"],
                    ),
                    None,
                    None,
                )
            )

        return entries

    def date(self, filepath: str) -> Date | None:
        """Return the date associated with this file."""
        try:
            entries = self.extract(filepath)
            if entries:
                return max(entry.date for entry in entries if hasattr(entry, "date"))
        except Exception:
            pass
        return None

    def filename(self, filepath: str) -> str | None:
        """Return the archival filename for the given file."""
        return "paypal.csv"
