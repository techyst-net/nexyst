# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.model.naming import set_name_by_naming_series


class Campaign(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.crm.doctype.campaign_email_schedule.campaign_email_schedule import (
			CampaignEmailSchedule,
		)

		campaign_name: DF.Data
		campaign_schedules: DF.Table[CampaignEmailSchedule]
		description: DF.Text | None
		naming_series: DF.Literal["SAL-CAM-.YYYY.-"]
	# end: auto-generated types

	def after_insert(self):
		self.sync_utm_campaign()

	def on_change(self):
		self.sync_utm_campaign()

	def sync_utm_campaign(self):
		# look up the existing mirror by the stable Campaign link first, so editing
		# campaign_name updates that mirror instead of creating a duplicate
		existing = frappe.db.get_value("UTM Campaign", {"crm_campaign": self.name}) or self.campaign_name
		try:
			mc = frappe.get_doc("UTM Campaign", existing)
		except frappe.DoesNotExistError:
			mc = frappe.new_doc("UTM Campaign")
			mc.name = self.campaign_name
		mc.campaign_description = self.description
		# link by the document name, which differs from campaign_name when a naming series is used
		mc.crm_campaign = self.name
		mc.save(ignore_permissions=True)

	def autoname(self):
		if frappe.defaults.get_global_default("campaign_naming_by") != "Naming Series":
			self.name = self.campaign_name
		else:
			set_name_by_naming_series(self)
