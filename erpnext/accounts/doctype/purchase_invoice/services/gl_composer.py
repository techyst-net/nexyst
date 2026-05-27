# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt, get_link_to_form

import erpnext
from erpnext.accounts.general_ledger import get_round_off_account_and_cost_center
from erpnext.accounts.services.base_gl_composer import BaseGLComposer
from erpnext.accounts.utils import get_account_currency


class PurchaseInvoiceGLComposer(BaseGLComposer):
	"""Assembles the GL entries for a Purchase Invoice."""

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

		self.make_supplier_gl_entry(gl_entries)
		doc.make_item_gl_entries(gl_entries)
		doc.make_precision_loss_gl_entry(gl_entries)

		self.make_tax_gl_entries(gl_entries)
		self.make_internal_transfer_gl_entries(gl_entries)
		self.make_gl_entries_for_tax_withholding(gl_entries)

		gl_entries = make_regional_gl_entries(gl_entries, doc)
		gl_entries = merge_similar_entries(gl_entries)

		self.make_payment_gl_entries(gl_entries)
		self.make_write_off_gl_entry(gl_entries)
		self.make_gle_for_rounding_adjustment(gl_entries)
		doc.set_transaction_currency_and_rate_in_gl_map(gl_entries)
		doc.set_gl_entry_for_purchase_expense(gl_entries)
		return gl_entries

	def make_supplier_gl_entry(self, gl_entries):
		doc = self.doc
		grand_total = (
			doc.rounded_total if (doc.rounding_adjustment and doc.rounded_total) else doc.grand_total
		)
		base_grand_total = flt(
			doc.base_rounded_total
			if (doc.base_rounding_adjustment and doc.base_rounded_total)
			else doc.base_grand_total,
			doc.precision("base_grand_total"),
		)
		if grand_total and not doc.is_internal_transfer():
			self.add_supplier_gl_entry(gl_entries, base_grand_total, grand_total)

	def add_supplier_gl_entry(
		self,
		gl_entries,
		base_grand_total,
		grand_total,
		against_account=None,
		remarks=None,
		skip_merge=False,
	):
		doc = self.doc
		against_voucher = doc.name
		if doc.is_return and doc.return_against and not doc.update_outstanding_for_self:
			against_voucher = doc.return_against

		gl = {
			"account": doc.credit_to,
			"party_type": "Supplier",
			"party": doc.supplier,
			"due_date": doc.due_date,
			"against": against_account or doc.against_expense_account,
			"credit": base_grand_total,
			"credit_in_account_currency": base_grand_total
			if doc.party_account_currency == doc.company_currency
			else grand_total,
			"credit_in_transaction_currency": grand_total,
			"against_voucher": against_voucher,
			"against_voucher_type": doc.doctype,
			"project": doc.project,
			"cost_center": doc.cost_center,
			"_skip_merge": skip_merge,
		}
		if remarks:
			gl["remarks"] = remarks
		gl_entries.append(doc.get_gl_dict(gl, doc.party_account_currency, item=doc))

	def make_tax_gl_entries(self, gl_entries):
		doc = self.doc
		valuation_tax = {}

		for tax in doc.get("taxes"):
			amount, base_amount = doc.get_tax_amounts(tax, None)
			if tax.category in ("Total", "Valuation and Total") and flt(base_amount):
				account_currency = get_account_currency(tax.account_head)
				dr_or_cr = "debit" if tax.add_deduct_tax == "Add" else "credit"
				gl_entries.append(
					doc.get_gl_dict(
						{
							"account": tax.account_head,
							"against": doc.supplier,
							dr_or_cr: base_amount,
							dr_or_cr + "_in_account_currency": base_amount
							if account_currency == doc.company_currency
							else amount,
							dr_or_cr + "_in_transaction_currency": amount,
							"cost_center": tax.cost_center,
						},
						account_currency,
						item=tax,
					)
				)

			if (
				doc.is_opening == "No"
				and tax.category in ("Valuation", "Valuation and Total")
				and flt(base_amount)
				and not doc.is_internal_transfer()
			):
				if doc.auto_accounting_for_stock and not tax.cost_center:
					frappe.throw(
						_("Cost Center is required in row {0} in Taxes table for type {1}").format(
							tax.idx, _(tax.category)
						)
					)
				valuation_tax.setdefault(tax.name, 0)
				valuation_tax[tax.name] += (tax.add_deduct_tax == "Add" and 1 or -1) * flt(base_amount)

		if doc.is_opening == "No" and doc.negative_expense_to_be_booked and valuation_tax:
			total_valuation_amount = sum(valuation_tax.values())
			amount_including_divisional_loss = doc.negative_expense_to_be_booked
			i = 1
			for tax in doc.get("taxes"):
				if valuation_tax.get(tax.name):
					if i == len(valuation_tax):
						applicable_amount = amount_including_divisional_loss
					else:
						applicable_amount = doc.negative_expense_to_be_booked * (
							valuation_tax[tax.name] / total_valuation_amount
						)
						amount_including_divisional_loss -= applicable_amount

					gl_entries.append(
						doc.get_gl_dict(
							{
								"account": tax.account_head,
								"cost_center": tax.cost_center,
								"against": doc.supplier,
								"credit": applicable_amount,
								"credit_in_transaction_currency": flt(
									applicable_amount / doc.conversion_rate,
									frappe.get_precision("Purchase Invoice Item", "item_tax_amount"),
								),
								"remarks": doc.remarks or _("Accounting Entry for Stock"),
							},
							item=tax,
						)
					)
					i += 1

		if doc.auto_accounting_for_stock and doc.update_stock and valuation_tax:
			for tax in doc.get("taxes"):
				if valuation_tax.get(tax.name):
					gl_entries.append(
						doc.get_gl_dict(
							{
								"account": tax.account_head,
								"cost_center": tax.cost_center,
								"against": doc.supplier,
								"credit": valuation_tax[tax.name],
								"credit_in_transaction_currency": flt(
									valuation_tax[tax.name] / doc.conversion_rate,
									frappe.get_precision("Purchase Invoice Item", "item_tax_amount"),
								),
								"remarks": doc.remarks or _("Accounting Entry for Stock"),
							},
							item=tax,
						)
					)

	def make_internal_transfer_gl_entries(self, gl_entries):
		doc = self.doc
		if doc.is_internal_transfer() and flt(doc.base_total_taxes_and_charges):
			account_currency = get_account_currency(doc.unrealized_profit_loss_account)
			gl_entries.append(
				doc.get_gl_dict(
					{
						"account": doc.unrealized_profit_loss_account,
						"against": doc.supplier,
						"credit": flt(doc.total_taxes_and_charges),
						"credit_in_transaction_currency": flt(doc.total_taxes_and_charges),
						"credit_in_account_currency": flt(doc.base_total_taxes_and_charges),
						"cost_center": doc.cost_center,
					},
					account_currency,
					item=doc,
				)
			)

	def make_gl_entries_for_tax_withholding(self, gl_entries):
		"""Separate supplier GL entry for tax withholding (TDS) — not part of the supplier invoice amount."""
		doc = self.doc
		if not doc.apply_tds:
			return

		for row in doc.get("taxes"):
			if not row.is_tax_withholding_account or not row.tax_amount:
				continue

			base_tds_amount = row.base_tax_amount_after_discount_amount
			tds_amount = row.tax_amount_after_discount_amount

			self.add_supplier_gl_entry(gl_entries, base_tds_amount, tds_amount)
			self.add_supplier_gl_entry(
				gl_entries,
				-base_tds_amount,
				-tds_amount,
				against_account=row.account_head,
				remarks=_("TDS Deducted"),
				skip_merge=True,
			)

	def make_payment_gl_entries(self, gl_entries):
		doc = self.doc
		if cint(doc.is_paid) and doc.cash_bank_account and doc.paid_amount:
			bank_account_currency = get_account_currency(doc.cash_bank_account)

			gl_entries.append(
				doc.get_gl_dict(
					{
						"account": doc.credit_to,
						"party_type": "Supplier",
						"party": doc.supplier,
						"against": doc.cash_bank_account,
						"debit": doc.base_paid_amount,
						"debit_in_account_currency": doc.base_paid_amount
						if doc.party_account_currency == doc.company_currency
						else doc.paid_amount,
						"debit_in_transaction_currency": doc.paid_amount,
						"against_voucher": doc.return_against
						if cint(doc.is_return) and doc.return_against
						else doc.name,
						"against_voucher_type": doc.doctype,
						"cost_center": doc.cost_center,
						"project": doc.project,
					},
					doc.party_account_currency,
					item=doc,
				)
			)

			gl_entries.append(
				doc.get_gl_dict(
					{
						"account": doc.cash_bank_account,
						"against": doc.supplier,
						"credit": doc.base_paid_amount,
						"credit_in_account_currency": doc.base_paid_amount
						if bank_account_currency == doc.company_currency
						else doc.paid_amount,
						"credit_in_transaction_currency": doc.paid_amount,
						"cost_center": doc.cost_center,
					},
					bank_account_currency,
					item=doc,
				)
			)

	def make_write_off_gl_entry(self, gl_entries):
		doc = self.doc
		if doc.write_off_account and flt(doc.write_off_amount):
			write_off_account_currency = get_account_currency(doc.write_off_account)

			gl_entries.append(
				doc.get_gl_dict(
					{
						"account": doc.credit_to,
						"party_type": "Supplier",
						"party": doc.supplier,
						"against": doc.write_off_account,
						"debit": doc.base_write_off_amount,
						"debit_in_account_currency": doc.base_write_off_amount
						if doc.party_account_currency == doc.company_currency
						else doc.write_off_amount,
						"debit_in_transaction_currency": doc.write_off_amount,
						"against_voucher": doc.return_against
						if cint(doc.is_return) and doc.return_against
						else doc.name,
						"against_voucher_type": doc.doctype,
						"cost_center": doc.cost_center,
						"project": doc.project,
					},
					doc.party_account_currency,
					item=doc,
				)
			)
			gl_entries.append(
				doc.get_gl_dict(
					{
						"account": doc.write_off_account,
						"against": doc.supplier,
						"credit": flt(doc.base_write_off_amount),
						"credit_in_account_currency": doc.base_write_off_amount
						if write_off_account_currency == doc.company_currency
						else doc.write_off_amount,
						"credit_in_transaction_currency": doc.write_off_amount,
						"cost_center": doc.cost_center or doc.write_off_cost_center,
					},
					item=doc,
				)
			)

	def make_gle_for_rounding_adjustment(self, gl_entries):
		doc = self.doc
		if not doc.is_internal_transfer() and doc.rounding_adjustment and doc.base_rounding_adjustment:
			(
				round_off_account,
				round_off_cost_center,
				round_off_for_opening,
			) = get_round_off_account_and_cost_center(
				doc.company, "Purchase Invoice", doc.name, doc.use_company_roundoff_cost_center
			)

			if doc.is_opening == "Yes" and doc.rounding_adjustment:
				if not round_off_for_opening:
					frappe.throw(
						_(
							"Opening Invoice has rounding adjustment of {0}.<br><br> '{1}' account is required to post these values. Please set it in Company: {2}.<br><br> Or, '{3}' can be enabled to not post any rounding adjustment."
						).format(
							frappe.bold(doc.rounding_adjustment),
							frappe.bold("Round Off for Opening"),
							get_link_to_form("Company", doc.company),
							frappe.bold("Disable Rounded Total"),
						)
					)
				else:
					round_off_account = round_off_for_opening

			gl_entries.append(
				doc.get_gl_dict(
					{
						"account": round_off_account,
						"against": doc.supplier,
						"debit_in_account_currency": doc.rounding_adjustment,
						"debit": doc.base_rounding_adjustment,
						"cost_center": round_off_cost_center
						if doc.use_company_roundoff_cost_center
						else (doc.cost_center or round_off_cost_center),
					},
					item=doc,
				)
			)
