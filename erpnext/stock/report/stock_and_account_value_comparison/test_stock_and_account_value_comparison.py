# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.doctype.warehouse.test_warehouse import create_warehouse
from erpnext.stock.report.stock_and_account_value_comparison.stock_and_account_value_comparison import (
	execute,
)
from erpnext.tests.utils import ERPNextTestSuite

COMPANY = "_Test Company with perpetual inventory"


class TestStockAndAccountValueComparison(ERPNextTestSuite):
	def test_balanced_warehouse_not_flagged(self):
		warehouse = create_warehouse("_Test SAVC WH", company=COMPANY)
		account = frappe.get_value("Warehouse", warehouse, "account")
		item = "_Test Item"

		make_stock_entry(
			item_code=item,
			to_warehouse=warehouse,
			qty=10,
			rate=100,
			company=COMPANY,
			posting_date="2026-06-01",
		)

		# Filtering by the isolated account restricts both the stock-ledger and GL
		# scans to this fresh warehouse's account only.
		rows = self.run_report(account=account)

		# The report lists only mismatches (rows where abs(difference_value) > 0.1),
		# keyed per voucher. A balanced perpetual warehouse posts equal stock-ledger
		# and GL values for the receipt voucher, so nothing should be flagged.
		self.assertEqual(rows, [])

	def test_stock_account_gl_mismatch_is_flagged(self):
		warehouse = create_warehouse("_Test SAVC Mismatch WH", company=COMPANY)
		account = frappe.get_value("Warehouse", warehouse, "account")

		receipt = make_stock_entry(
			item_code="_Test Item",
			to_warehouse=warehouse,
			qty=10,
			rate=100,
			company=COMPANY,
			posting_date="2026-06-01",
		)

		# Simulate corruption: the stock-account GL entry for this receipt drifts out of sync
		# with the stock ledger (stock value stays 1000, but the account only shows 600).
		frappe.db.set_value(
			"GL Entry",
			{"voucher_no": receipt.name, "account": account, "is_cancelled": 0},
			"debit_in_account_currency",
			600,
			update_modified=False,
		)

		rows = self.run_report(account=account)

		row = next(r for r in rows if r["voucher_no"] == receipt.name)
		self.assertEqual(row["ledger_type"], "Stock Ledger Entry")
		self.assertEqual(row["stock_value"], 1000)  # unchanged stock ledger value
		self.assertEqual(row["account_value"], 600)  # tampered GL value
		self.assertEqual(row["difference_value"], 400)  # 1000 - 600, above the 0.1 threshold

	def run_report(self, **extra):
		filters = {"company": COMPANY, "as_on_date": "2026-12-31"}
		filters.update(extra)
		return execute(frappe._dict(filters))[1]
