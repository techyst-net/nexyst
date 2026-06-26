# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.report.stock_ledger.stock_ledger import execute
from erpnext.tests.utils import ERPNextTestSuite

WH = "_Test Warehouse - _TC"
WH2 = "Stores - _TC"


class TestStockLedgerReport(ERPNextTestSuite):
	def make_item(self, valuation_method="Moving Average"):
		return make_item(
			properties={"is_stock_item": 1, "valuation_method": valuation_method}
		).name

	def run_report(self, item_code, warehouse=None, **extra):
		filters = frappe._dict(
			{
				"company": "_Test Company",
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"valuation_field_type": "Currency",
				"item_code": [item_code] if isinstance(item_code, str) else item_code,
				**extra,
			}
		)
		if warehouse:
			filters["warehouse"] = [warehouse] if isinstance(warehouse, str) else warehouse
		return execute(filters)[1]

	def sle_rows(self, item_code, **extra):
		# drop the synthetic "'Opening'" row, keep only this item's ledger lines
		return [row for row in self.run_report(item_code, **extra) if row.get("item_code") == item_code]

	def test_receipt_shows_in_qty_and_balance(self):
		item = self.make_item()
		make_stock_entry(item_code=item, to_warehouse=WH, qty=10, rate=100, posting_date="2026-06-01")

		(row,) = self.sle_rows(item)
		self.assertEqual(row["in_qty"], 10)
		self.assertEqual(row["out_qty"], 0)
		self.assertEqual(row["qty_after_transaction"], 10)
		self.assertEqual(row["incoming_rate"], 100)
		self.assertEqual(row["valuation_rate"], 100)
		self.assertEqual(row["stock_value"], 1000)
		self.assertEqual(row["stock_value_difference"], 1000)

	def test_issue_shows_out_qty_and_outgoing_rate(self):
		item = self.make_item()
		make_stock_entry(item_code=item, to_warehouse=WH, qty=10, rate=100, posting_date="2026-06-01")
		make_stock_entry(item_code=item, from_warehouse=WH, qty=4, posting_date="2026-06-02")

		issue = self.sle_rows(item)[-1]
		self.assertEqual(issue["in_qty"], 0)
		self.assertEqual(issue["out_qty"], -4)
		self.assertEqual(issue["qty_after_transaction"], 6)
		self.assertEqual(issue["in_out_rate"], 100)  # stock_value_difference / actual_qty
		self.assertEqual(issue["stock_value"], 600)

	def test_running_balance_across_transactions(self):
		item = self.make_item()
		make_stock_entry(item_code=item, to_warehouse=WH, qty=10, rate=100, posting_date="2026-06-01")
		make_stock_entry(item_code=item, to_warehouse=WH, qty=5, rate=100, posting_date="2026-06-02")
		make_stock_entry(item_code=item, from_warehouse=WH, qty=3, posting_date="2026-06-03")

		balances = [row["qty_after_transaction"] for row in self.sle_rows(item)]
		self.assertEqual(balances, [10, 15, 12])

	def test_moving_average_valuation(self):
		item = self.make_item(valuation_method="Moving Average")
		make_stock_entry(item_code=item, to_warehouse=WH, qty=10, rate=100, posting_date="2026-06-01")
		make_stock_entry(item_code=item, to_warehouse=WH, qty=10, rate=200, posting_date="2026-06-02")

		latest = self.sle_rows(item)[-1]
		# (10*100 + 10*200) / 20 = 150
		self.assertEqual(latest["valuation_rate"], 150)
		self.assertEqual(latest["stock_value"], 3000)

	def test_item_code_filter_excludes_other_items(self):
		item_a = self.make_item()
		item_b = self.make_item()
		make_stock_entry(item_code=item_a, to_warehouse=WH, qty=10, rate=100, posting_date="2026-06-01")
		make_stock_entry(item_code=item_b, to_warehouse=WH, qty=7, rate=100, posting_date="2026-06-01")

		item_codes = {row["item_code"] for row in self.run_report(item_a)}
		self.assertEqual(item_codes, {item_a})

	def test_warehouse_filter(self):
		item = self.make_item()
		make_stock_entry(item_code=item, to_warehouse=WH, qty=10, rate=100, posting_date="2026-06-01")
		make_stock_entry(item_code=item, to_warehouse=WH2, qty=5, rate=100, posting_date="2026-06-01")

		warehouses = {row["warehouse"] for row in self.sle_rows(item, warehouse=WH2)}
		self.assertEqual(warehouses, {WH2})

	def test_voucher_no_filter(self):
		item = self.make_item()
		se = make_stock_entry(item_code=item, to_warehouse=WH, qty=10, rate=100, posting_date="2026-06-01")
		make_stock_entry(item_code=item, to_warehouse=WH, qty=5, rate=100, posting_date="2026-06-02")

		rows = self.sle_rows(item, voucher_no=se.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["voucher_no"], se.name)

	def test_date_range_excludes_out_of_range_entries(self):
		item = self.make_item()
		se = make_stock_entry(item_code=item, to_warehouse=WH, qty=10, rate=100, posting_date="2025-12-01")

		# 2026 window must not include the 2025 entry
		self.assertEqual(self.sle_rows(item), [])
		# widening the window back to 2025 brings it in
		in_window = self.run_report(item, from_date="2025-01-01", to_date="2025-12-31")
		self.assertIn(se.name, {row.get("voucher_no") for row in in_window})

	def test_opening_balance_row(self):
		item = self.make_item()
		# stock received before the reporting window should surface as the opening balance
		make_stock_entry(item_code=item, to_warehouse=WH, qty=10, rate=100, posting_date="2025-12-01")

		data = self.run_report(item, warehouse=WH)
		opening = data[0]
		self.assertEqual(opening["item_code"], "'Opening'")
		self.assertEqual(opening["qty_after_transaction"], 10)
		self.assertEqual(opening["stock_value"], 1000)
