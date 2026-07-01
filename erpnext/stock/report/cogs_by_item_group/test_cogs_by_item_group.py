# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.report.cogs_by_item_group.cogs_by_item_group import execute
from erpnext.tests.utils import ERPNextTestSuite


class TestCogsByItemGroup(ERPNextTestSuite):
	def run_report(self, **extra) -> list:
		filters = frappe._dict(
			company="_Test Company with perpetual inventory",
			from_date="2026-01-01",
			to_date="2026-12-31",
		)
		filters.update(extra)
		return execute(filters)[1]

	def test_cogs_for_item_group(self):
		# Reuse the bootstrap item `_Test Item` (item group `_Test Item Group`).
		# It has zero stock in `Stores - TCP1`, so this receipt starts from a clean balance.
		item = "_Test Item"

		make_stock_entry(
			item_code=item,
			to_warehouse="Stores - TCP1",
			qty=10,
			rate=100,
			company="_Test Company with perpetual inventory",
			posting_date="2026-06-01",
		)

		# A Sales Invoice with update_stock delivers the goods and books the COGS
		# against the company's default expense account, which the report keys on.
		create_sales_invoice(
			item_code=item,
			qty=4,
			rate=150,
			warehouse="Stores - TCP1",
			company="_Test Company with perpetual inventory",
			update_stock=1,
			cost_center="Main - TCP1",
			parent_cost_center="Main - TCP1",
			debit_to="Debtors - TCP1",
			income_account="Sales - TCP1",
			expense_account="Cost of Goods Sold - TCP1",
			posting_date="2026-06-02",
		)

		data = self.run_report()
		rows = [row for row in data if "_Test Item Group" in row.get("item_group")]
		self.assertTrue(rows, "No row found for _Test Item Group")
		# 4 units delivered at 100 valuation rate -> 400 COGS.
		self.assertEqual(rows[0].get("cogs_debit"), 400)
