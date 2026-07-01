# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import frappe

from erpnext.manufacturing.doctype.production_plan.test_production_plan import make_bom
from erpnext.manufacturing.report.bom_operations_time.bom_operations_time import execute
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.tests.utils import ERPNextTestSuite

OPERATION = "_Test BOM Ops Time Operation"
WORKSTATION = "_Test BOM Ops Time Workstation"
TIME_IN_MINS = 45


class TestBOMOperationsTime(ERPNextTestSuite):
	def setUp(self):
		ensure_workstation_and_operation()
		self.rm_item = make_item(properties={"is_stock_item": 1, "valuation_rate": 100}).name
		self.fg_item = make_item(properties={"is_stock_item": 1}).name
		self.bom = build_bom_with_operation(self.fg_item, self.rm_item)

	def run_report(self, **extra):
		filters = frappe._dict({"bom_id": [self.bom.name]})
		filters.update(extra)
		return execute(filters)[1]

	def test_operation_row_appears_with_expected_values(self):
		rows = self.run_report()

		bom_rows = [row for row in rows if row.name == self.bom.name]
		self.assertEqual(len(bom_rows), 1)

		row = bom_rows[0]
		self.assertEqual(row.item, self.fg_item)
		self.assertEqual(row.operation, OPERATION)
		self.assertEqual(row.workstation, WORKSTATION)
		self.assertEqual(row.time_in_mins, TIME_IN_MINS)

	def test_item_code_filter_scopes_to_bom(self):
		rows = self.run_report(item_code=self.fg_item)

		self.assertTrue(rows)
		self.assertTrue(all(row.item == self.fg_item for row in rows))
		self.assertIn(self.bom.name, {row.name for row in rows})

	def test_workstation_filter(self):
		matching = self.run_report(workstation=WORKSTATION)
		self.assertIn(self.bom.name, {row.name for row in matching})

		other_workstation = ensure_other_workstation()
		non_matching = self.run_report(workstation=other_workstation)
		self.assertNotIn(self.bom.name, {row.name for row in non_matching})

	def test_draft_bom_excluded(self):
		draft_bom = build_bom_with_operation(
			make_item(properties={"is_stock_item": 1}).name, self.rm_item, do_not_submit=True
		)

		rows = execute(frappe._dict({"bom_id": [draft_bom.name]}))[1]
		self.assertEqual(rows, [])


def ensure_workstation_and_operation():
	if not frappe.db.exists("Workstation", WORKSTATION):
		frappe.get_doc({"doctype": "Workstation", "workstation_name": WORKSTATION}).insert(
			ignore_permissions=True
		)

	if not frappe.db.exists("Operation", OPERATION):
		frappe.get_doc({"doctype": "Operation", "name": OPERATION, "workstation": WORKSTATION}).insert(
			ignore_permissions=True
		)


def ensure_other_workstation():
	name = "_Test BOM Ops Time Workstation 2"
	if not frappe.db.exists("Workstation", name):
		frappe.get_doc({"doctype": "Workstation", "workstation_name": name}).insert(ignore_permissions=True)
	return name


def build_bom_with_operation(fg_item, rm_item, do_not_submit=False):
	bom = make_bom(
		item=fg_item,
		raw_materials=[rm_item],
		with_operations=1,
		do_not_save=True,
	)
	bom.append(
		"operations",
		{
			"operation": OPERATION,
			"workstation": WORKSTATION,
			"time_in_mins": TIME_IN_MINS,
			"hour_rate": 100,
		},
	)
	bom.insert(ignore_permissions=True)
	if not do_not_submit:
		bom.submit()
	return bom
