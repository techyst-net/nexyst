# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.report.fifo_queue_vs_qty_after_transaction_comparison.fifo_queue_vs_qty_after_transaction_comparison import (
	execute,
)
from erpnext.tests.utils import ERPNextTestSuite


class TestFifoQueueVsQtyAfterTransactionComparison(ERPNextTestSuite):
	def run_report(self, filters: dict) -> list:
		return execute(frappe._dict(filters))[1]

	def test_healthy_fifo_item_no_mismatch(self):
		item = make_item(properties={"is_stock_item": 1, "valuation_method": "FIFO"}).name
		warehouse = "_Test Warehouse - _TC"

		make_stock_entry(item_code=item, to_warehouse=warehouse, qty=10, rate=100, posting_date="2026-06-01")
		make_stock_entry(item_code=item, to_warehouse=warehouse, qty=5, rate=120, posting_date="2026-06-01")
		make_stock_entry(item_code=item, from_warehouse=warehouse, qty=4, posting_date="2026-06-02")

		data = self.run_report({"company": "_Test Company", "item_code": item})

		item_codes = [row.get("item_code") for row in data if row]
		self.assertNotIn(item, item_codes)

	def test_requires_a_filter(self):
		with self.assertRaises(frappe.ValidationError):
			self.run_report({"company": "_Test Company"})
