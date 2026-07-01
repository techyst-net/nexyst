# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.report.incorrect_balance_qty_after_transaction.incorrect_balance_qty_after_transaction import (
	execute,
)
from erpnext.tests.utils import ERPNextTestSuite

WAREHOUSE = "Stores - _TC"
COMPANY = "_Test Company"


class TestIncorrectBalanceQtyAfterTransaction(ERPNextTestSuite):
	def run_report(self, **extra):
		filters = frappe._dict({"company": COMPANY, "warehouse": WAREHOUSE})
		filters.update(extra)
		return execute(filters)[1]

	def test_healthy_stock_not_flagged(self):
		item = "_Test Item"
		make_stock_entry(item_code=item, to_warehouse=WAREHOUSE, qty=10, rate=100, posting_date="2026-06-01")
		make_stock_entry(item_code=item, from_warehouse=WAREHOUSE, qty=4, rate=100, posting_date="2026-06-02")

		data = self.run_report(item_code=item)
		flagged = [row for row in data if row.get("item_code") == item]
		self.assertEqual(flagged, [])

	def test_sequence_of_movements_not_flagged(self):
		item = "_Test Item 2"
		make_stock_entry(item_code=item, to_warehouse=WAREHOUSE, qty=20, rate=50, posting_date="2026-06-01")
		make_stock_entry(item_code=item, from_warehouse=WAREHOUSE, qty=5, rate=50, posting_date="2026-06-02")
		make_stock_entry(item_code=item, to_warehouse=WAREHOUSE, qty=8, rate=50, posting_date="2026-06-03")
		make_stock_entry(item_code=item, from_warehouse=WAREHOUSE, qty=3, rate=50, posting_date="2026-06-04")

		data = self.run_report(item_code=item)
		flagged = [row for row in data if row.get("item_code") == item]
		self.assertEqual(flagged, [])
