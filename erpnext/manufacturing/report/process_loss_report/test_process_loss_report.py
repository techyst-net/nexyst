# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import nowdate

from erpnext.manufacturing.doctype.work_order.mapper import make_stock_entry
from erpnext.manufacturing.doctype.work_order.test_work_order import make_wo_order_test_record
from erpnext.manufacturing.report.process_loss_report.process_loss_report import execute
from erpnext.stock.doctype.stock_entry import test_stock_entry
from erpnext.tests.utils import ERPNextTestSuite


class TestProcessLossReport(ERPNextTestSuite):
	def run_report(self, **extra):
		filters = frappe._dict(
			{
				"company": "_Test Company",
				"from_date": nowdate(),
				"to_date": nowdate(),
			}
		)
		filters.update(extra)
		return execute(filters)[1]

	def find_row(self, data, work_order):
		for row in data:
			if row.get("name") == work_order:
				return row
		return None

	def make_manufactured_work_order(self, planned_qty, produced_qty):
		"""Create a submitted WO and manufacture `produced_qty` of `planned_qty`.

		The difference is booked as process loss on the Manufacture stock entry,
		which propagates to the work order's `process_loss_qty`.
		"""
		wo_order = make_wo_order_test_record(production_item="_Test FG Item", qty=planned_qty)

		test_stock_entry.make_stock_entry(
			item_code="_Test Item", target="Stores - _TC", qty=100, basic_rate=100
		)
		test_stock_entry.make_stock_entry(
			item_code="_Test Item Home Desktop 100", target="Stores - _TC", qty=100, basic_rate=100
		)

		transfer = frappe.get_doc(
			make_stock_entry(wo_order.name, "Material Transfer for Manufacture", planned_qty)
		)
		for d in transfer.get("items"):
			d.s_warehouse = "Stores - _TC"
		transfer.insert()
		transfer.submit()

		manufacture = frappe.get_doc(make_stock_entry(wo_order.name, "Manufacture", planned_qty))
		# Reduce the finished good qty below fg_completed_qty so the difference is
		# recorded as process loss.
		process_loss_qty = planned_qty - produced_qty
		if process_loss_qty:
			for d in manufacture.get("items"):
				if d.is_finished_item:
					d.qty = produced_qty
					d.transfer_qty = produced_qty * (d.conversion_factor or 1)
		manufacture.insert()
		manufacture.submit()

		wo_order.reload()
		return wo_order

	def test_work_order_with_process_loss_is_listed(self):
		wo_order = self.make_manufactured_work_order(planned_qty=5, produced_qty=4)

		self.assertEqual(wo_order.process_loss_qty, 1)
		self.assertEqual(wo_order.produced_qty, 4)

		data = self.run_report(work_order=wo_order.name)
		row = self.find_row(data, wo_order.name)

		self.assertIsNotNone(row, "Work order with process loss should appear in the report")
		self.assertEqual(row.production_item, "_Test FG Item")
		self.assertEqual(row.qty_to_manufacture, 5)
		self.assertEqual(row.produced_qty, 4)
		self.assertEqual(row.process_loss_qty, 1)

		# total_pl_value = process_loss_qty * (total_fg_value / qty_to_manufacture)
		expected_pl_value = row.process_loss_qty * (row.total_fg_value / row.qty_to_manufacture)
		self.assertAlmostEqual(row.total_pl_value, expected_pl_value)
		self.assertGreater(row.total_pl_value, 0)

	def test_work_order_without_process_loss_is_not_listed(self):
		wo_order = self.make_manufactured_work_order(planned_qty=5, produced_qty=5)

		self.assertEqual(wo_order.process_loss_qty, 0)
		self.assertEqual(wo_order.produced_qty, 5)

		data = self.run_report(work_order=wo_order.name)
		self.assertIsNone(
			self.find_row(data, wo_order.name),
			"Work order that produced the full planned qty should not appear (no loss)",
		)

	def test_item_and_work_order_filters_are_ineffective(self):
		"""BUG: the `item` and `work_order` filters in process_loss_report.get_data
		call `query.where(...)` without reassigning the result. frappe's query
		builder is immutable, so `.where()` returns a new query and these extra
		conditions are silently dropped. A non-matching item filter therefore fails
		to exclude the row. This test documents the current (buggy) behaviour; if the
		report is fixed to reassign the query, update the assertion below to
		`assertIsNone`.
		"""
		wo_order = self.make_manufactured_work_order(planned_qty=5, produced_qty=4)

		# A non-matching item filter should exclude the row, but currently does not.
		data = self.run_report(item="_Test FG Item 2")
		self.assertIsNotNone(
			self.find_row(data, wo_order.name),
			"Filter bug regressed/fixed: `item` filter now takes effect - update this test",
		)
