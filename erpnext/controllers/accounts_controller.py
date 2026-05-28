# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import json
from collections import defaultdict

import frappe
from frappe import _, bold, qb, throw
from frappe.contacts.doctype.address.address import get_address_display
from frappe.model.workflow import get_workflow_name, is_transition_condition_satisfied
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import (
	cint,
	comma_and,
	flt,
	get_link_to_form,
	getdate,
	nowdate,
	today,
)

import erpnext
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimensions,
)
from erpnext.accounts.doctype.pricing_rule.utils import (
	apply_pricing_rule_for_free_items,
	apply_pricing_rule_on_transaction,
	get_applied_pricing_rules,
)
from erpnext.accounts.general_ledger import get_round_off_account_and_cost_center
from erpnext.accounts.party import (
	PURCHASE_TRANSACTION_TYPES,
	SALES_TRANSACTION_TYPES,
	get_party_account,
	get_party_account_currency,
	get_party_gle_currency,
	validate_party_frozen_disabled,
)
from erpnext.accounts.utils import (
	get_account_currency,
	validate_fiscal_year,
)
from erpnext.accounts.utils import (
	get_advance_payment_doctypes as _get_advance_payment_doctypes,
)
from erpnext.buying.utils import update_last_purchase_rate
from erpnext.controllers.print_settings import (
	set_print_templates_for_item_table,
	set_print_templates_for_taxes,
)
from erpnext.controllers.sales_and_purchase_return import validate_return
from erpnext.exceptions import InvalidCurrency
from erpnext.setup.utils import get_exchange_rate
from erpnext.stock.doctype.item.item import get_uom_conv_factor
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
from erpnext.stock.get_item_details import (
	ItemDetailsCtx,
	get_bin_details,
	get_conversion_factor,
	get_item_details,
	get_item_warehouse_,
)
from erpnext.utilities.regional import temporary_flag
from erpnext.utilities.transaction_base import TransactionBase


class AccountMissingError(frappe.ValidationError):
	pass


class InvalidQtyError(frappe.ValidationError):
	pass


force_item_fields = (
	"item_group",
	"brand",
	"stock_uom",
	"is_fixed_asset",
	"pricing_rules",
	"weight_per_unit",
	"weight_uom",
	"total_weight",
	"valuation_rate",
)


class AccountsController(TransactionBase):
	def get_print_settings(self):
		print_setting_fields = []
		items_field = self.meta.get_field("items")

		if items_field and items_field.fieldtype == "Table":
			print_setting_fields += ["compact_item_print", "print_uom_after_quantity"]

		taxes_field = self.meta.get_field("taxes")
		if taxes_field and taxes_field.fieldtype == "Table":
			print_setting_fields += ["print_taxes_with_zero_amount"]

		return print_setting_fields

	@property
	def company_currency(self):
		if not hasattr(self, "__company_currency"):
			self.__company_currency = erpnext.get_company_currency(self.company)

		return self.__company_currency

	def onload(self):
		self.set_onload(
			"make_payment_via_journal_entry",
			frappe.client_cache.get_doc("Accounts Settings").make_payment_via_journal_entry,
		)

		if self.is_new():
			relevant_docs = (
				"Quotation",
				"Purchase Order",
				"Sales Order",
				"Purchase Invoice",
				"Sales Invoice",
			)
			if self.doctype in relevant_docs:
				self.set_payment_schedule()

	def on_update(self):
		from erpnext.controllers.taxes_and_totals import process_item_wise_tax_details

		process_item_wise_tax_details(self)

	def remove_bundle_for_non_stock_invoices(self):
		has_sabb = False
		if self.doctype in ("Sales Invoice", "Purchase Invoice") and not self.update_stock:
			for item in self.get("items"):
				if item.serial_and_batch_bundle:
					item.serial_and_batch_bundle = None
					has_sabb = True

		if has_sabb:
			self.remove_serial_and_batch_bundle()

	def ensure_supplier_is_not_blocked(self):
		is_supplier_payment = self.doctype == "Payment Entry" and self.party_type == "Supplier"
		is_buying_invoice = self.doctype in ["Purchase Invoice", "Purchase Order"]
		supplier_name = self.supplier if is_buying_invoice else self.party if is_supplier_payment else None
		supplier = None

		if supplier_name:
			supplier = frappe.get_lazy_doc("Supplier", supplier_name)

		if supplier and supplier.on_hold:
			if (is_buying_invoice and supplier.hold_type in ["All", "Invoices"]) or (
				is_supplier_payment and supplier.hold_type in ["All", "Payments"]
			):
				if not supplier.release_date or getdate(nowdate()) <= supplier.release_date:
					frappe.msgprint(
						_("{0} is blocked so this transaction cannot proceed").format(supplier_name),
						raise_exception=1,
					)

	def validate_against_voucher_outstanding(self):
		from frappe.model.meta import get_meta

		if not get_meta(self.doctype).has_field("outstanding_amount"):
			return

		if self.get("is_return") and self.return_against and not self.get("is_pos"):
			against_voucher_outstanding = frappe.get_value(
				self.doctype, self.return_against, "outstanding_amount"
			)
			document_type = "Credit Note" if self.doctype == "Sales Invoice" else "Debit Note"

			msg = ""
			if self.get("update_outstanding_for_self"):
				msg = _(
					"We can see {0} is made against {1}. If you want {1}'s outstanding to be updated, uncheck the '{2}' checkbox."
				).format(
					frappe.bold(document_type),
					get_link_to_form(self.doctype, self.get("return_against")),
					frappe.bold(_("Update Outstanding for Self")),
				)

			elif not self.update_outstanding_for_self and (
				abs(flt(self.rounded_total) or flt(self.grand_total)) > flt(against_voucher_outstanding)
			):
				self.update_outstanding_for_self = 1
				msg = _(
					"The outstanding amount {0} in {1} is lesser than {2}. Updating the outstanding to this invoice."
				).format(
					against_voucher_outstanding,
					get_link_to_form(self.doctype, self.get("return_against")),
					flt(abs(self.outstanding_amount)),
				)

			if msg:
				msg += "<br><br>" + _("You can use {0} to reconcile against {1} later.").format(
					get_link_to_form("Payment Reconciliation"),
					get_link_to_form(self.doctype, self.get("return_against")),
				)
				frappe.msgprint(msg)

	def validate(self):
		if not self.get("is_return") and not self.get("is_debit_note"):
			self.validate_qty_is_not_zero()

		if (
			self.doctype in ["Sales Invoice", "Purchase Invoice", "POS Invoice"]
			and self.get("is_return")
			and self.get("update_stock")
		):
			self.validate_zero_qty_for_return_invoices_with_stock()

		if self.get("_action") and self._action != "update_after_submit":
			self.set_missing_values(for_validate=True)

		if self.get("_action") == "submit":
			self.remove_bundle_for_non_stock_invoices()

		self.ensure_supplier_is_not_blocked()

		self.validate_date_with_fiscal_year()
		self.validate_party_accounts()
		if self.doctype in ["Sales Invoice", "Purchase Invoice"]:
			if self.is_return:
				self.validate_qty()
			else:
				self.validate_deferred_start_and_end_date()

		self.validate_inter_company_reference()
		# validate inter  company transaction rate
		self.validate_internal_transaction()

		self.disable_pricing_rule_on_internal_transfer()
		self.disable_tax_included_prices_for_internal_transfer()
		self.set_incoming_rate()
		self.init_internal_values()
		self.validate_against_voucher_outstanding()

		# Need to set taxes based on taxes_and_charges template
		# before calculating taxes and totals
		from erpnext.accounts.services.taxes import TaxService

		tax_service = TaxService(self)
		if self.meta.get_field("taxes_and_charges"):
			tax_service.validate_enabled_taxes_and_charges()
			tax_service.validate_tax_account_company()

		tax_service.set_taxes_and_charges()

		if self.meta.get_field("currency"):
			self.calculate_taxes_and_totals()

			if not self.meta.get_field("is_return") or not self.is_return:
				self.validate_value("base_grand_total", ">=", 0)

			validate_return(self)

		self.validate_all_documents_schedule()

		self.validate_party()
		self.validate_currency()
		self.validate_party_account_currency()
		self.validate_return_against_account()

		if self.doctype in ["Purchase Invoice", "Sales Invoice"]:
			if invalid_advances := [x for x in self.advances if not x.reference_type or not x.reference_name]:
				frappe.throw(
					_(
						"Rows: {0} in {1} section are Invalid. Reference Name should point to a valid Payment Entry or Journal Entry."
					).format(
						frappe.bold(comma_and([x.idx for x in invalid_advances])),
						frappe.bold(_("Advance Payments")),
					)
				)

			pos_check_field = "is_pos" if self.doctype == "Sales Invoice" else "is_paid"
			if cint(self.allocate_advances_automatically) and not cint(self.get(pos_check_field)):
				self.set_advances()

			self.set_advance_gain_or_loss()

			self.validate_deferred_income_expense_account()
			self.set_inter_company_account()

		if self.doctype == "Purchase Invoice":
			self.calculate_paid_amount()

		with temporary_flag("company", self.company):
			validate_regional(self)
			validate_einvoice_fields(self)

		if self.doctype != "Material Request" and not self.ignore_pricing_rule:
			apply_pricing_rule_on_transaction(self)

		self.set_total_in_words()
		self.set_default_letter_head()
		self.validate_company_in_accounting_dimension()
		self.validate_party_address_and_contact()
		self.validate_company_linked_addresses()

	def validate_company_linked_addresses(self):
		address_fields = []
		sales_doctypes = ("Quotation", "Sales Order", "Delivery Note", "Sales Invoice")
		purchase_doctypes = ("Purchase Order", "Purchase Receipt", "Purchase Invoice", "Supplier Quotation")

		if self.doctype in sales_doctypes:
			address_fields = ["dispatch_address_name", "company_address"]
		elif self.doctype in purchase_doctypes:
			address_fields = ["billing_address", "shipping_address"]

		if not address_fields:
			return

		# Determine if drop ship applies
		is_drop_ship = self.doctype in {
			"Purchase Order",
			"Purchase Invoice",
			"Sales Order",
			"Sales Invoice",
		} and self.is_drop_ship(self.items)

		for field in address_fields:
			address = self.get(field)

			if (field in ["dispatch_address_name", "shipping_address"]) and is_drop_ship:
				continue

			if address and not frappe.db.exists(
				"Dynamic Link",
				{
					"parent": address,
					"parenttype": "Address",
					"link_doctype": "Company",
					"link_name": self.company,
				},
			):
				frappe.throw(
					_("{0} does not belong to the Company {1}.").format(
						_(self.meta.get_label(field)), bold(self.company)
					)
				)

	@staticmethod
	def is_drop_ship(items):
		return any(item.delivered_by_supplier for item in items)

	def set_default_letter_head(self):
		if hasattr(self, "letter_head") and not self.letter_head:
			self.letter_head = frappe.db.get_value("Company", self.company, "default_letter_head")

	def init_internal_values(self):
		# init all the internal values as 0 on sa
		if self.docstatus.is_draft():
			# TODO: Add all such pending values here
			fields = ["billed_amt", "delivered_qty"]
			for item in self.get("items"):
				for field in fields:
					if hasattr(item, field):
						item.set(field, 0)

	def before_cancel(self):
		validate_einvoice_fields(self)

	def _remove_references_in_unreconcile(self):
		upe = frappe.qb.DocType("Unreconcile Payment Entries")
		rows = (
			frappe.qb.from_(upe)
			.select(upe.name, upe.parent)
			.where((upe.reference_doctype == self.doctype) & (upe.reference_name == self.name))
			.run(as_dict=True)
		)

		if rows:
			references_map = frappe._dict()
			for x in rows:
				references_map.setdefault(x.parent, []).append(x.name)

			for doc, rows in references_map.items():
				unreconcile_doc = frappe.get_doc("Unreconcile Payment", doc)
				for row in rows:
					unreconcile_doc.remove(unreconcile_doc.get("allocations", {"name": row})[0])

				unreconcile_doc.flags.ignore_validate_update_after_submit = True
				unreconcile_doc.flags.ignore_links = True
				unreconcile_doc.save(ignore_permissions=True)

		# delete docs upon parent doc deletion
		unreconcile_docs = frappe.db.get_all("Unreconcile Payment", filters={"voucher_no": self.name})
		for x in unreconcile_docs:
			_doc = frappe.get_doc("Unreconcile Payment", x.name)
			if _doc.docstatus == 1:
				_doc.cancel()
			_doc.delete()

	def _remove_references_in_repost_doctypes(self):
		repost_doctypes = ["Repost Payment Ledger Items", "Repost Accounting Ledger Items"]

		for _doctype in repost_doctypes:
			dt = frappe.qb.DocType(_doctype)

			cancelled_entries = (
				frappe.qb.from_(dt)
				.select(dt.parent, dt.parenttype)
				.where((dt.voucher_type == self.doctype) & (dt.voucher_no == self.name) & (dt.docstatus == 2))
				.run(as_dict=True)
			)

			if cancelled_entries:
				entries = "<br>".join([get_link_to_form(d.parenttype, d.parent) for d in cancelled_entries])

				frappe.throw(
					_(
						"The following cancelled repost entries exist for <b>{0}</b>:<br><br>{1}<br><br>"
						"Kindly delete these entries before continuing."
					).format(self.name, entries)
				)

			rows = (
				frappe.qb.from_(dt)
				.select(dt.name, dt.parent, dt.parenttype)
				.where((dt.voucher_type == self.doctype) & (dt.voucher_no == self.name))
				.run(as_dict=True)
			)

			if rows:
				references_map = frappe._dict()
				for x in rows:
					references_map.setdefault((x.parenttype, x.parent), []).append(x.name)

				for doc, rows in references_map.items():
					repost_doc = frappe.get_doc(doc[0], doc[1])

					for row in rows:
						if _doctype == "Repost Payment Ledger Items":
							repost_doc.remove(repost_doc.get("repost_vouchers", {"name": row})[0])
						else:
							repost_doc.remove(repost_doc.get("vouchers", {"name": row})[0])

					repost_doc.flags.ignore_validate_update_after_submit = True
					repost_doc.flags.ignore_links = True
					repost_doc.save(ignore_permissions=True)

	def _remove_advance_payment_ledger_entries(self):
		adv = qb.DocType("Advance Payment Ledger Entry")
		qb.from_(adv).delete().where(adv.voucher_type.eq(self.doctype) & adv.voucher_no.eq(self.name)).run()

		if self.doctype in self.get_advance_payment_doctypes():
			qb.from_(adv).delete().where(
				adv.against_voucher_type.eq(self.doctype) & adv.against_voucher_no.eq(self.name)
			).run()

	def on_trash(self):
		from erpnext.accounts.utils import delete_exchange_gain_loss_journal

		self._remove_references_in_repost_doctypes()
		self._remove_references_in_unreconcile()
		self.remove_serial_and_batch_bundle()

		# delete sl and gl entries on deletion of transaction
		if frappe.get_single_value("Accounts Settings", "delete_linked_ledger_entries"):
			# delete linked exchange gain/loss journal
			delete_exchange_gain_loss_journal(self)

			ple = frappe.qb.DocType("Payment Ledger Entry")
			frappe.qb.from_(ple).delete().where(
				(ple.voucher_type == self.doctype) & (ple.voucher_no == self.name)
				| (
					(ple.against_voucher_type == self.doctype)
					& (ple.against_voucher_no == self.name)
					& ple.delinked
					== 1
				)
			).run()
			gle = frappe.qb.DocType("GL Entry")
			frappe.qb.from_(gle).delete().where(
				(gle.voucher_type == self.doctype) & (gle.voucher_no == self.name)
			).run()
			sle = frappe.qb.DocType("Stock Ledger Entry")
			frappe.qb.from_(sle).delete().where(
				(sle.voucher_type == self.doctype) & (sle.voucher_no == self.name)
			).run()

			self._remove_advance_payment_ledger_entries()

	def remove_serial_and_batch_bundle(self):
		bundles = frappe.get_all(
			"Serial and Batch Bundle",
			filters={"voucher_type": self.doctype, "voucher_no": self.name, "docstatus": ("!=", 1)},
		)

		for bundle in bundles:
			frappe.delete_doc("Serial and Batch Bundle", bundle.name)

		batches = frappe.get_all(
			"Batch", filters={"reference_doctype": self.doctype, "reference_name": self.name}
		)
		for row in batches:
			frappe.delete_doc("Batch", row.name)

	def validate_company_in_accounting_dimension(self):
		doc_field = DocType("DocField")
		accounting_dimension = DocType("Accounting Dimension")
		dimension_list = (
			frappe.qb.from_(accounting_dimension)
			.select(accounting_dimension.document_type)
			.join(doc_field)
			.on(doc_field.parent == accounting_dimension.document_type)
			.where(doc_field.fieldname == "company")
		).run(as_list=True)

		dimension_list = sum(dimension_list, ["Project", "Cost Center"])
		self.validate_company(dimension_list)

		for child in self.get_all_children() or []:
			self.validate_company(dimension_list, child)

	def validate_company(self, dimension_list, child=None):
		for dimension in dimension_list:
			if not child:
				dimension_value = self.get(frappe.scrub(dimension))
			else:
				dimension_value = child.get(frappe.scrub(dimension))

			if dimension_value:
				company = frappe.get_cached_value(dimension, dimension_value, "company")
				if company and company != self.company:
					frappe.throw(
						_("{0}: {1} does not belong to the Company: {2}").format(
							dimension, frappe.bold(dimension_value), self.company
						)
					)

	def validate_party_address_and_contact(self):
		party_type, party = self.get_party()

		if not (party_type and party):
			return

		if party_type == "Customer":
			billing_address, shipping_address = (
				self.get("customer_address"),
				self.get("shipping_address_name"),
			)
			self.validate_party_address(party, party_type, billing_address, shipping_address)
		elif party_type == "Supplier":
			billing_address = self.get("supplier_address")
			self.validate_party_address(party, party_type, billing_address)

		self.validate_party_contact(party, party_type)

	def validate_party_address(self, party, party_type, billing_address, shipping_address=None):
		if billing_address or shipping_address:
			party_address = frappe.get_all(
				"Dynamic Link",
				{"link_doctype": party_type, "link_name": party, "parenttype": "Address"},
				pluck="parent",
			)
			if billing_address and billing_address not in party_address:
				frappe.throw(_("Billing Address does not belong to the {0}").format(party))
			elif shipping_address and shipping_address not in party_address:
				frappe.throw(_("Shipping Address does not belong to the {0}").format(party))

	def validate_party_contact(self, party, party_type):
		if self.get("contact_person"):
			contact = frappe.get_all(
				"Dynamic Link",
				{"link_doctype": party_type, "link_name": party, "parenttype": "Contact"},
				pluck="parent",
			)
			if self.contact_person and self.contact_person not in contact:
				frappe.throw(_("Contact Person does not belong to the {0}").format(party))

	def validate_return_against_account(self):
		if self.doctype in ["Sales Invoice", "Purchase Invoice"] and self.is_return and self.return_against:
			cr_dr_account_field = "debit_to" if self.doctype == "Sales Invoice" else "credit_to"
			original_account = frappe.get_value(self.doctype, self.return_against, cr_dr_account_field)
			if original_account != self.get(cr_dr_account_field):
				frappe.throw(
					_(
						"Please set {0} to {1}, the same account that was used in the original invoice {2}."
					).format(
						frappe.bold(_(self.meta.get_label(cr_dr_account_field), context=self.doctype)),
						frappe.bold(original_account),
						frappe.bold(self.return_against),
					)
				)

	def validate_deferred_income_expense_account(self):
		field_map = {
			"Sales Invoice": "deferred_revenue_account",
			"Purchase Invoice": "deferred_expense_account",
		}

		for item in self.get("items"):
			if item.get("enable_deferred_revenue") or item.get("enable_deferred_expense"):
				if not item.get(field_map.get(self.doctype)):
					default_deferred_account = frappe.get_cached_value(
						"Company", self.company, "default_" + field_map.get(self.doctype)
					)
					if not default_deferred_account:
						frappe.throw(
							_(
								"Row #{0}: Please update deferred revenue/expense account in item row or default account in company master"
							).format(item.idx)
						)
					else:
						item.set(field_map.get(self.doctype), default_deferred_account)

	def validate_auto_repeat_subscription_dates(self):
		if self.get("from_date") and self.get("to_date") and getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("To Date cannot be before From Date"), title=_("Invalid Auto Repeat Date"))

	def validate_deferred_start_and_end_date(self):
		for d in self.items:
			if d.get("enable_deferred_revenue") or d.get("enable_deferred_expense"):
				if not (d.service_start_date and d.service_end_date):
					frappe.throw(
						_("Row #{0}: Service Start and End Date is required for deferred accounting").format(
							d.idx
						)
					)
				elif getdate(d.service_start_date) > getdate(d.service_end_date):
					frappe.throw(
						_("Row #{0}: Service Start Date cannot be greater than Service End Date").format(
							d.idx
						)
					)
				elif getdate(self.posting_date) > getdate(d.service_end_date):
					frappe.throw(
						_("Row #{0}: Service End Date cannot be before Invoice Posting Date").format(d.idx)
					)

	def validate_invoice_documents_schedule(self):
		if (
			self.is_return
			or (self.doctype == "Purchase Invoice" and self.is_paid)
			or (self.doctype == "Sales Invoice" and self.is_pos)
			or self.get("is_opening") == "Yes"
		):
			self.payment_terms_template = ""
			self.payment_schedule = []

		if self.is_return:
			return

		self.validate_payment_schedule_dates()
		self.set_due_date()
		self.set_payment_schedule()
		if not self.get("ignore_default_payment_terms_template"):
			self.validate_payment_schedule_amount()
			self.validate_due_date()
		self.validate_advance_entries()

	def validate_non_invoice_documents_schedule(self):
		self.set_payment_schedule()
		self.validate_payment_schedule_dates()
		self.validate_payment_schedule_amount()

	def validate_all_documents_schedule(self):
		if self.doctype in ("Sales Invoice", "Purchase Invoice"):
			self.validate_invoice_documents_schedule()
		elif self.doctype in ("Quotation", "Purchase Order", "Sales Order"):
			self.validate_non_invoice_documents_schedule()

	def before_print(self, settings=None):
		if self.doctype in [
			"Purchase Order",
			"Sales Order",
			"Sales Invoice",
			"Purchase Invoice",
			"Supplier Quotation",
			"Purchase Receipt",
			"Delivery Note",
			"Quotation",
		]:
			if self.get("group_same_items"):
				self.group_similar_items()

			df = self.meta.get_field("discount_amount")
			if self.get("discount_amount") and hasattr(self, "taxes") and not len(self.taxes):
				df.set("print_hide", 0)
				self.discount_amount = -self.discount_amount
			else:
				df.set("print_hide", 1)

		set_print_templates_for_item_table(self, settings)
		set_print_templates_for_taxes(self, settings)

	def calculate_paid_amount(self):
		if hasattr(self, "is_pos") or hasattr(self, "is_paid"):
			is_paid = self.get("is_pos") or self.get("is_paid")

			if is_paid:
				if not self.cash_bank_account:
					# show message that the amount is not paid
					frappe.throw(
						_(
							"Note: Payment Entry will not be created since 'Cash or Bank Account' was not specified"
						)
					)

				if cint(self.is_return) and self.grand_total > self.paid_amount:
					self.paid_amount = flt(flt(self.grand_total), self.precision("paid_amount"))

				elif not flt(self.paid_amount) and flt(self.outstanding_amount) > 0:
					self.paid_amount = flt(flt(self.outstanding_amount), self.precision("paid_amount"))

				self.base_paid_amount = flt(
					self.paid_amount * self.conversion_rate, self.precision("base_paid_amount")
				)
			else:
				self.paid_amount = 0
				self.base_paid_amount = 0

	def set_missing_values(self, for_validate=False):
		if frappe.in_test:
			for fieldname in ["posting_date", "transaction_date"]:
				if self.meta.get_field(fieldname) and not self.get(fieldname):
					self.set(fieldname, today())
					break

	def calculate_taxes_and_totals(self):
		from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals

		calculate_taxes_and_totals(self)

		if self.doctype in (
			"Sales Order",
			"Delivery Note",
			"Sales Invoice",
			"POS Invoice",
		):
			self.calculate_commission()
			self.calculate_contribution()

	def validate_date_with_fiscal_year(self):
		if self.meta.get_field("fiscal_year"):
			date_field = None
			if self.meta.get_field("posting_date"):
				date_field = "posting_date"
			elif self.meta.get_field("transaction_date"):
				date_field = "transaction_date"

			if date_field and self.get(date_field):
				validate_fiscal_year(
					self.get(date_field),
					self.fiscal_year,
					self.company,
					self.meta.get_label(date_field),
					self,
				)

	def validate_party_accounts(self):
		if self.doctype not in ("Sales Invoice", "Purchase Invoice"):
			return

		if self.doctype == "Sales Invoice":
			party_account_field = "debit_to"
			item_field = "income_account"
		else:
			party_account_field = "credit_to"
			item_field = "expense_account"

		for item in self.get("items"):
			if item.get(item_field) == self.get(party_account_field):
				frappe.throw(
					_("Row {0}: {1} {2} cannot be same as {3} (Party Account) {4}").format(
						item.idx,
						frappe.bold(frappe.unscrub(item_field)),
						item.get(item_field),
						frappe.bold(frappe.unscrub(party_account_field)),
						self.get(party_account_field),
					)
				)

	def validate_inter_company_reference(self):
		if self.get("is_return"):
			return

		if self.doctype not in ("Purchase Invoice", "Purchase Receipt"):
			return

		if self.is_internal_transfer():
			if not (
				self.get("inter_company_reference")
				or self.get("inter_company_invoice_reference")
				or self.get("inter_company_order_reference")
			) and not self.get("is_return"):
				msg = _("Internal Sale or Delivery Reference missing.")
				msg += _("Please create purchase from internal sale or delivery document itself")
				frappe.throw(msg, title=_("Internal Sales Reference Missing"))

			label = "Delivery Note Item" if self.doctype == "Purchase Receipt" else "Sales Invoice Item"

			field = frappe.scrub(label)

			for row in self.get("items"):
				if not row.get(field):
					msg = f"At Row {row.idx}: The field {bold(label)} is mandatory for internal transfer"
					frappe.throw(_(msg), title=_("Internal Transfer Reference Missing"))

	def validate_internal_transaction(self):
		if not cint(frappe.get_single_value("Accounts Settings", "maintain_same_internal_transaction_rate")):
			return

		doctypes_list = ["Sales Order", "Sales Invoice", "Purchase Order", "Purchase Invoice"]

		if self.doctype in doctypes_list and (
			self.get("is_internal_customer") or self.get("is_internal_supplier")
		):
			self.validate_internal_transaction_based_on_voucher_type()

	def validate_internal_transaction_based_on_voucher_type(self):
		order = ["Sales Order", "Purchase Order"]
		invoice = ["Sales Invoice", "Purchase Invoice"]

		if self.doctype in order and self.get("inter_company_order_reference"):
			# Fetch the linked order
			linked_doctype = "Sales Order" if self.doctype == "Purchase Order" else "Purchase Order"
			self.validate_line_items(
				linked_doctype,
				"sales_order" if linked_doctype == "Sales Order" else "purchase_order",
				"sales_order_item" if linked_doctype == "Sales Order" else "purchase_order_item",
			)
		elif self.doctype in invoice and self.get("inter_company_invoice_reference"):
			# Fetch the linked invoice
			linked_doctype = "Sales Invoice" if self.doctype == "Purchase Invoice" else "Purchase Invoice"
			self.validate_line_items(
				linked_doctype,
				"sales_invoice" if linked_doctype == "Sales Invoice" else "purchase_invoice",
				"sales_invoice_item" if linked_doctype == "Sales Invoice" else "purchase_invoice_item",
			)

	def validate_line_items(self, ref_dt, ref_dn_field, ref_link_field):
		action, role_allowed_to_override = frappe.get_cached_value(
			"Accounts Settings", "None", ["maintain_same_rate_action", "role_to_override_stop_action"]
		)

		reference_names = [d.get(ref_link_field) for d in self.get("items") if d.get(ref_link_field)]
		reference_details = self.get_reference_details(reference_names, ref_dt + " Item")

		stop_actions = []

		for d in self.get("items"):
			if d.get(ref_link_field):
				ref_rate = reference_details.get(d.get(ref_link_field))
				if ref_rate is not None and abs(flt(d.rate - ref_rate, d.precision("rate"))) >= 0.01:
					if action == "Stop":
						user_roles = [
							r["role"]
							for r in frappe.get_all(
								"Has Role", filters={"parent": frappe.session.user}, fields=["role"]
							)
						]
						if role_allowed_to_override not in user_roles:
							stop_actions.append(
								_("Row #{0}: Rate must be same as {1}: {2} ({3} / {4})").format(
									d.idx,
									ref_dt,
									self.inter_company_invoice_reference
									if d.parenttype in ("Sales Invoice", "Purchase Invoice")
									else d.get(ref_dn_field),
									d.rate,
									ref_rate,
								)
							)
					else:
						frappe.msgprint(
							_("Row #{0}: Rate must be same as {1}: {2} ({3} / {4})").format(
								d.idx,
								ref_dt,
								self.inter_company_invoice_reference
								if d.parenttype in ("Sales Invoice", "Purchase Invoice")
								else d.get(ref_dn_field),
								d.rate,
								ref_rate,
							),
							title=_("Warning"),
							indicator="orange",
						)

		if stop_actions:
			frappe.throw(stop_actions, as_list=True)

	def disable_pricing_rule_on_internal_transfer(self):
		if not self.get("ignore_pricing_rule") and self.is_internal_transfer():
			self.ignore_pricing_rule = 1
			frappe.msgprint(
				_("Disabled pricing rules since this {} is an internal transfer").format(self.doctype),
				alert=1,
			)

	def disable_tax_included_prices_for_internal_transfer(self):
		if self.is_internal_transfer():
			tax_updated = False
			for tax in self.get("taxes"):
				if tax.get("included_in_print_rate"):
					tax.included_in_print_rate = 0
					tax_updated = True

			if tax_updated:
				frappe.msgprint(
					_("Disabled tax included prices since this {} is an internal transfer").format(
						self.doctype
					),
					alert=1,
				)

	def validate_due_date(self):
		if self.get("is_pos") or self.doctype not in ["Sales Invoice", "Purchase Invoice"]:
			return

		from erpnext.accounts.party import validate_due_date

		posting_date = (
			self.posting_date if self.doctype == "Sales Invoice" else (self.bill_date or self.posting_date)
		)

		# skip due date validation for records via Data Import
		if frappe.flags.in_import and getdate(self.due_date) < getdate(posting_date):
			self.due_date = posting_date

		elif self.doctype in ["Sales Invoice", "Purchase Invoice"]:
			bill_date = self.bill_date if self.doctype == "Purchase Invoice" else None

			validate_due_date(
				posting_date=posting_date,
				due_date=self.due_date,
				bill_date=bill_date,
				template_name=self.payment_terms_template,
				doctype=self.doctype,
			)

	def set_price_list_currency(self, buying_or_selling):
		if self.meta.get_field("posting_date"):
			transaction_date = self.posting_date
		else:
			transaction_date = self.transaction_date

		if self.meta.get_field("currency"):
			# price list part
			if buying_or_selling.lower() == "selling":
				fieldname = "selling_price_list"
				args = "for_selling"
			else:
				fieldname = "buying_price_list"
				args = "for_buying"

			if self.meta.get_field(fieldname) and self.get(fieldname):
				self.price_list_currency = frappe.db.get_value("Price List", self.get(fieldname), "currency")

				if self.price_list_currency == self.company_currency:
					self.plc_conversion_rate = 1.0

				elif not self.plc_conversion_rate:
					self.plc_conversion_rate = get_exchange_rate(
						self.price_list_currency, self.company_currency, transaction_date, args
					)

			# currency
			if not self.currency:
				self.currency = self.price_list_currency
				self.conversion_rate = self.plc_conversion_rate
			elif self.currency == self.company_currency:
				self.conversion_rate = 1.0
			elif not self.conversion_rate:
				self.conversion_rate = get_exchange_rate(
					self.currency, self.company_currency, transaction_date, args
				)

			if (
				self.currency
				and buying_or_selling == "Buying"
				and frappe.db.get_single_value("Buying Settings", "use_transaction_date_exchange_rate")
				and self.doctype == "Purchase Invoice"
			):
				self.use_transaction_date_exchange_rate = True
				self.conversion_rate = get_exchange_rate(
					self.currency, self.company_currency, transaction_date, args
				)

	def set_missing_item_details(self, for_validate=False):
		"""set missing item values"""
		from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos

		if hasattr(self, "items"):
			parent_dict = {}
			for fieldname in self.meta.get_valid_columns():
				parent_dict[fieldname] = self.get(fieldname)

			if self.doctype in ["Quotation", "Sales Order", "Delivery Note", "Sales Invoice"]:
				document_type = f"{self.doctype} Item"
				parent_dict.update({"document_type": document_type})

			# party_name field used for customer in quotation
			if (
				self.doctype == "Quotation"
				and self.quotation_to == "Customer"
				and parent_dict.get("party_name")
			):
				parent_dict.update({"customer": parent_dict.get("party_name")})

			self.pricing_rules = []

			for item in self.get("items"):
				if item.get("item_code"):
					ctx: ItemDetailsCtx = ItemDetailsCtx(parent_dict.copy())
					ctx.update(item.as_dict())

					ctx.update(
						{
							"doctype": self.doctype,
							"name": self.name,
							"child_doctype": item.doctype,
							"child_docname": item.name,
							"ignore_pricing_rule": (
								self.ignore_pricing_rule if hasattr(self, "ignore_pricing_rule") else 0
							),
						}
					)

					if not ctx.transaction_date:
						ctx.transaction_date = ctx.posting_date

					if self.get("is_subcontracted"):
						ctx.is_subcontracted = self.is_subcontracted

					ret = get_item_details(ctx, self, for_validate=for_validate, overwrite_warehouse=False)
					for fieldname, value in ret.items():
						if item.meta.get_field(fieldname) and value is not None:
							if (
								item.get(fieldname) is None
								or fieldname in force_item_fields
								or (
									fieldname in ["serial_no", "batch_no"]
									and item.get("use_serial_batch_fields")
								)
							):
								item.set(fieldname, value)

								if fieldname == "batch_no" and item.batch_no and not item.is_free_item:
									if ret.get("rate"):
										item.set("rate", ret.get("rate"))

									if not item.get("price_list_rate") and ret.get("price_list_rate"):
										item.set("price_list_rate", ret.get("price_list_rate"))

							elif fieldname in ["cost_center", "conversion_factor"] and not item.get(
								fieldname
							):
								item.set(fieldname, value)
							elif fieldname == "item_tax_rate" and not (
								self.get("is_return") and self.get("return_against")
							):
								item.set(fieldname, value)
							elif fieldname == "serial_no":
								# Ensure that serial numbers are matched against Stock UOM
								item_conversion_factor = item.get("conversion_factor") or 1.0
								item_qty = abs(item.get("qty")) * item_conversion_factor

								if item_qty != len(get_serial_nos(item.get("serial_no"))):
									item.set(fieldname, value)

							elif (
								ret.get("pricing_rule_removed")
								and value is not None
								and fieldname
								in [
									"discount_percentage",
									"discount_amount",
									"rate",
									"margin_rate_or_amount",
									"margin_type",
									"remove_free_item",
								]
							):
								# reset pricing rule fields if pricing_rule_removed
								item.set(fieldname, value)

							elif fieldname == "expense_account" and not item.get("expense_account"):
								item.expense_account = value

					if self.doctype in ["Purchase Invoice", "Sales Invoice"] and item.meta.get_field(
						"is_fixed_asset"
					):
						item.set("is_fixed_asset", ret.get("is_fixed_asset", 0))

					if self.doctype in ["Purchase Invoice", "Sales Invoice"] and item.meta.get_field(
						"tax_withholding_category",
					):
						if not item.get("tax_withholding_category") and ret.get("tax_withholding_category"):
							item.set("tax_withholding_category", ret.get("tax_withholding_category"))

					# Double check for cost center
					# Items add via promotional scheme may not have cost center set
					if hasattr(item, "cost_center") and not item.get("cost_center"):
						item.set(
							"cost_center",
							self.get("cost_center") or erpnext.get_default_cost_center(self.company),
						)

					if ret.get("pricing_rules"):
						self.apply_pricing_rule_on_items(item, ret)
						self.set_pricing_rule_details(item, ret)
				else:
					# Transactions line item without item code

					uom = item.get("uom")
					stock_uom = item.get("stock_uom")
					if bool(uom) != bool(stock_uom):  # xor
						item.stock_uom = item.uom = uom or stock_uom

					# UOM cannot be zero so substitute as 1
					item.conversion_factor = (
						get_uom_conv_factor(item.get("uom"), item.get("stock_uom"))
						or item.get("conversion_factor")
						or 1
					)

			if self.doctype == "Purchase Invoice":
				self.set_expense_account(for_validate)

	def apply_pricing_rule_on_items(self, item, pricing_rule_args):
		if not pricing_rule_args.get("validate_applied_rule", 0):
			# if user changed the discount percentage then set user's discount percentage ?
			if pricing_rule_args.get("price_or_product_discount") == "Price":
				item.set("pricing_rules", pricing_rule_args.get("pricing_rules"))
				if pricing_rule_args.get("apply_rule_on_other_items"):
					other_items = json.loads(pricing_rule_args.get("apply_rule_on_other_items"))
					if other_items and item.item_code not in other_items:
						return

				item.set("discount_percentage", pricing_rule_args.get("discount_percentage"))
				item.set("discount_amount", pricing_rule_args.get("discount_amount"))
				if pricing_rule_args.get("pricing_rule_for") == "Rate":
					item.set("price_list_rate", pricing_rule_args.get("price_list_rate"))

				if item.get("price_list_rate"):
					item.rate = flt(
						item.price_list_rate * (1.0 - (flt(item.discount_percentage) / 100.0)),
						item.precision("rate"),
					)

					if item.get("discount_amount"):
						item.rate = item.price_list_rate - item.discount_amount

				if item.get("apply_discount_on_discounted_rate") and pricing_rule_args.get("rate"):
					item.rate = pricing_rule_args.get("rate")

			elif pricing_rule_args.get("free_item_data"):
				apply_pricing_rule_for_free_items(self, pricing_rule_args.get("free_item_data"))

		elif pricing_rule_args.get("validate_applied_rule"):
			for pricing_rule in get_applied_pricing_rules(item.get("pricing_rules")):
				pricing_rule_doc = frappe.get_cached_doc("Pricing Rule", pricing_rule)
				for field in ["discount_percentage", "discount_amount", "rate"]:
					if item.get(field) < pricing_rule_doc.get(field):
						title = get_link_to_form("Pricing Rule", pricing_rule)

						frappe.msgprint(
							_("Row {0}: user has not applied the rule {1} on the item {2}").format(
								item.idx, frappe.bold(title), frappe.bold(item.item_code)
							)
						)

	def set_pricing_rule_details(self, item_row, args):
		pricing_rules = get_applied_pricing_rules(args.get("pricing_rules"))
		if not pricing_rules:
			return

		for pricing_rule in pricing_rules:
			self.append(
				"pricing_rules",
				{
					"pricing_rule": pricing_rule,
					"item_code": item_row.item_code,
					"child_docname": item_row.name,
					"rule_applied": True,
				},
			)

	def get_gl_dict(self, args, account_currency=None, item=None):
		from erpnext.accounts.services.base_gl_composer import get_gl_dict

		return get_gl_dict(self, args, account_currency, item)

	def get_voucher_subtype(self):
		from erpnext.accounts.services.base_gl_composer import get_voucher_subtype

		return get_voucher_subtype(self)

	def get_value_in_transaction_currency(self, account_currency, gl_dict, field):
		from erpnext.accounts.services.base_gl_composer import get_value_in_transaction_currency

		return get_value_in_transaction_currency(self, account_currency, gl_dict, field)

	def validate_zero_qty_for_return_invoices_with_stock(self):
		rows = []
		for item in self.items:
			if not flt(item.qty):
				rows.append(item)
		if rows:
			frappe.throw(
				_(
					"For Return Invoices with Stock effect, '0' qty Items are not allowed. Following rows are affected: {0}"
				).format(frappe.bold(comma_and(["#" + str(x.idx) for x in rows])))
			)

	def validate_qty_is_not_zero(self):
		if self.flags.allow_zero_qty:
			return

		for item in self.items:
			if self.doctype == "Purchase Receipt" and item.rejected_qty:
				continue

			if not flt(item.qty):
				frappe.throw(
					msg=_("Row #{0}: Quantity for Item {1} cannot be zero.").format(
						item.idx, frappe.bold(item.item_code)
					),
					title=_("Invalid Quantity"),
					exc=InvalidQtyError,
				)

	def validate_account_currency(self, account, account_currency=None):
		from erpnext.accounts.services.base_gl_composer import validate_account_currency

		return validate_account_currency(self, account, account_currency)

	def clear_unallocated_advances(self, childtype, parentfield):
		self.set(parentfield, self.get(parentfield, {"allocated_amount": ["not in", [0, None, ""]]}))

		doctype = frappe.qb.DocType(childtype)
		frappe.qb.from_(doctype).delete().where(
			(doctype.parentfield == parentfield)
			& (doctype.parent == self.name)
			& (doctype.allocated_amount == 0)
		).run()

	@frappe.whitelist()
	def apply_shipping_rule(self):
		if self.shipping_rule:
			shipping_rule = frappe.get_doc("Shipping Rule", self.shipping_rule)
			shipping_rule.apply(self)
			self.calculate_taxes_and_totals()

	def get_shipping_address(self):
		"""Returns Address object from shipping address fields if present"""

		# shipping address fields can be `shipping_address_name` or `shipping_address`
		# try getting value from both

		for fieldname in ("shipping_address_name", "shipping_address"):
			shipping_field = self.meta.get_field(fieldname)
			if shipping_field and shipping_field.fieldtype == "Link":
				if self.get(fieldname):
					return frappe.get_doc("Address", self.get(fieldname))

		return {}

	@frappe.whitelist()
	def set_advances(self):
		from erpnext.accounts.services.advances import set_advances

		set_advances(self)

	def get_advance_entries(self, include_unallocated=True):
		from erpnext.accounts.services.advances import get_advance_entries

		return get_advance_entries(self, include_unallocated)

	def is_inclusive_tax(self):
		is_inclusive = cint(frappe.get_single_value("Accounts Settings", "show_inclusive_tax_in_print"))

		if is_inclusive:
			is_inclusive = 0
			if self.get("taxes", filters={"included_in_print_rate": 1}):
				is_inclusive = 1

		return is_inclusive

	def should_show_taxes_as_table_in_print(self):
		return cint(frappe.get_single_value("Accounts Settings", "show_taxes_as_table_in_print"))

	def validate_advance_entries(self):
		from erpnext.accounts.services.advances import validate_advance_entries

		validate_advance_entries(self)

	def set_advance_gain_or_loss(self):
		from erpnext.accounts.services.advances import set_advance_gain_or_loss

		set_advance_gain_or_loss(self)

	def make_precision_loss_gl_entry(self, gl_entries):
		from erpnext.accounts.services.exchange_gain_loss import make_precision_loss_gl_entry

		make_precision_loss_gl_entry(self, gl_entries)

	def gain_loss_journal_already_booked(
		self, gain_loss_account, exc_gain_loss, ref2_dt, ref2_dn, ref2_detail_no
	) -> bool:
		from erpnext.accounts.services.exchange_gain_loss import gain_loss_journal_already_booked

		return gain_loss_journal_already_booked(
			gain_loss_account, exc_gain_loss, ref2_dt, ref2_dn, ref2_detail_no
		)

	def make_exchange_gain_loss_journal(
		self, args: dict | None = None, dimensions_dict: dict | None = None
	) -> None:
		from erpnext.accounts.services.exchange_gain_loss import make_exchange_gain_loss_journal

		make_exchange_gain_loss_journal(self, args, dimensions_dict)

	def is_payable_account(self, reference_doctype, account):
		from erpnext.accounts.services.exchange_gain_loss import is_payable_account

		return is_payable_account(reference_doctype, account)

	def update_against_document_in_jv(self):
		"""
		Links invoice and advance voucher:
		        1. cancel advance voucher
		        2. split into multiple rows if partially adjusted, assign against voucher
		        3. submit advance voucher
		"""

		if self.doctype == "Sales Invoice":
			party_type = "Customer"
			party = self.customer
			party_account = self.debit_to
			dr_or_cr = "credit_in_account_currency"
		else:
			party_type = "Supplier"
			party = self.supplier
			party_account = self.credit_to
			dr_or_cr = "debit_in_account_currency"

		lst = []
		for d in self.get("advances"):
			if flt(d.allocated_amount) > 0:
				args = frappe._dict(
					{
						"voucher_type": d.reference_type,
						"voucher_no": d.reference_name,
						"voucher_detail_no": d.reference_row,
						"against_voucher_type": self.doctype,
						"against_voucher": self.name,
						"account": party_account,
						"party_type": party_type,
						"party": party,
						"is_advance": "Yes",
						"dr_or_cr": dr_or_cr,
						"unadjusted_amount": flt(d.advance_amount),
						"allocated_amount": flt(d.allocated_amount),
						"precision": d.precision("advance_amount"),
						"exchange_rate": (
							self.conversion_rate
							if self.party_account_currency != self.company_currency
							else 1
						),
						"grand_total": (
							self.base_grand_total
							if self.party_account_currency == self.company_currency
							else self.grand_total
						),
						"outstanding_amount": self.outstanding_amount,
						"difference_account": frappe.get_cached_value(
							"Company", self.company, "exchange_gain_loss_account"
						),
						"exchange_gain_loss": flt(d.get("exchange_gain_loss")),
						"difference_posting_date": d.get("difference_posting_date"),
					}
				)
				lst.append(args)

		if lst:
			from erpnext.accounts.utils import reconcile_against_document

			# pass dimension values to utility method
			active_dimensions = get_dimensions()[0]
			for x in lst:
				for dim in active_dimensions:
					if self.get(dim.fieldname):
						x.update({dim.fieldname: self.get(dim.fieldname)})
			reconcile_against_document(lst, active_dimensions=active_dimensions)

	def cancel_system_generated_credit_debit_notes(self):
		# Cancel 'Credit/Debit' Note Journal Entries, if found.
		if self.doctype in ["Sales Invoice", "Purchase Invoice"]:
			voucher_type = "Credit Note" if self.doctype == "Sales Invoice" else "Debit Note"
			journals = frappe.db.get_all(
				"Journal Entry",
				filters={
					"is_system_generated": 1,
					"reference_type": self.doctype,
					"reference_name": self.name,
					"voucher_type": voucher_type,
					"docstatus": 1,
				},
				pluck="name",
			)
			for x in journals:
				frappe.get_doc("Journal Entry", x).cancel()

	def on_cancel(self):
		from erpnext.accounts.doctype.bank_transaction.bank_transaction import (
			remove_from_bank_transaction,
		)
		from erpnext.accounts.utils import (
			cancel_common_party_journal,
			cancel_exchange_gain_loss_journal,
			unlink_ref_doc_from_payment_entries,
		)

		remove_from_bank_transaction(self.doctype, self.name)

		if self.doctype in ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"]:
			self.cancel_system_generated_credit_debit_notes()

			# Cancel Exchange Gain/Loss Journal before unlinking
			cancel_exchange_gain_loss_journal(self)
			cancel_common_party_journal(self)

			if frappe.get_single_value("Accounts Settings", "unlink_payment_on_cancellation_of_invoice"):
				unlink_ref_doc_from_payment_entries(self)

		elif self.doctype in ["Sales Order", "Purchase Order"]:
			if frappe.get_single_value("Accounts Settings", "unlink_advance_payment_on_cancelation_of_order"):
				unlink_ref_doc_from_payment_entries(self)

			if self.doctype == "Sales Order":
				self.unlink_ref_doc_from_po()

	def unlink_ref_doc_from_po(self):
		so_items = []
		for item in self.items:
			so_items.append(item.name)

		linked_po = list(
			set(
				frappe.get_all(
					"Purchase Order Item",
					filters={
						"sales_order": self.name,
						"sales_order_item": ["in", so_items],
						"docstatus": ["<", 2],
					},
					pluck="parent",
				)
			)
		)

		if linked_po:
			frappe.db.set_value(
				"Purchase Order Item",
				{"sales_order": self.name, "sales_order_item": ["in", so_items], "docstatus": ["<", 2]},
				{"sales_order": None, "sales_order_item": None},
			)

			frappe.msgprint(_("Purchase Orders {0} are un-linked").format("\n".join(linked_po)))

	def validate_multiple_billing(self, ref_dt: str, item_ref_dn: str, based_on: str) -> None:
		from erpnext.accounts.services.billing_validation import validate_multiple_billing

		validate_multiple_billing(self, ref_dt, item_ref_dn, based_on)

	def get_billing_reference_details(
		self, reference_names: list, reference_doctype: str, based_on: str
	) -> frappe._dict:
		from erpnext.accounts.services.billing_validation import get_billing_reference_details

		return get_billing_reference_details(self, reference_names, reference_doctype, based_on)

	def get_reference_wise_billed_amt(self, ref_dt: str, item_ref_dn: str, based_on: str) -> dict | None:
		from erpnext.accounts.services.billing_validation import get_reference_wise_billed_amt

		return get_reference_wise_billed_amt(self, ref_dt, item_ref_dn, based_on)

	def get_already_billed_amount(
		self, reference_names: list, item_ref_dn: str, based_on: str
	) -> frappe._dict:
		from erpnext.accounts.services.billing_validation import get_already_billed_amount

		return get_already_billed_amount(self, reference_names, item_ref_dn, based_on)

	def throw_overbill_exception(self, overbilled_items: list, precision: int) -> None:
		from erpnext.accounts.services.billing_validation import throw_overbill_exception

		throw_overbill_exception(self, overbilled_items, precision)

	def get_company_default(self, fieldname, ignore_validation=False):
		from erpnext.accounts.utils import get_company_default

		return get_company_default(self.company, fieldname, ignore_validation=ignore_validation)

	def get_stock_items(self):
		stock_items = []
		item_codes = list(set(item.item_code for item in self.get("items")))
		if item_codes:
			stock_items = frappe.db.get_values(
				"Item", {"name": ["in", item_codes], "is_stock_item": 1}, pluck="name", cache=True
			)

		return stock_items

	def get_asset_items(self):
		asset_items = []
		item_codes = list(set(item.item_code for item in self.get("items")))
		if item_codes:
			asset_items = frappe.db.get_values(
				"Item", {"name": ["in", item_codes], "is_fixed_asset": 1}, pluck="name", cache=True
			)

		return asset_items

	def calculate_total_advance_from_ledger(self):
		from erpnext.accounts.services.advances import calculate_total_advance_from_ledger

		return calculate_total_advance_from_ledger(self)

	def set_total_advance_paid(self):
		from erpnext.accounts.services.advances import set_total_advance_paid

		set_total_advance_paid(self)

	def set_advance_payment_status(self):
		from erpnext.accounts.services.advances import set_advance_payment_status

		set_advance_payment_status(self)

	@property
	def company_abbr(self):
		if not hasattr(self, "_abbr"):
			self._abbr = frappe.get_cached_value("Company", self.company, "abbr")

		return self._abbr

	def raise_missing_debit_credit_account_error(self, party_type, party):
		"""Raise an error if debit to/credit to account does not exist."""
		db_or_cr = (
			frappe.bold(_("Debit To")) if self.doctype == "Sales Invoice" else frappe.bold(_("Credit To"))
		)
		rec_or_pay = "Receivable" if self.doctype == "Sales Invoice" else "Payable"

		link_to_party = frappe.utils.get_link_to_form(party_type, party)
		link_to_company = frappe.utils.get_link_to_form("Company", self.company)

		message = _("{0} Account not found against Customer {1}.").format(db_or_cr, frappe.bold(party) or "")
		message += "<br>" + _("Please set one of the following:") + "<br>"
		message += (
			"<br><ul><li>"
			+ _("'Account' in the Accounting section of Customer {0}").format(link_to_party)
			+ "</li>"
		)
		message += (
			"<li>"
			+ _("'Default {0} Account' in Company {1}").format(rec_or_pay, link_to_company)
			+ "</li></ul>"
		)

		frappe.throw(message, title=_("Account Missing"), exc=AccountMissingError)

	def validate_party(self):
		party_type, party = self.get_party()
		validate_party_frozen_disabled(self.company, party_type, party)

	def get_party(self):
		party_type = None
		if self.doctype in ("Opportunity", "Quotation", "Sales Order", "Delivery Note", "Sales Invoice"):
			party_type = "Customer"

		elif self.doctype in (
			"Supplier Quotation",
			"Purchase Order",
			"Purchase Receipt",
			"Purchase Invoice",
		):
			party_type = "Supplier"

		elif self.meta.get_field("customer"):
			party_type = "Customer"

		elif self.meta.get_field("supplier"):
			party_type = "Supplier"

		party = self.get(party_type.lower()) if party_type else None

		return party_type, party

	def validate_currency(self):
		if self.get("currency"):
			party_type, party = self.get_party()
			if party_type and party:
				party_account_currency = get_party_account_currency(party_type, party, self.company)

				if (
					party_account_currency
					and party_account_currency != self.company_currency
					and self.currency != party_account_currency
				):
					frappe.throw(
						_("Accounting Entry for {0}: {1} can only be made in currency: {2}").format(
							party_type, party, party_account_currency
						),
						InvalidCurrency,
					)

				# Note: not validating with gle account because we don't have the account
				# at quotation / sales order level and we shouldn't stop someone
				# from creating a sales invoice if sales order is already created

	def validate_party_account_currency(self):
		if self.doctype not in ("Sales Invoice", "Purchase Invoice"):
			return

		if self.is_opening == "Yes":
			return

		party_type, party = self.get_party()
		party_gle_currency = get_party_gle_currency(party_type, party, self.company)
		party_account = self.get("debit_to") if self.doctype == "Sales Invoice" else self.get("credit_to")
		party_account_currency = get_account_currency(party_account)
		allow_multi_currency_invoices_against_single_party_account = frappe.db.get_singles_value(
			"Accounts Settings", "allow_multi_currency_invoices_against_single_party_account"
		)

		if (
			not party_gle_currency
			and (party_account_currency != self.currency)
			and not allow_multi_currency_invoices_against_single_party_account
		):
			frappe.throw(
				_("Party Account {0} currency ({1}) and document currency ({2}) should be same").format(
					frappe.bold(party_account), party_account_currency, self.currency
				)
			)

	def delink_advance_entries(self, linked_doc_name):
		from erpnext.accounts.services.advances import delink_advance_entries

		delink_advance_entries(self, linked_doc_name)

	def group_similar_items(self):
		grouped_items = {}
		# to update serial number in print
		count = 0

		fields_to_group = frappe.get_hooks("fields_for_group_similar_items")
		fields_to_group = set(fields_to_group)

		for item in self.items:
			item_values = grouped_items.setdefault(item.item_code, defaultdict(int))

			for field in fields_to_group:
				item_values[field] += item.get(field, 0)

		duplicate_list = []
		for item in self.items:
			if item.item_code in grouped_items:
				count += 1

				for field in fields_to_group:
					item.set(field, grouped_items[item.item_code][field])

				if item.qty:
					item.rate = flt(flt(item.amount) / flt(item.qty), item.precision("rate"))
				else:
					item.rate = 0

				item.idx = count
				del grouped_items[item.item_code]
			else:
				duplicate_list.append(item)
		for item in duplicate_list:
			self.remove(item)

	def set_payment_schedule(self) -> None:
		from erpnext.accounts.services.payment_schedule import set_payment_schedule

		set_payment_schedule(self)

	def get_order_details(self) -> tuple:
		from erpnext.accounts.services.payment_schedule import get_order_details

		return get_order_details(self)

	def linked_order_has_payment_terms(self, po_or_so, fieldname, doctype) -> bool:
		from erpnext.accounts.services.payment_schedule import linked_order_has_payment_terms

		return linked_order_has_payment_terms(self, po_or_so, fieldname, doctype)

	def all_items_have_same_po_or_so(self, po_or_so, fieldname) -> bool:
		from erpnext.accounts.services.payment_schedule import all_items_have_same_po_or_so

		return all_items_have_same_po_or_so(self, po_or_so, fieldname)

	def linked_order_has_payment_terms_template(self, po_or_so, doctype) -> str | None:
		from erpnext.accounts.services.payment_schedule import linked_order_has_payment_terms_template

		return linked_order_has_payment_terms_template(po_or_so, doctype)

	def linked_order_has_payment_schedule(self, po_or_so) -> list:
		from erpnext.accounts.services.payment_schedule import linked_order_has_payment_schedule

		return linked_order_has_payment_schedule(po_or_so)

	def fetch_payment_terms_from_order(
		self,
		po_or_so,
		po_or_so_doctype,
		grand_total,
		base_grand_total,
		automatically_fetch_payment_terms,
	) -> None:
		from erpnext.accounts.services.payment_schedule import fetch_payment_terms_from_order

		fetch_payment_terms_from_order(
			self, po_or_so, po_or_so_doctype, grand_total, base_grand_total, automatically_fetch_payment_terms
		)

	def set_due_date(self) -> None:
		from erpnext.accounts.services.payment_schedule import set_due_date

		set_due_date(self)

	def validate_payment_schedule_dates(self) -> None:
		from erpnext.accounts.services.payment_schedule import validate_payment_schedule_dates

		validate_payment_schedule_dates(self)

	def validate_payment_schedule_amount(self) -> None:
		from erpnext.accounts.services.payment_schedule import validate_payment_schedule_amount

		validate_payment_schedule_amount(self)

	def is_rounded_total_disabled(self):
		if self.meta.get_field("disable_rounded_total"):
			return self.disable_rounded_total
		else:
			return frappe.db.get_single_value("Global Defaults", "disable_rounded_total")

	def set_inter_company_account(self):
		"""
		Set intercompany account for inter warehouse transactions
		This account will be used in case billing company and internal customer's
		representation company is same
		"""

		if self.is_internal_transfer() and not self.unrealized_profit_loss_account:
			unrealized_profit_loss_account = frappe.get_cached_value(
				"Company", self.company, "unrealized_profit_loss_account"
			)

			if not unrealized_profit_loss_account:
				msg = _(
					"Please select Unrealized Profit / Loss account or add default Unrealized Profit / Loss account account for company {0}"
				).format(frappe.bold(self.company))
				frappe.throw(msg)

			self.unrealized_profit_loss_account = unrealized_profit_loss_account

	def is_internal_transfer(self):
		"""
		It will an internal transfer if its an internal customer and representation
		company is same as billing company
		"""
		if self.doctype in ("Sales Invoice", "Delivery Note", "Sales Order"):
			internal_party_field = "is_internal_customer"
		elif self.doctype in ("Purchase Invoice", "Purchase Receipt", "Purchase Order"):
			internal_party_field = "is_internal_supplier"
		else:
			return False

		if self.get(internal_party_field) and (self.represents_company == self.company):
			return True

		return False

	def process_common_party_accounting(self):
		is_invoice = self.doctype in ["Sales Invoice", "Purchase Invoice"]
		if not is_invoice:
			return

		if frappe.get_single_value("Accounts Settings", "enable_common_party_accounting"):
			party_link = self.get_common_party_link()
			if party_link and self.outstanding_amount:
				self.create_advance_and_reconcile(party_link)

	def get_common_party_link(self):
		party_type, party = self.get_party()
		return frappe.db.get_value(
			doctype="Party Link",
			filters={"secondary_role": party_type, "secondary_party": party},
			fieldname=["primary_role", "primary_party"],
			as_dict=True,
		)

	def create_advance_and_reconcile(self, party_link):
		from erpnext.accounts.services.advances import create_advance_and_reconcile

		create_advance_and_reconcile(self, party_link)

	def check_conversion_rate(self):
		default_currency = erpnext.get_company_currency(self.company)
		if not default_currency:
			throw(_("Please enter default currency in Company Master"))

		if not self.conversion_rate:
			throw(_("Conversion rate cannot be 0"))

		if self.currency == default_currency and flt(self.conversion_rate) != 1.00:
			throw(_("Conversion rate must be 1.00 if document currency is same as company currency"))

		if self.currency != default_currency and flt(self.conversion_rate) == 1.00:
			frappe.msgprint(
				_("Conversion rate is 1.00, but document currency is different from company currency")
			)

	def check_finance_books(self, item, asset):
		if (
			len(asset.finance_books) > 1
			and not item.get("finance_book")
			and not self.get("finance_book")
			and asset.finance_books[0].finance_book
		):
			frappe.throw(
				_("Select finance book for the item {0} at row {1}").format(item.item_code, item.idx)
			)

	def check_if_fields_updated(self, fields_to_check, child_tables):
		# Check if any field affecting accounting entry is altered
		doc_before_update = self.get_doc_before_save()
		accounting_dimensions = [*get_accounting_dimensions(), "cost_center", "project"]

		# Parent Level Accounts excluding party account
		fields_to_check += accounting_dimensions
		for field in fields_to_check:
			if doc_before_update.get(field) != self.get(field):
				return True

		# Check for child tables
		for table in child_tables:
			if check_if_child_table_updated(
				doc_before_update.get(table), self.get(table), child_tables[table]
			):
				return True

		return False

	@frappe.whitelist()
	def repost_accounting_entries(self):
		repost_ledger = frappe.new_doc("Repost Accounting Ledger")
		repost_ledger.company = self.company
		repost_ledger.append("vouchers", {"voucher_type": self.doctype, "voucher_no": self.name})
		repost_ledger.flags.ignore_permissions = True
		repost_ledger.insert()
		repost_ledger.submit()

	def get_advance_payment_doctypes(self, payment_type=None) -> list:
		return _get_advance_payment_doctypes(payment_type=payment_type)

	def set_transaction_currency_and_rate_in_gl_map(self, gl_entries: list) -> None:
		from erpnext.accounts.services.exchange_gain_loss import set_transaction_currency_and_rate_in_gl_map

		set_transaction_currency_and_rate_in_gl_map(self, gl_entries)

	def after_mapping(self, source_doc):
		self.set_discount_amount_after_mapping(source_doc)

	def set_discount_amount_after_mapping(self, source_doc):
		"""
		Ensures that Additional Discount Amount is not copied repeatedly
		for multiple mappings of a single source transaction.
		"""

		# source and target doctypes should both be buying / selling
		for transaction_types in (PURCHASE_TRANSACTION_TYPES, SALES_TRANSACTION_TYPES):
			if self.doctype in transaction_types and source_doc.doctype in transaction_types:
				break

		else:
			return

		# ensure both doctypes have discount_amount field
		if not self.meta.get_field("discount_amount") or not source_doc.meta.get_field("discount_amount"):
			return

		# ensure discount_amount is set in source doc
		if not source_doc.discount_amount:
			return

		# ensure additional_discount_percentage is not set in the source doc
		if source_doc.get("additional_discount_percentage"):
			return

		item_doctype = self.meta.get_field("items").options
		doctype_table = frappe.qb.DocType(self.doctype)
		item_table = frappe.qb.DocType(item_doctype)

		is_same_doctype = self.doctype == source_doc.doctype
		is_return = self.get("is_return") and is_same_doctype

		if is_same_doctype and not is_return:
			# should never happen
			# you don't map to the same doctype without it being a return
			return

		query = (
			frappe.qb.from_(doctype_table)
			.where(doctype_table.docstatus == 1)
			.where(doctype_table.discount_amount != 0)
			.select(Sum(doctype_table.discount_amount))
		)

		if is_return:
			query = query.where(doctype_table.is_return == 1).where(
				doctype_table.return_against == source_doc.name
			)

		else:
			item_meta = frappe.get_meta(item_doctype)
			reference_fieldname = next(
				(
					row.fieldname
					for row in item_meta.fields
					if row.fieldtype == "Link"
					and row.options == source_doc.doctype
					and not row.get("is_custom_field")
				),
				None,
			)

			if not reference_fieldname:
				return

			query = query.where(
				doctype_table.name.isin(
					frappe.qb.from_(item_table)
					.select(item_table.parent)
					.where(item_table[reference_fieldname] == source_doc.name)
					.distinct()
				)
			)

		result = query.run()
		if not result:
			return

		discount_already_applied = result[0][0]
		if not discount_already_applied:
			return

		if is_return:
			# returns have negative discount
			discount_already_applied *= -1

		discount_amount = max(source_doc.discount_amount - discount_already_applied, 0)
		if discount_amount and is_return:
			discount_amount *= -1

		self.discount_amount = flt(discount_amount, self.precision("discount_amount"))

		self.calculate_taxes_and_totals()


from erpnext.accounts.services.advances import (
	get_advance_journal_entries,
	get_advance_payment_entries,
	get_advance_payment_entries_for_regional,
	get_common_query,
)
from erpnext.accounts.services.taxes import (
	add_taxes_from_tax_template,
	get_default_taxes_and_charges,
	get_tax_rate,
	get_taxes_and_charges,
	merge_taxes,
	set_balance_in_account_currency,
	set_child_tax_template_and_map,
	validate_account_head,
	validate_conversion_rate,
	validate_cost_center,
	validate_inclusive_tax,
	validate_taxes_and_charges,
)


def update_invoice_status():
	"""Updates status as Overdue for applicable invoices. Runs daily."""
	today = getdate()
	payment_schedule = frappe.qb.DocType("Payment Schedule")
	for doctype in ("Sales Invoice", "Purchase Invoice"):
		invoice = frappe.qb.DocType(doctype)

		consider_base_amount = invoice.party_account_currency != invoice.currency
		payment_amount = (
			frappe.qb.terms.Case()
			.when(consider_base_amount, payment_schedule.base_payment_amount)
			.else_(payment_schedule.payment_amount)
		)

		payable_amount = (
			frappe.qb.from_(payment_schedule)
			.select(Sum(payment_amount))
			.where((payment_schedule.parent == invoice.name) & (payment_schedule.due_date < today))
		)

		total = (
			frappe.qb.terms.Case()
			.when(invoice.disable_rounded_total, invoice.grand_total)
			.else_(invoice.rounded_total)
		)

		base_total = (
			frappe.qb.terms.Case()
			.when(invoice.disable_rounded_total, invoice.base_grand_total)
			.else_(invoice.base_rounded_total)
		)

		total_amount = frappe.qb.terms.Case().when(consider_base_amount, base_total).else_(total)

		is_overdue = total_amount - invoice.outstanding_amount < payable_amount

		conditions = (
			(invoice.docstatus == 1)
			& (invoice.outstanding_amount > 0)
			& (invoice.status.like("Unpaid%") | invoice.status.like("Partly Paid%"))
			& (
				((invoice.is_pos & invoice.due_date < today) | is_overdue)
				if doctype == "Sales Invoice"
				else is_overdue
			)
		)

		status = (
			frappe.qb.terms.Case()
			.when(invoice.status.like("%Discounted"), "Overdue and Discounted")
			.else_("Overdue")
		)

		frappe.qb.update(invoice).set("status", status).where(conditions).run()


from erpnext.accounts.services.payment_schedule import (
	get_discount_date,
	get_due_date,
	get_payment_term_details,
	get_payment_terms,
)


def get_supplier_block_status(party_name):
	"""
	Returns a dict containing the values of `on_hold`, `release_date` and `hold_type` of
	a `Supplier`
	"""
	supplier = frappe.get_doc("Supplier", party_name)
	info = {
		"on_hold": supplier.on_hold,
		"release_date": supplier.release_date,
		"hold_type": supplier.hold_type,
	}
	return info


def set_order_defaults(parent_doctype, parent_doctype_name, child_doctype, child_docname, trans_item):
	"""
	Returns a Sales/Purchase Order Item child item containing the default values
	"""
	p_doc = frappe.get_doc(parent_doctype, parent_doctype_name)
	child_item = frappe.new_doc(child_doctype, parent_doc=p_doc, parentfield=child_docname)
	item = frappe.get_doc("Item", trans_item.get("item_code"))

	for field in ("item_code", "item_name", "description", "item_group", "weight_per_unit", "weight_uom"):
		child_item.update({field: item.get(field)})

	date_fieldname = "delivery_date" if child_doctype == "Sales Order Item" else "schedule_date"
	child_item.update({date_fieldname: trans_item.get(date_fieldname) or p_doc.get(date_fieldname)})
	child_item.stock_uom = item.stock_uom
	child_item.uom = trans_item.get("uom") or item.stock_uom
	child_item.warehouse = get_item_warehouse_(p_doc, item, overwrite_warehouse=True)
	conversion_factor = flt(get_conversion_factor(item.item_code, child_item.uom).get("conversion_factor"))
	child_item.conversion_factor = flt(trans_item.get("conversion_factor")) or conversion_factor
	child_item.update(get_bin_details(child_item.item_code, child_item.warehouse, p_doc.get("company")))

	if child_doctype in ["Purchase Order Item", "Supplier Quotation Item"]:
		# Initialized value will update in parent validation
		child_item.base_rate = 1
		child_item.base_amount = 1
	if child_doctype == "Sales Order Item":
		child_item.warehouse = get_item_warehouse_(p_doc, item, overwrite_warehouse=True)
		if not child_item.warehouse:
			frappe.throw(
				_(
					"Cannot find a default warehouse for item {0}. Please set one in the Item Master or in Stock Settings."
				).format(frappe.bold(item.item_code))
			)

	set_child_tax_template_and_map(item, child_item, p_doc)
	add_taxes_from_tax_template(child_item, p_doc)
	return child_item


def validate_child_on_delete(row, parent, ordered_item=None):
	"""Check if partially transacted item (row) is being deleted."""
	if parent.doctype == "Sales Order":
		if flt(row.delivered_qty):
			frappe.throw(
				_("Row #{0}: Cannot delete item {1} which has already been delivered").format(
					row.idx, row.item_code
				)
			)
		if flt(row.work_order_qty):
			frappe.throw(
				_("Row #{0}: Cannot delete item {1} which has work order assigned to it.").format(
					row.idx, row.item_code
				)
			)
		if flt(row.ordered_qty):
			frappe.throw(
				_(
					"Row #{0}: Cannot delete item {1} which is already ordered against this Sales Order."
				).format(row.idx, row.item_code)
			)

	if parent.doctype == "Purchase Order" and flt(row.received_qty):
		frappe.throw(
			_("Row #{0}: Cannot delete item {1} which has already been received").format(
				row.idx, row.item_code
			)
		)
	if parent.doctype in ["Purchase Order", "Sales Order"]:
		if flt(row.billed_amt):
			frappe.throw(
				_("Row #{0}: Cannot delete item {1} which has already been billed.").format(
					row.idx, row.item_code
				)
			)

	if parent.doctype == "Quotation":
		if ordered_item.get(row.name):
			frappe.throw(_("Cannot delete an item which has been ordered"))


def update_bin_on_delete(row, doctype):
	"""Update bin for deleted item (row)."""
	from erpnext.stock.stock_balance import (
		get_indented_qty,
		get_ordered_qty,
		get_reserved_qty,
		update_bin_qty,
	)

	qty_dict = {}

	if doctype == "Sales Order":
		qty_dict["reserved_qty"] = get_reserved_qty(row.item_code, row.warehouse)
	else:
		if row.material_request_item:
			qty_dict["indented_qty"] = get_indented_qty(row.item_code, row.warehouse)

		qty_dict["ordered_qty"] = get_ordered_qty(row.item_code, row.warehouse)

	if row.warehouse:
		update_bin_qty(row.item_code, row.warehouse, qty_dict)


def validate_and_delete_children(parent, data, ordered_item=None) -> bool:
	deleted_children = []
	updated_item_names = [d.get("docname") for d in data]
	for item in parent.items:
		if item.name not in updated_item_names:
			deleted_children.append(item)

	for d in deleted_children:
		validate_child_on_delete(d, parent, ordered_item)
		d.cancel()
		d.delete()

	if parent.doctype == "Purchase Order":
		parent.update_ordered_qty_in_so_for_removed_items(deleted_children)

	# need to update ordered qty in Material Request first
	# bin uses Material Request Items to recalculate & update
	if parent.doctype not in ["Quotation", "Supplier Quotation"]:
		parent.update_prevdoc_status()
		for d in deleted_children:
			update_bin_on_delete(d, parent.doctype)

	return bool(deleted_children)


def get_allow_zero_qty(parent_doctype: str) -> bool:
	if parent_doctype == "Sales Order":
		return frappe.db.get_single_value("Selling Settings", "allow_zero_qty_in_sales_order") or False
	if parent_doctype == "Purchase Order":
		return frappe.db.get_single_value("Buying Settings", "allow_zero_qty_in_purchase_order") or False
	return False


def get_child_item_change_state(parent_doctype: str, child_item, new_data) -> frappe._dict:
	prev_rate, new_rate = flt(child_item.get("rate")), flt(new_data.get("rate"))
	prev_qty, new_qty = flt(child_item.get("qty")), flt(new_data.get("qty"))
	prev_fg_qty, new_fg_qty = flt(child_item.get("fg_item_qty")), flt(new_data.get("fg_item_qty"))
	prev_con_fac, new_con_fac = (
		flt(child_item.get("conversion_factor")),
		flt(new_data.get("conversion_factor")),
	)

	if parent_doctype == "Sales Order":
		prev_date, new_date = child_item.get("delivery_date"), new_data.get("delivery_date")
	elif parent_doctype == "Purchase Order":
		prev_date, new_date = child_item.get("schedule_date"), new_data.get("schedule_date")
	else:
		prev_date, new_date = None, None

	if parent_doctype in ["Quotation", "Supplier Quotation"]:
		date_unchanged = False
	else:
		prev_date = getdate(prev_date) if prev_date else None
		new_date = getdate(new_date) if new_date else None
		date_unchanged = prev_date == new_date

	return frappe._dict(
		rate_unchanged=prev_rate == new_rate,
		qty_unchanged=prev_qty == new_qty,
		fg_qty_unchanged=prev_fg_qty == new_fg_qty,
		uom_unchanged=child_item.get("uom") == new_data.get("uom"),
		conversion_factor_unchanged=prev_con_fac == new_con_fac,
		date_unchanged=date_unchanged,
		description_unchanged=child_item.get("description") == new_data.get("description"),
	)


def is_child_item_unchanged(change_state: frappe._dict) -> bool:
	return (
		change_state.rate_unchanged
		and change_state.qty_unchanged
		and change_state.fg_qty_unchanged
		and change_state.conversion_factor_unchanged
		and change_state.uom_unchanged
		and change_state.date_unchanged
		and change_state.description_unchanged
	)


def update_child_item_rate_and_discount(
	parent_doctype: str, child_item, new_data, allow_zero_qty: bool, rate_unchanged: bool | None = None
) -> None:
	rate_precision = child_item.precision("rate") or 2
	qty_precision = child_item.precision("qty") or 2

	if rate_unchanged is None:
		prev_rate, new_rate = flt(child_item.get("rate")), flt(new_data.get("rate"))
		rate_unchanged = prev_rate == new_rate

	if not rate_unchanged and not child_item.get("qty") and allow_zero_qty:
		frappe.throw(_("Rate of '{}' items cannot be changed").format(frappe.bold(_("Unit Price"))))

	# Amount cannot be lesser than billed amount, except for negative amounts
	row_rate = flt(new_data.get("rate"), rate_precision)

	if parent_doctype in ["Purchase Order", "Sales Order"]:
		amount_below_billed_amt = flt(child_item.billed_amt, rate_precision) > flt(
			row_rate * flt(new_data.get("qty"), qty_precision), rate_precision
		)
		if amount_below_billed_amt and row_rate > 0.0:
			frappe.throw(
				_(
					"Row #{0}: Cannot set Rate if the billed amount is greater than the amount for Item {1}."
				).format(child_item.idx, child_item.item_code)
			)

	child_item.rate = row_rate

	if parent_doctype not in ["Sales Order", "Purchase Order"] or not flt(child_item.price_list_rate):
		return

	if flt(child_item.rate) > flt(child_item.price_list_rate):
		# if rate is greater than price_list_rate, set margin or set discount
		child_item.discount_percentage = 0
		child_item.margin_type = "Amount"
		child_item.margin_rate_or_amount = flt(
			child_item.rate - child_item.price_list_rate,
			child_item.precision("margin_rate_or_amount"),
		)
		child_item.rate_with_margin = child_item.rate
	else:
		child_item.discount_percentage = flt(
			(1 - flt(child_item.rate) / flt(child_item.price_list_rate)) * 100.0,
			child_item.precision("discount_percentage"),
		)
		child_item.discount_amount = flt(child_item.price_list_rate) - flt(child_item.rate)
		child_item.margin_type = ""
		child_item.margin_rate_or_amount = 0
		child_item.rate_with_margin = 0


def update_child_item_uom_and_weight(child_item, new_data) -> None:
	conv_fac_precision = child_item.precision("conversion_factor") or 2

	if new_data.get("conversion_factor"):
		if child_item.stock_uom == child_item.uom:
			child_item.conversion_factor = 1
		else:
			child_item.conversion_factor = flt(new_data.get("conversion_factor"), conv_fac_precision)

	if new_data.get("uom"):
		child_item.uom = new_data.get("uom")
		conversion_factor = flt(
			get_conversion_factor(child_item.item_code, child_item.uom).get("conversion_factor")
		)
		child_item.conversion_factor = (
			flt(new_data.get("conversion_factor"), conv_fac_precision) or conversion_factor
		)

	if child_item.get("weight_per_unit"):
		child_item.total_weight = flt(
			child_item.weight_per_unit * child_item.qty * child_item.conversion_factor,
			child_item.precision("total_weight"),
		)


@frappe.whitelist()
def update_child_qty_rate(
	parent_doctype: str, trans_items: str, parent_doctype_name: str, child_docname: str = "items"
):
	from erpnext.buying.doctype.supplier_quotation.supplier_quotation import get_purchased_items
	from erpnext.selling.doctype.quotation.quotation import get_ordered_items

	def check_doc_permissions(doc, perm_type="create"):
		try:
			doc.check_permission(perm_type)
		except frappe.PermissionError:
			actions = {"create": "add", "write": "update"}

			frappe.throw(
				_("You do not have permissions to {} items in a {}.").format(
					actions[perm_type], parent_doctype
				),
				title=_("Insufficient Permissions"),
			)

	def validate_workflow_conditions(doc):
		workflow = get_workflow_name(doc.doctype)
		if not workflow:
			return

		workflow_doc = frappe.get_doc("Workflow", workflow)
		current_state = doc.get(workflow_doc.workflow_state_field)
		roles = frappe.get_roles()

		transitions = []
		for transition in workflow_doc.transitions:
			if transition.next_state == current_state and transition.allowed in roles:
				if not is_transition_condition_satisfied(transition, doc):
					continue
				transitions.append(transition.as_dict())

		if not transitions:
			frappe.throw(
				_("You are not allowed to update as per the conditions set in {} Workflow.").format(
					get_link_to_form("Workflow", workflow)
				),
				title=_("Insufficient Permissions"),
			)

	def get_new_child_item(item_row):
		child_doctype = parent_doctype + " Item"
		return set_order_defaults(parent_doctype, parent_doctype_name, child_doctype, child_docname, item_row)

	def validate_quantity_and_rate(child_item, new_data):
		if not flt(new_data.get("qty")) and not allow_zero_qty:
			frappe.throw(
				_("Row #{0}:Quantity for Item {1} cannot be zero.").format(
					new_data.get("idx"), frappe.bold(new_data.get("item_code"))
				),
				title=_("Invalid Qty"),
			)

		qty_limits = {
			"Sales Order": ("delivered_qty", _("Cannot set quantity less than delivered quantity.")),
			"Purchase Order": ("received_qty", _("Cannot set quantity less than received quantity.")),
		}

		if parent_doctype in qty_limits:
			qty_field, error_message = qty_limits[parent_doctype]
			if flt(new_data.get("qty")) < flt(child_item.get(qty_field)):
				frappe.throw(
					_("Row #{0}:").format(new_data.get("idx"))
					+ error_message.format(frappe.bold(new_data.get("item_code"))),
					title=_("Invalid Qty"),
				)

		if parent_doctype in ["Quotation", "Supplier Quotation"]:
			if (parent_doctype == "Quotation" and not ordered_items) or (
				parent_doctype == "Supplier Quotation" and not purchased_items
			):
				return

			qty_to_check = (
				ordered_items.get(child_item.name)
				if parent_doctype == "Quotation"
				else purchased_items.get(child_item.name)
			)

			if qty_to_check:
				if not rate_unchanged:
					frappe.throw(
						_(
							"Cannot update rate as item {0} is already ordered or purchased against this quotation"
						).format(frappe.bold(new_data.get("item_code")))
					)

				if flt(new_data.get("qty")) < qty_to_check:
					frappe.throw(_("Cannot reduce quantity than ordered or purchased quantity"))

	def validate_fg_item_for_subcontracting(new_data, is_new):
		if is_new:
			if not new_data.get("fg_item"):
				frappe.throw(
					_("Finished Good Item is not specified for service item {0}").format(
						new_data["item_code"]
					)
				)
			else:
				is_sub_contracted_item, default_bom = frappe.db.get_value(
					"Item", new_data["fg_item"], ["is_sub_contracted_item", "default_bom"]
				)

				if not is_sub_contracted_item:
					frappe.throw(
						_("Finished Good Item {0} must be a sub-contracted item").format(new_data["fg_item"])
					)
				elif not default_bom:
					frappe.throw(_("Default BOM not found for FG Item {0}").format(new_data["fg_item"]))

		if not new_data.get("fg_item_qty"):
			frappe.throw(_("Finished Good Item {0} Qty can not be zero").format(new_data["fg_item"]))

	data = json.loads(trans_items)
	any_qty_changed = False  # updated to true if any item's qty changes
	items_added_or_removed = False  # updated to true if any new item is added or removed
	any_conversion_factor_changed = False

	parent = frappe.get_doc(parent_doctype, parent_doctype_name)
	allow_zero_qty = get_allow_zero_qty(parent_doctype)

	check_doc_permissions(parent, "write")

	if parent_doctype == "Quotation":
		ordered_items = get_ordered_items(parent.name)
		_removed_items = validate_and_delete_children(parent, data, ordered_items)
	elif parent_doctype == "Supplier Quotation":
		purchased_items = get_purchased_items(parent.name)
		_removed_items = validate_and_delete_children(parent, data, purchased_items)
	else:
		_removed_items = validate_and_delete_children(parent, data)

	items_added_or_removed |= _removed_items

	for d in data:
		new_child_flag = False
		rate_unchanged = None

		if not d.get("item_code"):
			# ignore empty rows
			continue

		if not d.get("docname"):
			new_child_flag = True
			items_added_or_removed = True
			check_doc_permissions(parent, "create")
			child_item = get_new_child_item(d)
		else:
			check_doc_permissions(parent, "write")
			child_item = frappe.get_doc(parent_doctype + " Item", d.get("docname"))

			change_state = get_child_item_change_state(parent_doctype, child_item, d)
			rate_unchanged = change_state.rate_unchanged
			any_conversion_factor_changed |= not change_state.conversion_factor_unchanged
			if is_child_item_unchanged(change_state):
				continue

		validate_quantity_and_rate(child_item, d)

		if flt(child_item.get("qty")) != flt(d.get("qty")):
			any_qty_changed = True

		if parent.doctype in ["Sales Order", "Purchase Order"] and parent.is_subcontracted:
			validate_fg_item_for_subcontracting(d, new_child_flag)
			child_item.fg_item_qty = flt(d["fg_item_qty"])

			if new_child_flag:
				child_item.fg_item = d["fg_item"]

		child_item.qty = flt(d.get("qty"))
		child_item.description = d.get("description")
		update_child_item_rate_and_discount(
			parent_doctype, child_item, d, allow_zero_qty, rate_unchanged=rate_unchanged
		)
		update_child_item_uom_and_weight(child_item, d)

		if d.get("delivery_date") and parent_doctype == "Sales Order":
			child_item.delivery_date = d.get("delivery_date")

		if d.get("schedule_date") and parent_doctype == "Purchase Order":
			child_item.schedule_date = d.get("schedule_date")

		if d.get("bom_no") and parent_doctype == "Sales Order":
			child_item.bom_no = d.get("bom_no")

		child_item.flags.ignore_validate_update_after_submit = True
		if new_child_flag:
			parent.load_from_db()
			child_item.idx = len(parent.items) + 1
			child_item.insert()
		else:
			child_item.save(ignore_permissions=True)

	parent.reload()
	parent.flags.ignore_validate_update_after_submit = True
	parent.set_qty_as_per_stock_uom()
	parent.calculate_taxes_and_totals()
	parent.set_total_in_words()
	if parent_doctype == "Sales Order" and not parent.is_subcontracted:
		make_packing_list(parent)
		parent.set_gross_profit()
	frappe.get_cached_doc("Authorization Control").validate_approving_authority(
		parent.doctype, parent.company, parent.base_grand_total
	)

	if parent_doctype != "Supplier Quotation":
		parent.set_payment_schedule()
	if parent_doctype == "Purchase Order":
		parent.validate_minimum_order_qty()
		parent.validate_budget()
		if parent.is_against_so():
			parent.update_status_updater()
	elif parent_doctype == "Sales Order":
		parent.check_credit_limit()

	# reset index of child table
	for idx, row in enumerate(parent.get(child_docname), start=1):
		row.idx = idx

	parent.save()

	if parent_doctype == "Purchase Order":
		update_last_purchase_rate(parent, is_submit=1)

		if any_qty_changed or items_added_or_removed or any_conversion_factor_changed:
			parent.update_prevdoc_status()

		parent.update_requested_qty()
		parent.update_ordered_qty()
		parent.update_ordered_and_reserved_qty()
		parent.update_receiving_percentage()

		if parent.is_subcontracted:
			if not parent.can_update_items():
				frappe.throw(
					_(
						"Items cannot be updated as Subcontracting Order is created against the Purchase Order {0}."
					).format(frappe.bold(parent.name))
				)
	elif parent_doctype == "Sales Order":  # Sales Order
		if parent.is_subcontracted and not parent.can_update_items():
			frappe.throw(
				_(
					"Items cannot be updated as Subcontracting Inward Order(s) exist against this Subcontracted Sales Order."
				)
			)
		parent.validate_selling_price()
		parent.validate_for_duplicate_items()
		parent.validate_warehouse()
		parent.update_reserved_qty()
		parent.update_project()
		parent.update_prevdoc_status("submit")
		parent.update_delivery_status()

	parent.reload()
	validate_workflow_conditions(parent)

	if parent_doctype in ["Purchase Order", "Sales Order"]:
		parent.update_blanket_order()
		parent.update_billing_percentage()
		parent.set_status()

	parent.validate_uom_is_integer("uom", "qty")
	parent.validate_uom_is_integer("stock_uom", "stock_qty")

	# Cancel and Recreate Stock Reservation Entries.
	if parent_doctype == "Sales Order" and not parent.is_subcontracted:
		from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
			cancel_stock_reservation_entries,
			has_reserved_stock,
		)

		if has_reserved_stock(parent.doctype, parent.name):
			cancel_stock_reservation_entries(parent.doctype, parent.name)

			if parent.per_picked == 0:
				parent.create_stock_reservation_entries()


def check_if_child_table_updated(child_table_before_update, child_table_after_update, fields_to_check):
	fields_to_check = list(fields_to_check) + get_accounting_dimensions() + ["cost_center", "project"]

	# Check if any field affecting accounting entry is altered
	for index, item in enumerate(child_table_before_update):
		for field in fields_to_check:
			if child_table_after_update[index].get(field) != item.get(field):
				return True

	return False


@erpnext.allow_regional
def validate_regional(doc):
	pass


@erpnext.allow_regional
def validate_einvoice_fields(doc):
	pass


from erpnext.accounts.services.base_gl_composer import (
	update_gl_dict_with_app_based_fields,
	update_gl_dict_with_regional_fields,
)


@frappe.whitelist()
def get_missing_company_details(doctype: str, docname: str):
	from frappe.contacts.doctype.address.address import get_address_display_list

	company = frappe.db.get_value(doctype, docname, "company")
	if doctype in ["Purchase Order", "Purchase Invoice"]:
		company_address = frappe.db.get_value(doctype, docname, "billing_address")
	elif doctype in ["Request for Quotation"]:
		company_address = frappe.db.get_value(doctype, docname, "shipping_address")
	else:
		company_address = frappe.db.get_value(doctype, docname, "company_address")

	company_details = frappe.get_value(
		"Company", company, ["company_logo", "website", "phone_no", "email"], as_dict=True
	)

	required_fields = [
		company_details.get("company_logo"),
		company_details.get("phone_no"),
		company_details.get("email"),
	]

	if not all(required_fields) and not frappe.has_permission("Company", "write", throw=False):
		frappe.msgprint(
			_(
				"Some required Company details are missing. You don't have permission to update them. Please contact your System Manager."
			)
		)
		return

	if not company_address and not frappe.has_permission(doctype, "write", throw=False):
		frappe.msgprint(
			_(
				"Company Address is missing. You don't have permission to update it. Please contact your System Manager."
			)
		)
		return

	address_display_list = get_address_display_list("Company", company)
	address_line = address_display_list[0].get("address_line1") if address_display_list else ""
	needs_new_company_address = not address_line

	if needs_new_company_address and not frappe.has_permission("Address", "create", throw=False):
		frappe.msgprint(
			_(
				"Company Address is missing. You don't have permission to create an Address. Please contact your System Manager."
			)
		)
		return

	required_fields.append(company_address)
	required_fields.append(address_line)

	if all(required_fields):
		return False
	return {
		"company_logo": company_details.get("company_logo"),
		"website": company_details.get("website"),
		"phone_no": company_details.get("phone_no"),
		"email": company_details.get("email"),
		"address_line": address_line,
		"company": company,
		"company_address": company_address,
		"name": docname,
	}


@frappe.whitelist()
def update_company_master_and_address(current_doctype: str, name: str, company: str, details: dict | str):
	from frappe.utils import validate_email_address

	if not frappe.has_permission(current_doctype, "write", doc=name, throw=False):
		frappe.throw(
			_("You don't have permission to update this document. Please contact your System Manager."),
			title=_("Insufficient Permissions"),
		)

	if not frappe.has_permission("Company", "write", doc=company, throw=False):
		frappe.throw(
			_("You don't have permission to update Company details. Please contact your System Manager."),
			title=_("Insufficient Permissions"),
		)

	if isinstance(details, str):
		details = frappe.parse_json(details)

	if details.get("email"):
		validate_email_address(details.get("email"), throw=True)

	company_fields = ["company_logo", "website", "phone_no", "email"]
	company_fields_to_update = {field: details.get(field) for field in company_fields if details.get(field)}

	if company_fields_to_update:
		frappe.db.set_value("Company", company, company_fields_to_update)

	company_address = details.get("company_address")
	if details.get("address_line1"):
		if not frappe.has_permission("Address", "create", throw=False):
			frappe.throw(
				_(
					"You don't have permission to create a Company Address. Please contact your System Manager."
				),
				title=_("Insufficient Permissions"),
			)
		address_doc = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": details.get("address_title"),
				"address_type": details.get("address_type"),
				"address_line1": details.get("address_line1"),
				"address_line2": details.get("address_line2"),
				"city": details.get("city"),
				"state": details.get("state"),
				"pincode": details.get("pincode"),
				"country": details.get("country"),
				"is_your_company_address": 1,
				"links": [{"link_doctype": "Company", "link_name": company}],
			}
		)
		address_doc.insert()
		company_address = address_doc.name

	update_doc_company_address(current_doctype, name, company_address, details)


def update_doc_company_address(current_doctype, docname, company_address, details):
	if not company_address:
		return

	address_field_map = {
		"Purchase Order": ("billing_address", "billing_address_display"),
		"Purchase Invoice": ("billing_address", "billing_address_display"),
		"Sales Order": ("company_address", "company_address_display"),
		"Sales Invoice": ("company_address", "company_address_display"),
		"Delivery Note": ("company_address", "company_address_display"),
		"POS Invoice": ("company_address", "company_address_display"),
		"Quotation": ("company_address", "company_address_display"),
		"Request for Quotation": ("shipping_address", "shipping_address_display"),
	}

	address_field, display_field = address_field_map.get(
		current_doctype, ("company_address", "company_address_display")
	)

	current_display = frappe.db.get_value(current_doctype, docname, display_field)

	if current_display and not details.get("address_line1"):
		return

	from frappe.query_builder import DocType

	DocType = DocType(current_doctype)

	(
		frappe.qb.update(DocType)
		.set(getattr(DocType, address_field), company_address)
		.set(getattr(DocType, display_field), get_address_display(company_address))
		.where(DocType.name == docname)
	).run()
