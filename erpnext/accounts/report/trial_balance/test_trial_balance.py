# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

import frappe
from frappe.utils import add_days, today

from erpnext.accounts.report.trial_balance.trial_balance import execute
from erpnext.tests.utils import ERPNextTestSuite


class TestTrialBalance(ERPNextTestSuite):
	def setUp(self):
		from erpnext.accounts.doctype.account.test_account import create_account
		from erpnext.accounts.doctype.cost_center.test_cost_center import create_cost_center
		from erpnext.accounts.utils import get_fiscal_year

		create_cost_center(
			cost_center_name="Test Cost Center",
			company="Trial Balance Company",
			parent_cost_center="Trial Balance Company - TBC",
		)
		create_account(
			account_name="Offsetting",
			company="Trial Balance Company",
			parent_account="Temporary Accounts - TBC",
		)
		self.fiscal_year = get_fiscal_year(today(), company="Trial Balance Company")[0]
		dim = frappe.get_doc("Accounting Dimension", "Branch")
		dim.append(
			"dimension_defaults",
			{
				"company": "Trial Balance Company",
				"automatically_post_balancing_accounting_entry": 1,
				"offsetting_account": "Offsetting - TBC",
			},
		)
		dim.save()

	def test_offsetting_entries_for_accounting_dimensions(self):
		"""
		Checks if Trial Balance Report is balanced when filtered using a particular Accounting Dimension
		"""
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

		branch1 = frappe.new_doc("Branch")
		branch1.branch = "Location 1"
		branch1.insert(ignore_if_duplicate=True)
		branch2 = frappe.new_doc("Branch")
		branch2.branch = "Location 2"
		branch2.insert(ignore_if_duplicate=True)

		si = create_sales_invoice(
			company="Trial Balance Company",
			debit_to="Debtors - TBC",
			cost_center="Test Cost Center - TBC",
			income_account="Sales - TBC",
			do_not_submit=1,
		)
		si.branch = "Location 1"
		si.items[0].branch = "Location 2"
		si.save()
		si.submit()

		filters = frappe._dict(
			{"company": "Trial Balance Company", "fiscal_year": self.fiscal_year, "branch": ["Location 1"]}
		)
		total_row = execute(filters)[1][-1]
		self.assertEqual(total_row["debit"], total_row["credit"])


class TestTrialBalanceReport(ERPNextTestSuite):
	"""Correctness tests using fresh accounts so the asserted rows are unpolluted."""

	def make_accounts_and_entry(self, amount, posting_date):
		from erpnext.accounts.doctype.account.test_account import create_account
		from erpnext.accounts.doctype.journal_entry.test_journal_entry import make_journal_entry

		debit_account = create_account(
			account_name="_Test Trial Balance Debit",
			company="_Test Company",
			parent_account="Current Assets - _TC",
		)
		credit_account = create_account(
			account_name="_Test Trial Balance Credit",
			company="_Test Company",
			parent_account="Current Assets - _TC",
		)
		make_journal_entry(debit_account, credit_account, amount, posting_date=posting_date, submit=True)
		return debit_account, credit_account

	def rows_by_account(self, **filters):
		from erpnext.accounts.utils import get_fiscal_year

		filters.setdefault("company", "_Test Company")
		filters.setdefault("fiscal_year", get_fiscal_year(today(), company="_Test Company")[0])
		data = execute(frappe._dict(filters))[1]
		return {row["account"]: row for row in data if row.get("account")}, data[-1]

	def test_posted_entry_lands_in_period_and_total_balances(self):
		debit_account, credit_account = self.make_accounts_and_entry(500, today())

		rows, total_row = self.rows_by_account()

		self.assertEqual(rows[debit_account]["debit"], 500)
		self.assertEqual(rows[credit_account]["credit"], 500)
		self.assertEqual(total_row["debit"], total_row["credit"])

	def test_entry_before_from_date_shows_as_opening_balance(self):
		from erpnext.accounts.utils import get_fiscal_year

		fiscal_year, year_start, year_end = get_fiscal_year(today(), company="_Test Company")
		debit_account, credit_account = self.make_accounts_and_entry(500, year_start)

		rows, _ = self.rows_by_account(
			fiscal_year=fiscal_year, from_date=add_days(year_start, 5), to_date=year_end
		)

		# the entry predates the period, so it belongs in opening - not in the period columns
		self.assertEqual(rows[debit_account]["opening_debit"], 500)
		self.assertEqual(rows[debit_account]["debit"], 0)
		self.assertEqual(rows[credit_account]["opening_credit"], 500)
