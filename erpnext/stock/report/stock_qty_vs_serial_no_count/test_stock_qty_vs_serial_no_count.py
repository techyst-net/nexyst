# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.report.stock_qty_vs_serial_no_count.stock_qty_vs_serial_no_count import execute
from erpnext.tests.utils import ERPNextTestSuite


class TestStockQtyVsSerialNoCount(ERPNextTestSuite):
	def run_report(self, **extra):
		filters = {
			"company": "_Test Company",
			"warehouse": "_Test Warehouse - _TC",
		}
		filters.update(extra)
		return execute(frappe._dict(filters))[1]

	def test_serial_count_matches_stock_qty(self):
		item = make_item(
			properties={
				"is_stock_item": 1,
				"has_serial_no": 1,
				"serial_no_series": "SQS-.#####",
			}
		).name
		make_stock_entry(
			item_code=item,
			to_warehouse="_Test Warehouse - _TC",
			qty=3,
			rate=100,
			posting_date="2026-06-01",
		)

		data = self.run_report()
		row = next((entry for entry in data if entry["item_code"] == item), None)

		self.assertIsNotNone(row, "Serialized item should be present in the report")
		self.assertEqual(row["total"], 3)
		self.assertEqual(row["stock_qty"], 3)
		self.assertEqual(row["difference"], 0)

	def test_warehouse_is_validated(self):
		with self.assertRaises(frappe.ValidationError):
			execute(
				frappe._dict(
					{
						"company": "_Test Company",
						"warehouse": "Non Existent Warehouse - XYZ",
					}
				)
			)
