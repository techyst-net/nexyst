# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.report.stock_projected_qty.stock_projected_qty import execute
from erpnext.tests.utils import ERPNextTestSuite

WAREHOUSE = "_Test Warehouse - _TC"


class TestStockProjectedQty(ERPNextTestSuite):
	"""Correctness tests for the Stock Projected Qty report (a current-Bin snapshot)."""

	def run_report(self, item_code):
		filters = frappe._dict(company="_Test Company", item_code=item_code)
		columns, data = execute(filters)
		fields = [column["fieldname"] for column in columns]
		return [dict(zip(fields, row, strict=False)) for row in data]

	def test_projected_qty_includes_actual_and_ordered(self):
		item = make_item().name
		make_stock_entry(item_code=item, qty=10, to_warehouse=WAREHOUSE, basic_rate=100)
		create_purchase_order(item_code=item, qty=5, rate=100, warehouse=WAREHOUSE)

		row = self.run_report(item)[0]
		self.assertEqual(row["actual_qty"], 10)
		self.assertEqual(row["ordered_qty"], 5)
		self.assertEqual(row["projected_qty"], 15)

	def test_shortage_qty_from_reorder_level(self):
		item = make_item().name
		doc = frappe.get_doc("Item", item)
		doc.append(
			"reorder_levels",
			{
				"warehouse": WAREHOUSE,
				"warehouse_reorder_level": 20,
				"warehouse_reorder_qty": 15,
				"material_request_type": "Purchase",
			},
		)
		doc.save()
		make_stock_entry(item_code=item, qty=10, to_warehouse=WAREHOUSE, basic_rate=100)

		row = self.run_report(item)[0]
		self.assertEqual(row["re_order_level"], 20)
		self.assertEqual(row["projected_qty"], 10)
		self.assertEqual(row["shortage_qty"], 10)  # reorder level 20 - projected 10

	def test_item_filter_returns_only_requested_item(self):
		item_a = make_item().name
		item_b = make_item().name
		make_stock_entry(item_code=item_a, qty=5, to_warehouse=WAREHOUSE, basic_rate=100)
		make_stock_entry(item_code=item_b, qty=7, to_warehouse=WAREHOUSE, basic_rate=100)

		rows = self.run_report(item_a)
		self.assertEqual({row["item_code"] for row in rows}, {item_a})
