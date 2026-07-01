# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.accounts.report.share_ledger.share_ledger import execute
from erpnext.tests.utils import ERPNextTestSuite

COMPANY = "_Test Company"


class TestShareLedger(ERPNextTestSuite):
	def setUp(self):
		self.shareholder = self.create_shareholder("_Test Share Ledger Holder")
		# Issue 100 shares on 2026-06-01, then another 50 on 2026-06-10.
		self.first = self.issue_shares(date="2026-06-01", from_no=1, to_no=100, rate=10)
		self.second = self.issue_shares(date="2026-06-10", from_no=101, to_no=150, rate=12)

	def test_ledger_lists_all_transfers_upto_date(self):
		data = self.run_report(shareholder=self.shareholder, date="2026-06-30")

		self.assertEqual(len(data), 2)

		first_row, second_row = data
		self.assertEqual(first_row[0], self.shareholder)
		self.assertEqual(first_row[1], frappe.utils.getdate("2026-06-01"))
		self.assertEqual(first_row[2], "Issue")
		self.assertEqual(first_row[3], "Equity")
		self.assertEqual(first_row[4], 100)
		self.assertEqual(first_row[5], 10)
		self.assertEqual(first_row[6], 1000)
		self.assertEqual(first_row[7], COMPANY)
		self.assertEqual(first_row[8], self.first)

		self.assertEqual(second_row[1], frappe.utils.getdate("2026-06-10"))
		self.assertEqual(second_row[4], 50)
		self.assertEqual(second_row[5], 12)
		self.assertEqual(second_row[6], 600)
		self.assertEqual(second_row[8], self.second)

	def test_running_balance_of_shares(self):
		data = self.run_report(shareholder=self.shareholder, date="2026-06-30")

		running = 0
		balances = []
		for row in data:
			running += row[4]
			balances.append(running)

		self.assertEqual(balances, [100, 150])

	def test_as_on_date_between_transfers_shows_only_first(self):
		data = self.run_report(shareholder=self.shareholder, date="2026-06-05")

		self.assertEqual(len(data), 1)
		self.assertEqual(data[0][8], self.first)
		self.assertEqual(data[0][4], 100)

	def test_missing_date_throws(self):
		self.assertRaises(frappe.ValidationError, execute, frappe._dict(shareholder=self.shareholder))

	def test_missing_shareholder_returns_no_rows(self):
		data = self.run_report(date="2026-06-30")
		self.assertEqual(data, [])

	def run_report(self, **extra):
		filters = frappe._dict({"company": COMPANY, **extra})
		return execute(filters)[1]

	def create_shareholder(self, title):
		doc = frappe.get_doc(
			{
				"doctype": "Shareholder",
				"title": title,
				"company": COMPANY,
			}
		).insert()
		return doc.name

	def issue_shares(self, date, from_no, to_no, rate):
		doc = frappe.get_doc(
			{
				"doctype": "Share Transfer",
				"transfer_type": "Issue",
				"date": date,
				"to_shareholder": self.shareholder,
				"share_type": "Equity",
				"from_no": from_no,
				"to_no": to_no,
				"no_of_shares": to_no - from_no + 1,
				"rate": rate,
				"company": COMPANY,
				"asset_account": "Cash - _TC",
				"equity_or_liability_account": "Creditors - _TC",
			}
		)
		doc.submit()
		return doc.name
