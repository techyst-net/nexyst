# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.stock.doctype.item.test_item import make_item
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
		item = make_item(properties={"is_stock_item": 1}).name

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

	def run_report(self, **extra):
		filters = {"company": COMPANY, "as_on_date": "2026-12-31"}
		filters.update(extra)
		return execute(frappe._dict(filters))[1]
