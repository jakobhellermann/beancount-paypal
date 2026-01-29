from beangulp import testing

import beancount_paypal

testing.main(
    beancount_paypal.PaypalImporter(
        "Assets:Paypal",
        "Assets:ZeroSum:Transfers",
        "Expenses:PayPal:Commission",
        beancount_paypal.lang.de(),
        fixme_account="Expenses:FIXME",
        metadata_map={
            # "uuid": "txn_id",
            "sender": "from",
            # "time": "time",
            # "timezone": "timezone",
            # "shipping_fee": "shipping_fee",
            # "vat": "vat",
            # "invoice_id": "invoice_id",
            # "reference_txn_id": "reference_txn_id",
        },
    )
)
