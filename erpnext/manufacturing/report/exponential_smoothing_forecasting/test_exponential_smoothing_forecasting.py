# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import flt

from erpnext.manufacturing.report.exponential_smoothing_forecasting.exponential_smoothing_forecasting import (
	execute,
)
from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order
from erpnext.tests.utils import ERPNextTestSuite

TEST_ITEM = "_Test Item"
FROM_DATE = "2026-06-01"
TO_DATE = "2026-08-31"


class TestExponentialSmoothingForecasting(ERPNextTestSuite):
	"""Drive real submitted Sales Orders and assert the report buckets the ordered
	quantities into the correct historical periods and produces a forecast."""

	def test_monthly_qty_forecast_from_sales_orders(self):
		# Historical demand: distinct calendar months strictly before FROM_DATE.
		# Monthly period keys are derived from the period's last day (e.g. "mar_2026").
		history = {"mar_2026": 7, "apr_2026": 4, "may_2026": 9}
		self.create_sales_orders(
			{
				"2026-03-15": history["mar_2026"],
				"2026-04-15": history["apr_2026"],
				"2026-05-15": history["may_2026"],
			}
		)

		columns, row = self.run_report()
		fields = {col["fieldname"] for col in columns}

		# For Monthly periodicity only future periods are exposed as columns, each as a
		# forecast_ field. Historical demand lives in the row data (keyed by month) but is
		# not surfaced as its own column.
		self.assertIn("forecast_jun_2026", fields, "expected future forecast column")
		self.assertNotIn("jun_2026", fields, "future period must not expose raw demand column")
		self.assertNotIn("mar_2026", fields, "historical month is not a Monthly report column")

		# Historical buckets must exactly reflect the ordered quantities.
		for key, qty in history.items():
			self.assertEqual(flt(row.get(key)), flt(qty), f"bucket {key} mismatch")

		# A forecast is produced for the first future period. The first non-zero
		# historical period seeds the forecast at the average of non-zero months,
		# so the future forecast must be positive.
		expected_avg = sum(history.values()) / len(history)
		self.assertGreater(flt(row.get("forecast_jun_2026")), 0.0)
		self.assertLessEqual(flt(row.get("forecast_jun_2026")), max(history.values()))
		self.assertAlmostEqual(flt(row.get("avg")), expected_avg, places=6)

	def test_ignores_documents_outside_range_and_other_docstatus(self):
		self.create_sales_orders({"2026-05-10": 6})
		# A draft SO and a future-dated SO must not contribute to historical demand.
		make_sales_order(item_code=TEST_ITEM, qty=100, transaction_date="2026-05-20", do_not_submit=True)
		make_sales_order(item_code=TEST_ITEM, qty=100, transaction_date=FROM_DATE)

		_columns, row = self.run_report()
		self.assertEqual(flt(row.get("may_2026")), 6.0)

	def create_sales_orders(self, date_to_qty):
		for transaction_date, qty in date_to_qty.items():
			make_sales_order(item_code=TEST_ITEM, qty=qty, transaction_date=transaction_date)

	def run_report(self, **extra):
		filters = frappe._dict(
			{
				"company": "_Test Company",
				"based_on_document": "Sales Order",
				"based_on_field": "Qty",
				"no_of_years": 3,
				"periodicity": "Monthly",
				"from_date": FROM_DATE,
				"to_date": TO_DATE,
				"smoothing_constant": 0.5,
				"item_code": TEST_ITEM,
			}
		)
		filters.update(extra)

		columns, data = execute(filters)[:2]
		item_row = next(
			(r for r in data if r.get("item_code") == TEST_ITEM),
			None,
		)
		self.assertIsNotNone(item_row, f"{TEST_ITEM} row missing from report output")
		return columns, item_row
