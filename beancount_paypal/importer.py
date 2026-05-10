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
            normalized_rows: list[dict[lang.FieldName, Any]] = []
            for row in rows:
                normalized_rows.append(self.language.normalize_keys(row))

        # Group rows by invoice_id (Rechnungsnummer). PayPal emits a foreign-
        # currency payment as a four-row bundle sharing one invoice_id:
        #   - bank deposit (account currency)
        #   - Allgemeine Währungsumrechnung (account currency, negative)
        #   - foreign-currency Express-Zahlung
        #   - Allgemeine Währungsumrechnung (foreign currency, positive)
        # We collapse the bundle into:
        #   - the bank deposit, unchanged
        #   - the foreign payment posted with an `@` price annotation on the
        #     account-currency side, balanced against the foreign-currency
        #     amount. The two Währungsumrechnung rows are dropped (their
        #     content is captured by the price annotation).
        # This keeps the PayPal account in a single currency.
        invoice_groups: dict[str, list[int]] = {}
        for i, row in enumerate(normalized_rows):
            invoice_id = row.get("invoice_id")
            if invoice_id:
                invoice_groups.setdefault(invoice_id, []).append(i)

        forex_bundles: dict[str, dict[str, dict[lang.FieldName, Any]]] = {}
        for invoice_id, indices in invoice_groups.items():
            if len(indices) != 4:
                continue
            rows_in_group = [normalized_rows[i] for i in indices]
            currencies = {r["currency"] for r in rows_in_group}
            if len(currencies) != 2:
                continue
            conversions = [
                r
                for r in rows_in_group
                if r["description"] == self.language.currency_conversion_description
            ]
            deposits = [
                r
                for r in rows_in_group
                if r["description"] == self.language.bank_deposit_description
            ]
            payments = [
                r
                for r in rows_in_group
                if r["description"] != self.language.currency_conversion_description
                and r["description"] != self.language.bank_deposit_description
            ]
            if len(conversions) != 2 or len(deposits) != 1 or len(payments) != 1:
                continue
            payment = payments[0]
            local_conversion = next(
                r for r in conversions if r["currency"] != payment["currency"]
            )
            forex_bundles[invoice_id] = {
                "deposit": deposits[0],
                "local_conversion": local_conversion,
                "payment": payment,
            }

        skipped_indices: set[int] = set()
        for invoice_id, bundle in forex_bundles.items():
            for i in invoice_groups[invoice_id]:
                row = normalized_rows[i]
                if row["description"] == self.language.currency_conversion_description:
                    skipped_indices.add(i)

        for index, normalized in enumerate(normalized_rows):
            if index in skipped_indices:
                continue

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

            invoice_id = normalized.get("invoice_id")
            forex_bundle = (
                forex_bundles.get(invoice_id) if invoice_id else None
            )
            is_forex_payment = (
                forex_bundle is not None
                and forex_bundle["payment"] is normalized
            )

            if is_forex_payment:
                assert forex_bundle is not None
                local_conversion = forex_bundle["local_conversion"]
                # The local-currency conversion row is negative; its absolute
                # value is the EUR cost of the foreign payment.
                local_amount = abs(D(self.language.decimal(local_conversion["net"])))
                foreign_amount = D(net)
                local_currency = local_conversion["currency"]
                foreign_currency = normalized["currency"]
                # Book the entire transaction in the local currency. Preserve
                # the foreign-currency information in metadata so the original
                # amount and rate are still recoverable. This keeps reports in
                # a single currency and avoids needing per-account currency
                # restrictions or explicit price directives.
                meta["foreign_amount"] = amount.Amount(
                    abs(foreign_amount), foreign_currency
                )
                meta["forex_rate"] = (abs(foreign_amount) / local_amount).quantize(
                    D("0.000001")
                )
                txn = txn._replace(
                    meta=meta,
                    narration=(
                        f"{normalized['description']} "
                        f"({abs(foreign_amount)} {foreign_currency})"
                    ),
                )
                txn.postings.append(
                    data.Posting(
                        self.account_name,
                        amount.Amount(-local_amount, local_currency),
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
                            amount.Amount(D(fee), local_currency),
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
                            amount.Amount(local_amount, local_currency),
                            None,
                            None,
                            None,
                            None,
                        )
                    )
            elif normalized["description"] == self.language.bank_deposit_description:
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

        # Add balance assertion from the chronologically last balance-bearing
        # row. PayPal can place foreign-currency settlement rows at file end
        # even when they are dated weeks earlier; we sort by (date, time, file
        # index) so the assertion reflects the genuine end-of-period balance
        # in the account's primary currency. The file-index tiebreaker keeps
        # the natural choice when several rows share an identical timestamp.
        def _row_sort_key(item: tuple[int, dict[lang.FieldName, Any]]) -> tuple[Date, str, int]:
            i, r = item
            return (
                self.language.parse_date(r["date"]).date(),
                r.get("time", ""),
                i,
            )

        balance_rows = [
            (i, r) for i, r in enumerate(normalized_rows) if "balance" in r
        ]
        if balance_rows:
            _, balance_row = max(balance_rows, key=_row_sort_key)
            balance_date = self.language.parse_date(balance_row["date"]).date()
            meta = data.new_metadata(filepath, len(normalized_rows))
            entries.append(
                data.Balance(
                    meta,
                    balance_date + timedelta(days=1),
                    self.account_name,
                    amount.Amount(
                        D(self.language.decimal(balance_row["balance"])),
                        balance_row["currency"],
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
