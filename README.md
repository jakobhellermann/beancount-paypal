# Beancount PayPal Importer

`beancount-paypal` provides a beangulp-compatible Importer for converting German PayPal CSV exports into beancount format.

**Note:** The exporter has only been tested with current german PayPal CSV exports as of 2025.

## Usage

Configure `PaypalImporter` in your beangulp importer script:

```python
from beancount_paypal import PaypalImporter
import beancount_paypal.lang as lang

CONFIG = [
    PaypalImporter(
        account_name="Assets:Paypal",
        checking_account="Assets:Checking",
        commission_account="Expenses:PayPal:Commission",
        language=lang.de(),
        metadata_map={
            "sender": "from",
        },
        fixme_account="Expenses:FIXME",  # Optional, defaults to None
    )
]
```

### Parameters

- `account_name`: The beancount account for your PayPal balance
- `checking_account`: The account used for bank deposits to PayPal (shown as "Bankgutschrift auf PayPal-Konto")
- `commission_account`: The account for PayPal fees
- `language`: Language configuration (currently only `lang.de()` is supported)
- `metadata_map`: Map beancount metadata keys to PayPal CSV fields (uses normalized field names)
- `fixme_account`: Optional account for balancing incomplete transactions. Set to `None` to omit balancing postings.

### Available metadata fields

You can map any of these normalized field names in `metadata_map`:

- `"date"`, `"time"`, `"timezone"`
- `"name"` - Sender/recipient name
- `"description"` - Transaction type (e.g., "Zahlung im Einzugsverfahren mit Zahlungsrechnung")
- `"currency"`, `"gross"`, `"fee"`, `"net"`, `"balance"`
- `"txn_id"` - Transaction ID
- `"from"` - Sender email address
- `"shipping_fee"` - Shipping and handling fee
- `"invoice_id"` - Invoice number
- `"reference_txn_id"` - Related transaction ID

**Note:** Metadata fields are only included if they have non-empty values in the CSV.

### Export PayPal CSV

1. Go to https://www.paypal.com/reports/accountStatements
2. "Bericht erstellen", Dateiformat CSV
3. Wait a bit and download the generated CSV

## Development

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```sh
just check
```

### Testing

```sh
just test          # Run tests
just test-generate # Regenerate expected test output
just check         # Run all checks
```
