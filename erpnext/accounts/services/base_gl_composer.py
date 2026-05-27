# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Base class for per-document GL entry composers.

A composer assembles the list of GL entry dicts for a single voucher. Unlike
the posting sink (``general_ledger.make_gl_entries``) and the stateless
validators (``gl_validator``), composing is stateful and per-document, so it is
modelled as a class holding the document being composed. Subclasses implement
``compose`` to return the voucher-specific list of GL entries.
"""

from erpnext.accounts.services.gl_entry_builder import add_gl_entry, get_gl_dict


class BaseGLComposer:
	def __init__(self, doc):
		self.doc = doc

	def compose(self):
		raise NotImplementedError

	def get_gl_dict(self, args: dict, account_currency: str | None = None, item=None) -> dict:
		return get_gl_dict(self.doc, args, account_currency, item)

	def add_gl_entry(
		self,
		gl_entries: list,
		account: str,
		cost_center: str,
		debit: float,
		credit: float,
		remarks: str,
		against_account: str,
		debit_in_account_currency: float | None = None,
		credit_in_account_currency: float | None = None,
		account_currency: str | None = None,
		project: str | None = None,
		voucher_detail_no: str | None = None,
		item=None,
		posting_date=None,
	) -> None:
		add_gl_entry(
			self.doc,
			gl_entries,
			account,
			cost_center,
			debit,
			credit,
			remarks,
			against_account,
			debit_in_account_currency,
			credit_in_account_currency,
			account_currency,
			project,
			voucher_detail_no,
			item,
			posting_date,
		)
