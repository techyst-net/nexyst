// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.setup");
erpnext.setup.EmployeeController = class EmployeeController extends frappe.ui.form.Controller {
	setup() {
		this.frm.fields_dict.user_id.get_query = function (doc, cdt, cdn) {
			return {
				query: "frappe.core.doctype.user.user.user_query",
				filters: { ignore_user_type: 1 },
			};
		};
		this.frm.fields_dict.reports_to.get_query = function (doc, cdt, cdn) {
			return {
				query: "erpnext.controllers.queries.employee_query",
				filters: [
					["status", "=", "Active"],
					["name", "!=", doc.name],
				],
			};
		};
	}

	refresh() {
		erpnext.toggle_naming_series();
	}
};

frappe.ui.form.on("Employee", {
	setup: function (frm) {
		frm.make_methods = {
			"Bank Account": () => erpnext.utils.make_bank_account(frm.doc.doctype, frm.doc.name),
		};
	},

	onload: function (frm) {
		frm.set_query("department", function () {
			return {
				filters: {
					company: frm.doc.company,
				},
			};
		});
	},

	refresh: function (frm) {
		frm.fields_dict.date_of_birth.datepicker.update({ maxDate: new Date() });

		frm.trigger("add_anniversary_indicator");
	},

	date_of_birth: function (frm) {
		frm.trigger("add_anniversary_indicator");
	},

	date_of_joining: function (frm) {
		frm.trigger("add_anniversary_indicator");
	},

	is_employee_birthday: function (frm) {
		if (!frm.doc.date_of_birth) return false;
		let today = moment().startOf("day");
		let dob = moment(frm.doc.date_of_birth);
		return dob.date() === today.date() && dob.month() === today.month();
	},

	is_work_anniversary: function (frm) {
		if (!frm.doc.date_of_joining) return false;
		let today = moment().startOf("day");
		let doj = moment(frm.doc.date_of_joining);
		let years = today.year() - doj.year();
		return doj.date() === today.date() && doj.month() === today.month() && years > 0;
	},

	get_work_anniversary_years: function (frm) {
		let today = moment().startOf("day");
		let doj = moment(frm.doc.date_of_joining);
		return today.year() - doj.year();
	},

	create_milestone_section: function ($sidebar) {
		let $indicator_section = $sidebar.find(".anniversary-indicator-section");
		if (!$indicator_section.length) {
			$indicator_section = $(`
				<div class="sidebar-section anniversary-indicator-section border-bottom pb-3">
					<div class="sidebar-label" style="font-weight: var(--weight-regular); color: var(--text-muted);">${__(
						"Milestones"
					)}</div>
					<div class="anniversary-content mt-3"></div>
				</div>
			`).insertAfter($sidebar.find(".sidebar-meta-details"));
		}
		return $indicator_section;
	},

	build_anniversary_content: function (frm) {
		let items = [];
		if (frm.events.is_employee_birthday(frm)) {
			items.push(`
				<div class="form-sidebar-items milestone-item mb-2">
					<span class="form-sidebar-label">
						${frappe.utils.icon("cake", "sm")}
						<span class="ellipsis">${__("Birthday")}</span>
					</span>
				</div>`);
		}
		if (frm.events.is_work_anniversary(frm)) {
			let years = frm.events.get_work_anniversary_years(frm);
			let label =
				years === 1
					? __("{0} Year Work Anniversary", [years])
					: __("{0} Years Work Anniversary", [years]);
			items.push(`
				<div class="form-sidebar-items milestone-item mb-2">
					<span class="form-sidebar-label">
						${frappe.utils.icon("briefcase", "sm")}
						<span class="ellipsis">${label}</span>
					</span>
				</div>`);
		}
		return items.join("");
	},

	add_anniversary_indicator: function (frm) {
		if (!frm.sidebar || !frm.sidebar.sidebar) return;

		let $sidebar = frm.sidebar.sidebar;
		let $indicator_section = frm.events.create_milestone_section($sidebar);
		let content = frm.events.build_anniversary_content(frm);

		if (content) {
			$indicator_section.find(".anniversary-content").html(content);
			$indicator_section.show();
		} else {
			$indicator_section.hide();
		}
	},

	prefered_contact_email: function (frm) {
		frm.events.update_contact(frm);
	},

	personal_email: function (frm) {
		frm.events.update_contact(frm);
	},

	company_email: function (frm) {
		frm.events.update_contact(frm);
	},

	user_id: function (frm) {
		frm.events.update_contact(frm);
	},

	update_contact: function (frm) {
		var prefered_email_fieldname = frappe.model.scrub(frm.doc.prefered_contact_email) || "user_id";
		frm.set_value("prefered_email", frm.fields_dict[prefered_email_fieldname].value);
	},

	status: function (frm) {
		return frm.call({
			method: "deactivate_sales_person",
			args: {
				employee: frm.doc.employee,
				status: frm.doc.status,
			},
		});
	},

	create_user: function (frm) {
		if (!frm.doc.prefered_email) {
			frappe.throw(__("Please enter Preferred Contact Email"));
		}
		frappe.call({
			method: "erpnext.setup.doctype.employee.employee.create_user",
			args: {
				employee: frm.doc.name,
				email: frm.doc.prefered_email,
			},
			freeze: true,
			freeze_message: __("Creating User..."),
			callback: function (r) {
				frm.reload_doc();
			},
		});
	},
});

cur_frm.cscript = new erpnext.setup.EmployeeController({
	frm: cur_frm,
});

frappe.tour["Employee"] = [
	{
		fieldname: "first_name",
		title: "First Name",
		description: __(
			"Enter First and Last name of Employee, based on Which Full Name will be updated. IN transactions, it will be Full Name which will be fetched."
		),
	},
	{
		fieldname: "company",
		title: "Company",
		description: __("Select a Company this Employee belongs to."),
	},
	{
		fieldname: "date_of_birth",
		title: "Date of Birth",
		description: __(
			"Select Date of Birth. This will validate Employees age and prevent hiring of under-age staff."
		),
	},
	{
		fieldname: "date_of_joining",
		title: "Date of Joining",
		description: __(
			"Select Date of joining. It will have impact on the first salary calculation, Leave allocation on pro-rata bases."
		),
	},
	{
		fieldname: "reports_to",
		title: "Reports To",
		description: __(
			"Here, you can select a senior of this Employee. Based on this, Organization Chart will be populated."
		),
	},
];
