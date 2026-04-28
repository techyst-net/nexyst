# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.query_builder.functions import Sum

from erpnext import get_region

# Per-execution memoization cache for the helper functions below.
# Cleared at the start of every execute() call so each report run gets
# fresh data; within a single run, repeated calls reuse the result.
_cache = {}


def _cached(fn):
	def wrapper(filters, *args, **kwargs):
		key = (fn.__name__, tuple(sorted((filters or {}).items())))
		if key not in _cache:
			_cache[key] = fn(filters, *args, **kwargs)
		return _cache[key]

	return wrapper


def execute(filters=None):
	validate_company_region(filters)
	_cache.clear()
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def validate_company_region(filters):
	if filters.get("company") and get_region(filters.get("company")) != "United Arab Emirates":
		frappe.throw(
			_(
				"The company {0} is not in United Arab Emirates. UAE VAT 201 report is only available for companies in United Arab Emirates."
			).format(frappe.bold(filters.get("company")))
		)


def get_columns():
	"""Creates a list of dictionaries that are used to generate column headers of the data table."""
	return [
		{"fieldname": "no", "label": _("No"), "fieldtype": "Data", "width": 50},
		{"fieldname": "legend", "label": _("Legend"), "fieldtype": "Data", "width": 300},
		{
			"fieldname": "amount",
			"label": _("Amount (AED)"),
			"fieldtype": "Currency",
			"width": 125,
		},
		{
			"fieldname": "vat_amount",
			"label": _("VAT Amount (AED)"),
			"fieldtype": "Currency",
			"width": 150,
		},
	]


def get_data(filters=None):
	"""Returns the list of dictionaries. Each dictionary is a row in the datatable and chart data."""
	data = []
	amounts_by_emirate = append_vat_on_sales(data, filters)
	append_vat_on_expenses(data, filters)
	net_vat_due(data, filters, amounts_by_emirate)

	final_data = []
	for i in range(0, len(data)):
		if data[i].get("legend") == "Standard rated supplies in Abu Dhabi":
			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Sales%20Invoice&vat=Abu%20Dhabi&category=Standard">{data[i].get("legend")}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)
		elif data[i].get("legend") == "Standard rated supplies in Dubai":
			company = frappe.defaults.get_user_default("Company")
			company_filters = [
				["Dynamic Link", "link_doctype", "=", "Company"],
				["Dynamic Link", "link_name", "=", company],
				["Address", "is_your_company_address", "=", 1],
			]
			company_fields = [
				"name",
				"address_line1",
				"address_line2",
				"city",
				"state",
				"country",
				"emirate",
			]
			address = frappe.get_all("Address", filters=company_filters, fields=company_fields)

			if address:
				if address[0].get("emirate"):
					name = "Standard rated supplies in" + " " + address[0].get("emirate")
				else:
					name = "Standard rated supplies in Dubai"
			else:
				name = "Standard rated supplies in Dubai"

			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Sales%20Invoice&vat=Dubai&category=Standard">{name}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)

		elif data[i].get("legend") == "Standard rated supplies in Sharjah":
			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Sales%20Invoice&vat=Sharjah&category=Standard">{data[i].get("legend")}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)
		elif data[i].get("legend") == "Standard rated supplies in Ajman":
			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Sales%20Invoice&vat=Ajman&category=Standard">{data[i].get("legend")}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)
		elif data[i].get("legend") == "Standard rated supplies in Umm Al Quwain":
			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Sales%20Invoice&vat=Umm%20Al%20Quwain&category=Standard">{data[i].get("legend")}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)
		elif data[i].get("legend") == "Standard rated supplies in Ras Al Khaimah":
			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Sales%20Invoice&vat=Ras%20Al%20Khaimah&category=Standard">{data[i].get("legend")}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)
		elif data[i].get("legend") == "Standard rated supplies in Fujairah":
			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Sales%20Invoice&vat=Fujairah&category=Standard">{data[i].get("legend")}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)
		elif data[i].get("legend") == "Supplies subject to the reverse charge provision":
			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Purchase%20Invoice&reverse_charge=Y">{data[i].get("legend")}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)
		elif data[i].get("legend") == "Zero Rated":
			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Sales%20Invoice&category=Zero%20Rated">{data[i].get("legend")}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)
		elif data[i].get("legend") == "Exempt Supplies":
			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Sales%20Invoice&category=Exempt%20Rated">{data[i].get("legend")}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)
		elif data[i].get("legend") == "Standard Rated Expenses":
			legend_link = f"""
			<a href= "/app/query-report/UAE%20VAT%20Register?company={filters.get("company")}&from_date={filters.get("from_date")}&to_date={filters.get("to_date")}&doc_type=Purchase%20Invoice">{data[i].get("legend")}</a>
			"""
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": legend_link,
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)
		else:
			final_data.append(
				{
					"no": data[i].get("no"),
					"legend": data[i].get("legend"),
					"amount": data[i].get("amount"),
					"vat_amount": data[i].get("vat_amount"),
				}
			)

	return final_data


def append_vat_on_sales(data, filters):
	"""Appends Sales and All Other Outputs."""
	append_data(data, "", _("VAT on Sales and All Other Outputs"), "", "")

	amounts_by_emirate = standard_rated_expenses_emiratewise(data, filters)

	si_amount = amounts_by_emirate[1]
	si_vat = amounts_by_emirate[2]

	append_data(
		data,
		"2",
		_("Tax Refunds provided to Tourists under the Tax Refunds for Tourists Scheme"),
		format_currency_signed((-1) * get_tourist_tax_return_total(filters)),
		format_currency_signed((-1) * get_tourist_tax_return_tax(filters)),
	)

	append_data(
		data,
		"3",
		_("Supplies subject to the reverse charge provision"),
		frappe.format(get_reverse_charge_total(filters), "Currency"),
		frappe.format(get_reverse_charge_tax(filters), "Currency"),
	)

	append_data(data, "4", _("Zero Rated"), frappe.format(get_zero_rated_total(filters), "Currency"), "-")

	append_data(data, "5", _("Exempt Supplies"), frappe.format(get_exempt_total(filters), "Currency"), "-")

	append_data(
		data,
		"8",
		_("Total"),
		frappe.format(
			(-1) * get_tourist_tax_return_total(filters)
			+ get_reverse_charge_total(filters)
			+ get_zero_rated_total(filters)
			+ get_exempt_total(filters)
			+ sum(si_amount),
			"Currency",
		),
		frappe.format(
			(-1) * get_tourist_tax_return_tax(filters) + get_reverse_charge_tax(filters) + sum(si_vat),
			"Currency",
		),
	)

	append_data(data, "", "", "", "")

	return amounts_by_emirate


def standard_rated_expenses_emiratewise(data, filters):
	"""Append emiratewise standard rated expenses and vat."""
	total_emiratewise = get_total_emiratewise(filters)
	emirates = get_emirates()
	amounts_by_emirate = {}
	for emirate, amount, vat in total_emiratewise:
		amounts_by_emirate[emirate] = {
			"legend": emirate,
			"raw_amount": amount,
			"raw_vat_amount": vat,
			"amount": frappe.format(amount, "Currency"),
			"vat_amount": frappe.format(vat, "Currency"),
		}
	amounts_by_emirate = append_emiratewise_expenses(data, emirates, amounts_by_emirate)
	return amounts_by_emirate


def append_emiratewise_expenses(data, emirates, amounts_by_emirate):
	"""Append emiratewise standard rated expenses and vat."""
	s_amount = []
	v_amount = []
	for no, emirate in enumerate(emirates, 97):
		if emirate in amounts_by_emirate:
			amounts_by_emirate[emirate]["no"] = _("1{0}").format(chr(no))
			amounts_by_emirate[emirate]["legend"] = _("Standard rated supplies in {0}").format(emirate)
			data.append(amounts_by_emirate[emirate])

			s_amount.append(amounts_by_emirate[emirate].get("raw_amount") or 0)
			v_amount.append(amounts_by_emirate[emirate].get("raw_vat_amount") or 0)
		else:
			append_data(
				data,
				_("1{0}").format(chr(no)),
				_("Standard rated supplies in {0}").format(emirate),
				frappe.format(0, "Currency"),
				frappe.format(0, "Currency"),
			)
	return amounts_by_emirate, s_amount, v_amount


def append_vat_on_expenses(data, filters):
	"""Appends Expenses and All Other Inputs."""
	append_data(data, "", _("VAT on Expenses and All Other Inputs"), "", "")
	append_data(
		data,
		"9",
		_("Standard Rated Expenses"),
		frappe.format(get_standard_rated_expenses_total(filters), "Currency"),
		frappe.format(get_standard_rated_expenses_tax(filters), "Currency"),
	)
	append_data(
		data,
		"10",
		_("Supplies subject to the reverse charge provision"),
		frappe.format(get_reverse_charge_recoverable_total(filters), "Currency"),
		frappe.format(get_reverse_charge_recoverable_tax(filters), "Currency"),
	)

	append_data(
		data,
		"11",
		_("Total"),
		frappe.format(
			get_standard_rated_expenses_total(filters) + get_reverse_charge_recoverable_total(filters),
			"Currency",
		),
		frappe.format(
			get_standard_rated_expenses_tax(filters) + get_reverse_charge_recoverable_tax(filters),
			"Currency",
		),
	)


def net_vat_due(data, filters, amounts_by_emirate):
	si_vat = amounts_by_emirate[2]

	append_data(data, "", "", "", "")
	append_data(data, "", _("Net VAT Due"), "", "")
	append_data(
		data,
		"12",
		_("Total value of due tax for the period"),
		frappe.format(0.00, "Currency"),
		frappe.format(
			sum(si_vat) + (-1) * get_tourist_tax_return_tax(filters) + get_reverse_charge_tax(filters),
			"Currency",
		),
	)
	append_data(
		data,
		"13",
		_("Total value of recoverable tax for the period "),
		frappe.format(0.00, "Currency"),
		frappe.format(
			get_standard_rated_expenses_tax(filters) + get_reverse_charge_recoverable_tax(filters),
			"Currency",
		),
	)

	# Calculate payable tax: Due Tax - Recoverable Tax
	due_tax = sum(si_vat) + (-1) * get_tourist_tax_return_tax(filters) + get_reverse_charge_tax(filters)
	recoverable_tax = get_standard_rated_expenses_tax(filters) + get_reverse_charge_recoverable_tax(filters)
	payable_tax = due_tax - recoverable_tax

	append_data(
		data,
		"14",
		_("Payable tax for the period"),
		frappe.format(0.00, "Currency"),
		frappe.format(payable_tax, "Currency"),
	)


def append_data(data, no, legend, amount, vat_amount):
	"""Returns data with appended value."""
	data.append({"no": no, "legend": legend, "amount": amount, "vat_amount": vat_amount})


def format_currency_signed(value):
	"""Format a number as currency, placing the minus sign *before* the currency symbol
	when negative (e.g. "-د.إ 5,000.00" rather than "د.إ -5,000.00")."""
	if value is None:
		value = 0
	if value < 0:
		return "-" + frappe.format(abs(value), "Currency")
	return frappe.format(value, "Currency")


@_cached
def get_total_emiratewise(filters):
	"""Returns Emiratewise Amount and Taxes."""
	i = frappe.qb.DocType("Sales Invoice Item")
	s = frappe.qb.DocType("Sales Invoice")
	query = (
		frappe.qb.from_(i)
		.inner_join(s)
		.on(i.parent == s.name)
		.select(s.vat_emirate.as_("emirate"), Sum(i.base_net_amount).as_("total"), Sum(i.tax_amount))
		.where((s.docstatus == 1) & (i.is_exempt != 1) & (i.is_zero_rated != 1))
		.groupby(s.vat_emirate)
	)
	for condition in get_conditions(filters, s):
		query = query.where(condition)
	try:
		return query.run()
	except (IndexError, TypeError):
		return 0


def get_emirates():
	"""Returns a List of emirates in the order that they are to be displayed."""
	return ["Abu Dhabi", "Dubai", "Sharjah", "Ajman", "Umm Al Quwain", "Ras Al Khaimah", "Fujairah"]


def get_filters(filters):
	"""The conditions to be used to filter data to calculate the total sale."""
	query_filters = []
	if filters.get("company"):
		query_filters.append(["company", "=", filters["company"]])
	if filters.get("from_date"):
		query_filters.append(["posting_date", ">=", filters["from_date"]])
	if filters.get("to_date"):
		query_filters.append(["posting_date", "<=", filters["to_date"]])
	return query_filters


@_cached
def get_reverse_charge_total(filters):
	"""Returns the sum of the total of each Purchase invoice made."""
	query_filters = get_filters(filters)
	query_filters.append(["reverse_charge", "=", "Y"])
	query_filters.append(["docstatus", "=", 1])
	try:
		return (
			frappe.db.get_all(
				"Purchase Invoice",
				filters=query_filters,
				fields=["sum(base_net_total)"],
				as_list=True,
				limit=1,
			)[0][0]
			or 0
		)
	except (IndexError, TypeError):
		return 0


@_cached
def get_reverse_charge_tax(filters):
	"""Returns the sum of the tax of each Purchase invoice made."""
	p = frappe.qb.DocType("Purchase Invoice")
	gl = frappe.qb.DocType("GL Entry")
	uae_vat = frappe.qb.DocType("UAE VAT Account")
	query = (
		frappe.qb.from_(p)
		.inner_join(gl)
		.on(gl.voucher_no == p.name)
		.select(Sum(gl.debit))
		.where(
			(p.reverse_charge == "Y")
			& (p.docstatus == 1)
			& (gl.docstatus == 1)
			& gl.account.isin(
				frappe.qb.from_(uae_vat)
				.select(uae_vat.account)
				.where(uae_vat.parent == filters.get("company"))
			)
		)
	)
	for condition in get_conditions_join(filters, p):
		query = query.where(condition)
	return query.run()[0][0] or 0


@_cached
def get_reverse_charge_recoverable_total(filters):
	"""Returns the sum of the total of each Purchase invoice made with recoverable reverse charge."""
	query_filters = get_filters(filters)
	query_filters.append(["reverse_charge", "=", "Y"])
	query_filters.append(["recoverable_reverse_charge", ">", "0"])
	query_filters.append(["docstatus", "=", 1])
	try:
		return (
			frappe.db.get_all(
				"Purchase Invoice",
				filters=query_filters,
				fields=["sum(base_net_total)"],
				as_list=True,
				limit=1,
			)[0][0]
			or 0
		)
	except (IndexError, TypeError):
		return 0


@_cached
def get_reverse_charge_recoverable_tax(filters):
	"""Returns the sum of the tax of each Purchase invoice made."""
	p = frappe.qb.DocType("Purchase Invoice")
	gl = frappe.qb.DocType("GL Entry")
	uae_vat = frappe.qb.DocType("UAE VAT Account")
	query = (
		frappe.qb.from_(p)
		.inner_join(gl)
		.on(gl.voucher_no == p.name)
		.select(Sum(gl.debit * p.recoverable_reverse_charge / 100))
		.where(
			(p.reverse_charge == "Y")
			& (p.docstatus == 1)
			& (p.recoverable_reverse_charge > 0)
			& (gl.docstatus == 1)
			& gl.account.isin(
				frappe.qb.from_(uae_vat)
				.select(uae_vat.account)
				.where(uae_vat.parent == filters.get("company"))
			)
		)
	)
	for condition in get_conditions_join(filters, p):
		query = query.where(condition)
	return query.run()[0][0] or 0


def get_conditions_join(filters, p):
	"""The conditions to be used to filter data to calculate the total vat."""
	conditions = []
	if filters.get("company"):
		conditions.append(p.company == filters.get("company"))
	if filters.get("from_date"):
		conditions.append(p.posting_date >= filters.get("from_date"))
	if filters.get("to_date"):
		conditions.append(p.posting_date <= filters.get("to_date"))
	return conditions


@_cached
def get_standard_rated_expenses_total(filters):
	"""Returns the sum of the total of each Purchase invoice made with recoverable reverse charge."""
	query_filters = get_filters(filters)
	query_filters.append(["recoverable_standard_rated_expenses", ">", 0])
	query_filters.append(["docstatus", "=", 1])
	try:
		return (
			frappe.db.get_all(
				"Purchase Invoice",
				filters=query_filters,
				fields=["sum(base_net_total)"],
				as_list=True,
				limit=1,
			)[0][0]
			or 0
		)
	except (IndexError, TypeError):
		return 0


@_cached
def get_standard_rated_expenses_tax(filters):
	"""Returns the sum of the tax of each Purchase invoice made."""
	query_filters = get_filters(filters)
	query_filters.append(["recoverable_standard_rated_expenses", ">", 0])
	query_filters.append(["docstatus", "=", 1])
	try:
		return (
			frappe.db.get_all(
				"Purchase Invoice",
				filters=query_filters,
				fields=["sum(recoverable_standard_rated_expenses)"],
				as_list=True,
				limit=1,
			)[0][0]
			or 0
		)
	except (IndexError, TypeError):
		return 0


@_cached
def get_tourist_tax_return_total(filters):
	"""Returns the sum of the total of each Sales invoice with non zero tourist_tax_return."""
	query_filters = get_filters(filters)
	query_filters.append(["tourist_tax_return", ">", 0])
	query_filters.append(["docstatus", "=", 1])
	try:
		return (
			frappe.db.get_all(
				"Sales Invoice", filters=query_filters, fields=["sum(base_net_total)"], as_list=True, limit=1
			)[0][0]
			or 0
		)
	except (IndexError, TypeError):
		return 0


@_cached
def get_tourist_tax_return_tax(filters):
	"""Returns the sum of the tax of each Sales invoice with non zero tourist_tax_return."""
	query_filters = get_filters(filters)
	query_filters.append(["tourist_tax_return", ">", 0])
	query_filters.append(["docstatus", "=", 1])
	try:
		return (
			frappe.db.get_all(
				"Sales Invoice",
				filters=query_filters,
				fields=["sum(tourist_tax_return)"],
				as_list=True,
				limit=1,
			)[0][0]
			or 0
		)
	except (IndexError, TypeError):
		return 0


@_cached
def get_zero_rated_total(filters):
	"""Returns the sum of each Sales Invoice Item Amount which is zero rated."""
	i = frappe.qb.DocType("Sales Invoice Item")
	s = frappe.qb.DocType("Sales Invoice")
	query = (
		frappe.qb.from_(i)
		.inner_join(s)
		.on(i.parent == s.name)
		.select(Sum(i.base_net_amount).as_("total"))
		.where((s.docstatus == 1) & (i.is_zero_rated == 1))
	)
	for condition in get_conditions(filters, s):
		query = query.where(condition)
	try:
		return query.run()[0][0] or 0
	except (IndexError, TypeError):
		return 0


@_cached
def get_exempt_total(filters):
	"""Returns the sum of each Sales Invoice Item Amount which is Vat Exempt."""
	i = frappe.qb.DocType("Sales Invoice Item")
	s = frappe.qb.DocType("Sales Invoice")
	query = (
		frappe.qb.from_(i)
		.inner_join(s)
		.on(i.parent == s.name)
		.select(Sum(i.base_net_amount).as_("total"))
		.where((s.docstatus == 1) & (i.is_exempt == 1))
	)
	for condition in get_conditions(filters, s):
		query = query.where(condition)
	try:
		return query.run()[0][0] or 0
	except (IndexError, TypeError):
		return 0


def get_conditions(filters, s):
	"""The conditions to be used to filter data to calculate the total sale."""
	conditions = []
	if filters.get("company"):
		conditions.append(s.company == filters.get("company"))
	if filters.get("from_date"):
		conditions.append(s.posting_date >= filters.get("from_date"))
	if filters.get("to_date"):
		conditions.append(s.posting_date <= filters.get("to_date"))
	return conditions
