# Copyright (c) 2017, Velometro Mobility Inc and contributors
# For license information, please see license.txt

import frappe

from erpnext.tests.utils import ERPNextTestSuite


class TestWorkOrderStockReport(ERPNextTestSuite):
	def test_report_executes_and_lists_work_order(self):
		# get_item_list computes build_qty by multiplying bin/bom/bom_item columns that are not
		# functionally dependent on the grouped item_code; they must be in the GROUP BY for the
		# report to run on Postgres. This exercises that query on both engines.
		from erpnext.manufacturing.doctype.work_order.test_work_order import make_wo_order_test_record
		from erpnext.manufacturing.report.work_order_stock_report.work_order_stock_report import execute

		wo = make_wo_order_test_record(
			production_item="_Test FG Item", qty=1, source_warehouse="_Test Warehouse - _TC"
		)

		columns, data = execute(frappe._dict(warehouse="_Test Warehouse - _TC"))

		self.assertTrue(columns)
		self.assertIn(wo.name, {row["work_order"] for row in data})
