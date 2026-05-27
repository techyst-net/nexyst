# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import erpnext
from erpnext.accounts.services.base_gl_composer import BaseGLComposer


class PurchaseInvoiceGLComposer(BaseGLComposer):
	"""Assembles the GL entries for a Purchase Invoice.

	Orchestration only for now: the voucher-specific row builders still live on
	the Purchase Invoice document and are invoked via ``self.doc``. They migrate
	onto this composer in a later increment.
	"""

	def compose(self, inventory_account_map=None):
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_regional_gl_entries
		from erpnext.accounts.general_ledger import merge_similar_entries

		doc = self.doc
		doc.auto_accounting_for_stock = erpnext.is_perpetual_inventory_enabled(doc.company)

		if doc.auto_accounting_for_stock:
			doc.stock_received_but_not_billed = doc.get_company_default("stock_received_but_not_billed")
		else:
			doc.stock_received_but_not_billed = None

		doc.negative_expense_to_be_booked = 0.0
		gl_entries = []

		doc.make_supplier_gl_entry(gl_entries)
		doc.make_item_gl_entries(gl_entries)
		doc.make_precision_loss_gl_entry(gl_entries)

		doc.make_tax_gl_entries(gl_entries)
		doc.make_internal_transfer_gl_entries(gl_entries)
		doc.make_gl_entries_for_tax_withholding(gl_entries)

		gl_entries = make_regional_gl_entries(gl_entries, doc)

		gl_entries = merge_similar_entries(gl_entries)

		doc.make_payment_gl_entries(gl_entries)
		doc.make_write_off_gl_entry(gl_entries)
		doc.make_gle_for_rounding_adjustment(gl_entries)
		doc.set_transaction_currency_and_rate_in_gl_map(gl_entries)
		doc.set_gl_entry_for_purchase_expense(gl_entries)
		return gl_entries
