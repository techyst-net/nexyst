# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.accounts.doctype.process_payment_reconciliation.process_payment_reconciliation import (
	get_pr_instance,
)
from erpnext.tests.utils import ERPNextTestSuite

COMPANY = "_Test Company"


class TestProcessPaymentReconciliation(ERPNextTestSuite):
	"""Process Payment Reconciliation validates its accounts against the company,
	moves to Queued on submit, and hands its filters to a Payment Reconciliation run."""

	def setUp(self):
		frappe.set_user("Administrator")

	def make_ppr(self, **args):
		args = frappe._dict(args)
		doc = frappe.new_doc("Process Payment Reconciliation")
		doc.company = COMPANY
		doc.party_type = "Customer"
		doc.party = "_Test Customer"
		doc.receivable_payable_account = args.get("receivable_payable_account", "Debtors - _TC")
		doc.bank_cash_account = args.get("bank_cash_account")
		doc.from_invoice_date = args.get("from_invoice_date")
		doc.to_invoice_date = args.get("to_invoice_date")
		return doc

	def test_receivable_account_must_belong_to_company(self):
		other = frappe.get_all(
			"Account",
			{"company": "_Test Company 1", "account_type": "Receivable", "is_group": 0},
			pluck="name",
		)[0]
		doc = self.make_ppr(receivable_payable_account=other)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_bank_cash_account_must_belong_to_company(self):
		other = frappe.get_all("Account", {"company": "_Test Company 1", "is_group": 0}, pluck="name")[0]
		doc = self.make_ppr(bank_cash_account=other)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_submit_sets_status_to_queued(self):
		doc = self.make_ppr()
		doc.insert()
		doc.submit()
		self.assertEqual(doc.status, "Queued")

	def test_get_pr_instance_copies_filters_and_caps_limits(self):
		doc = self.make_ppr(from_invoice_date="2026-01-01", to_invoice_date="2026-06-30")
		doc.insert()

		pr = get_pr_instance(doc.name)
		self.assertEqual(pr.company, COMPANY)
		self.assertEqual(pr.party, "_Test Customer")
		self.assertEqual(pr.receivable_payable_account, "Debtors - _TC")
		self.assertEqual(str(pr.from_invoice_date), "2026-01-01")
		# the tool run is capped so a single process can't fetch unbounded rows
		self.assertEqual(pr.invoice_limit, 1000)
		self.assertEqual(pr.payment_limit, 1000)
