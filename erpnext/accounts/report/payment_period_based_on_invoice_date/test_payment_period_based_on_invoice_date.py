# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, getdate, nowdate

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
from erpnext.accounts.report.payment_period_based_on_invoice_date.payment_period_based_on_invoice_date import (
	execute,
)
from erpnext.tests.utils import ERPNextTestSuite


class TestPaymentPeriodBasedOnInvoiceDate(ERPNextTestSuite):
	"""Depth tests for the Payment Period Based On Invoice Date report.

	The report lists Payment Ledger Entries against invoices and buckets the paid
	amount by the invoice's age into ranges: range1 (0-30), range2 (30-60),
	range3 (60-90), range4 (90 Above). The age is measured from the invoice
	posting date up to today, so invoice posting dates are placed relative to
	``nowdate()`` to land deterministically in a given bucket.
	"""

	def run_report(self, **extra):
		filters = frappe._dict(
			{
				"company": "_Test Company",
				"payment_type": "Incoming",
				"party_type": "Customer",
				"from_date": add_days(nowdate(), -180),
				"to_date": nowdate(),
			}
		)
		filters.update(extra)
		return execute(filters)

	def find_payment_row(self, data, payment_name):
		# Row shape (positional): payment_document, payment_entry(voucher_no),
		# party_type, party, posting_date, invoice(against_voucher_no),
		# invoice_posting_date, due_date, amount, remarks, age,
		# range1, range2, range3, range4, [delay_in_payment]
		for row in data:
			if row[1] == payment_name:
				return row
		return None

	def pay_invoice(self, invoice):
		pe = get_payment_entry("Sales Invoice", invoice.name)
		pe.posting_date = nowdate()
		pe.reference_no = "1"
		pe.reference_date = nowdate()
		pe.submit()
		return pe

	def test_paid_amount_lands_in_0_30_bucket(self):
		invoice = create_sales_invoice(
			customer="_Test Customer",
			rate=1000,
			posting_date=add_days(nowdate(), -15),
		)
		payment = self.pay_invoice(invoice)

		columns, data = self.run_report()

		row = self.find_payment_row(data, payment.name)
		self.assertIsNotNone(row, "Payment row not found in report output")

		# Positional assertions on the row shape.
		self.assertEqual(row[2], "Customer")
		self.assertEqual(row[4], getdate(nowdate()))  # payment posting date
		self.assertEqual(row[5], invoice.name)  # against invoice
		self.assertEqual(row[6], getdate(add_days(nowdate(), -15)))  # invoice posting date
		self.assertEqual(row[8], 1000)  # amount

		# Buckets: 0-30 filled, others empty.
		self.assertEqual(row[11], 1000)  # range1 (0-30)
		self.assertEqual(row[12], 0)  # range2 (30-60)
		self.assertEqual(row[13], 0)  # range3 (60-90)
		self.assertEqual(row[14], 0)  # range4 (90 Above)

	def test_paid_amount_lands_in_30_60_bucket(self):
		invoice = create_sales_invoice(
			customer="_Test Customer 1",
			rate=1000,
			posting_date=add_days(nowdate(), -45),
		)
		payment = self.pay_invoice(invoice)

		columns, data = self.run_report()

		row = self.find_payment_row(data, payment.name)
		self.assertIsNotNone(row, "Payment row not found in report output")

		self.assertEqual(row[8], 1000)  # amount
		# Buckets: 30-60 filled, others empty.
		self.assertEqual(row[11], 0)  # range1 (0-30)
		self.assertEqual(row[12], 1000)  # range2 (30-60)
		self.assertEqual(row[13], 0)  # range3 (60-90)
		self.assertEqual(row[14], 0)  # range4 (90 Above)

	def test_columns_expose_expected_age_buckets(self):
		columns, _data = self.run_report()
		labels_by_fieldname = {c["fieldname"]: c["label"] for c in columns}
		self.assertEqual(labels_by_fieldname["range1"], "0-30")
		self.assertEqual(labels_by_fieldname["range2"], "30-60")
		self.assertEqual(labels_by_fieldname["range3"], "60-90")
		self.assertEqual(labels_by_fieldname["range4"], "90 Above")
		# Sales Invoice link for Incoming payments.
		invoice_col = next(c for c in columns if c["fieldname"] == "invoice")
		self.assertEqual(invoice_col["options"], "Sales Invoice")

	def test_invalid_payment_type_party_type_combo_throws(self):
		# Incoming + Supplier is invalid.
		self.assertRaises(
			frappe.ValidationError,
			self.run_report,
			payment_type="Incoming",
			party_type="Supplier",
		)
		# Outgoing + Customer is invalid.
		self.assertRaises(
			frappe.ValidationError,
			self.run_report,
			payment_type="Outgoing",
			party_type="Customer",
		)
