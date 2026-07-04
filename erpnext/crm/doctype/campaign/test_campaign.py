# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.tests.utils import ERPNextTestSuite


class TestCampaign(ERPNextTestSuite):
	"""Campaign names itself from the campaign name (or a naming series) and mirrors
	itself into a UTM Campaign."""

	def setUp(self):
		frappe.set_user("Administrator")

	def make_campaign(self, **fields):
		doc = frappe.new_doc("Campaign")
		doc.campaign_name = fields.pop("campaign_name", f"_Test Campaign {frappe.generate_hash(length=6)}")
		doc.update(fields)
		return doc.insert()

	def test_autoname_uses_the_campaign_name_by_default(self):
		campaign = self.make_campaign(campaign_name="_Test Campaign Named")
		self.assertEqual(campaign.name, "_Test Campaign Named")

	def test_autoname_uses_naming_series_when_configured(self):
		# regression: with a naming series the document name differs from campaign_name,
		# and the UTM sync must still link back to a valid Campaign (self.name)
		original = frappe.defaults.get_global_default("campaign_naming_by")
		frappe.defaults.set_global_default("campaign_naming_by", "Naming Series")
		try:
			campaign = self.make_campaign(naming_series="SAL-CAM-.YYYY.-")
			self.assertTrue(campaign.name.startswith("SAL-CAM-"))
			utm = frappe.get_doc("UTM Campaign", campaign.campaign_name)
			self.assertEqual(utm.crm_campaign, campaign.name)
		finally:
			frappe.defaults.set_global_default("campaign_naming_by", original or "")

	def test_inserting_mirrors_into_a_utm_campaign(self):
		campaign = self.make_campaign(campaign_name="_Test Campaign UTM", description="Spring push")
		self.assertTrue(frappe.db.exists("UTM Campaign", campaign.campaign_name))
		utm = frappe.get_doc("UTM Campaign", campaign.campaign_name)
		self.assertEqual(utm.campaign_description, "Spring push")
		self.assertEqual(utm.crm_campaign, campaign.name)

	def test_editing_campaign_name_reuses_the_same_utm_campaign(self):
		campaign = self.make_campaign(campaign_name="_Test Campaign Rename A")
		campaign.campaign_name = "_Test Campaign Rename B"
		campaign.save()
		# the edit updates the existing mirror rather than creating a second one
		mirrors = frappe.get_all("UTM Campaign", filters={"crm_campaign": campaign.name})
		self.assertEqual(len(mirrors), 1)
