"""Phase 0 characterization tests for the accounts/controller refactor.

These are golden-master snapshot tests: each scenario builds a representative
voucher, submits it, and compares its GL entries against a stored snapshot
(see ``erpnext/accounts/gl_snapshots``). They assert nothing about *correct*
accounting — only that GL output stays byte-identical as the GL pipeline is
refactored into composer / validator / sink services.

Regenerate goldens after an intentional change::

    REGEN_GL_SNAPSHOTS=1 bench run-tests --site test-erpnext-v17 \\
        --module erpnext.accounts.test_gl_characterization
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.tests.classes.context_managers import change_settings

from erpnext.accounts.doctype.account.test_account import create_account
from erpnext.accounts.doctype.mode_of_payment.test_mode_of_payment import (
	set_default_account_for_mode_of_payment,
)
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
from erpnext.accounts.gl_snapshot import assert_gl_snapshot

POSTING_DATE = "2024-01-15"
COMPANY = "_Test Company"
CUSTOMER = "_Test Customer"


def make_dated_purchase_invoice(**args):
	"""make_purchase_invoice ignores posting_date unless set_posting_time is on,
	which would make snapshots depend on the run date. Force the backdated time."""
	pi = make_purchase_invoice(do_not_save=True, **args)
	pi.set_posting_time = 1
	pi.posting_date = POSTING_DATE
	return pi


class TestGLCharacterization(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for mode, account in (("Cash", "_Test Cash - _TC"), ("Bank Draft", "_Test Bank - _TC")):
			set_default_account_for_mode_of_payment(frappe.get_doc("Mode of Payment", mode), COMPANY, account)

	def test_si_basic(self):
		si = create_sales_invoice(posting_date=POSTING_DATE, qty=10, rate=100)
		assert_gl_snapshot(self, "si_basic", "Sales Invoice", si.name)

	def test_si_with_taxes(self):
		si = create_sales_invoice(posting_date=POSTING_DATE, qty=10, rate=100, do_not_save=True)
		si.append(
			"taxes",
			{
				"charge_type": "On Net Total",
				"account_head": "_Test Account Service Tax - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"description": "Service Tax",
				"rate": 14,
			},
		)
		si.insert()
		si.submit()
		assert_gl_snapshot(self, "si_with_taxes", "Sales Invoice", si.name)

	def test_si_multi_currency(self):
		si = create_sales_invoice(
			posting_date=POSTING_DATE, qty=10, rate=100, currency="USD", conversion_rate=75
		)
		assert_gl_snapshot(self, "si_multi_currency", "Sales Invoice", si.name)

	def test_si_return(self):
		original = create_sales_invoice(posting_date=POSTING_DATE, qty=10, rate=100)
		credit_note = make_sales_return(original.name)
		credit_note.set_posting_time = 1
		credit_note.posting_date = POSTING_DATE
		credit_note.insert()
		credit_note.submit()
		assert_gl_snapshot(self, "si_return", "Sales Invoice", credit_note.name)

	def test_si_round_off(self):
		si = create_sales_invoice(posting_date=POSTING_DATE, qty=1, rate=100, do_not_save=True)
		si.append(
			"taxes",
			{
				"charge_type": "On Net Total",
				"account_head": "_Test Account Service Tax - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"description": "Service Tax",
				"rate": 6.5,
			},
		)
		si.insert()
		si.submit()
		assert_gl_snapshot(self, "si_round_off", "Sales Invoice", si.name)

	def test_si_with_discount_accounting(self):
		with change_settings("Selling Settings", {"enable_discount_accounting": 1}):
			discount_account = create_account(
				account_name="Discount Account",
				parent_account="Indirect Expenses - _TC",
				company=COMPANY,
			)
			si = create_sales_invoice(
				posting_date=POSTING_DATE, qty=1, rate=90, discount_account=discount_account
			)
			assert_gl_snapshot(self, "si_with_discount", "Sales Invoice", si.name)

	def test_si_with_advance(self):
		advance = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"party_type": "Customer",
				"party": CUSTOMER,
				"company": COMPANY,
				"posting_date": POSTING_DATE,
				"paid_from": "Debtors - _TC",
				"paid_to": "_Test Cash - _TC",
				"paid_from_account_currency": "INR",
				"paid_to_account_currency": "INR",
				"source_exchange_rate": 1,
				"target_exchange_rate": 1,
				"reference_no": "ADV-1",
				"reference_date": POSTING_DATE,
				"paid_amount": 500,
				"received_amount": 500,
			}
		)
		advance.insert()
		advance.submit()

		si = create_sales_invoice(posting_date=POSTING_DATE, qty=10, rate=100, do_not_save=True)
		si.allocate_advances_automatically = 1
		si.insert()
		si.submit()
		assert_gl_snapshot(self, "si_with_advance", "Sales Invoice", si.name)

	def test_si_pos(self):
		si = create_sales_invoice(posting_date=POSTING_DATE, qty=10, rate=100, do_not_save=True)
		si.is_pos = 1
		si.append("payments", {"mode_of_payment": "Cash", "amount": 500})
		si.append("payments", {"mode_of_payment": "Bank Draft", "amount": 500})
		si.insert()
		si.submit()
		assert_gl_snapshot(self, "si_pos", "Sales Invoice", si.name)

	def test_pi_basic(self):
		pi = make_dated_purchase_invoice(qty=5, rate=50)
		pi.insert()
		pi.submit()
		assert_gl_snapshot(self, "pi_basic", "Purchase Invoice", pi.name)

	def test_pi_with_taxes(self):
		pi = make_dated_purchase_invoice(qty=5, rate=50)
		pi.append(
			"taxes",
			{
				"charge_type": "On Net Total",
				"account_head": "_Test Account VAT - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"description": "VAT",
				"rate": 15,
			},
		)
		pi.insert()
		pi.submit()
		assert_gl_snapshot(self, "pi_with_taxes", "Purchase Invoice", pi.name)

	def test_pi_multi_currency(self):
		pi = make_dated_purchase_invoice(qty=5, rate=50, currency="USD", conversion_rate=75)
		pi.insert()
		pi.submit()
		assert_gl_snapshot(self, "pi_multi_currency", "Purchase Invoice", pi.name)

	def test_pi_return(self):
		original = make_dated_purchase_invoice(qty=5, rate=50)
		original.insert()
		original.submit()
		debit_note = make_debit_note(original.name)
		debit_note.set_posting_time = 1
		debit_note.posting_date = POSTING_DATE
		debit_note.insert()
		debit_note.submit()
		assert_gl_snapshot(self, "pi_return", "Purchase Invoice", debit_note.name)
