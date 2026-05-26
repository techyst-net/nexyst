# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe

from erpnext.accounts.services.base_gl_composer import BaseGLComposer


class SalesInvoiceGLComposer(BaseGLComposer):
	"""Assembles the GL entries for a Sales Invoice.

	Orchestration only for now: the voucher-specific row builders still live on
	the Sales Invoice document and are invoked via ``self.doc``. They migrate
	onto this composer in a later increment.
	"""

	def compose(self, inventory_account_map=None):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_regional_gl_entries
		from erpnext.accounts.general_ledger import merge_similar_entries

		doc = self.doc
		gl_entries = []

		doc.make_customer_gl_entry(gl_entries)

		doc.make_tax_gl_entries(gl_entries)
		doc.make_internal_transfer_gl_entries(gl_entries)

		doc.make_item_gl_entries(gl_entries)

		disable_sdbnb_in_sr = frappe.get_cached_value("Company", doc.company, "disable_sdbnb_in_sr")

		if not (doc.is_return and disable_sdbnb_in_sr):
			doc.stock_delivered_but_not_billed_gl_entries(gl_entries)

		doc.make_precision_loss_gl_entry(gl_entries)
		doc.make_discount_gl_entries(gl_entries)

		gl_entries = make_regional_gl_entries(gl_entries, doc)

		# merge gl entries before adding pos entries
		gl_entries = merge_similar_entries(gl_entries)

		doc.make_loyalty_point_redemption_gle(gl_entries)
		doc.make_pos_gl_entries(gl_entries)

		doc.make_write_off_gl_entry(gl_entries)
		doc.make_gle_for_rounding_adjustment(gl_entries)

		doc.set_transaction_currency_and_rate_in_gl_map(gl_entries)
		return gl_entries
