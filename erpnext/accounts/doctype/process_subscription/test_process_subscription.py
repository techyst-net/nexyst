# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe

from erpnext.accounts.doctype.process_subscription.process_subscription import (
	create_subscription_process,
)
from erpnext.accounts.doctype.subscription.test_subscription import create_plan, create_subscription
from erpnext.tests.utils import ERPNextTestSuite


class TestProcessSubscription(ERPNextTestSuite):
	"""Process Subscription is a batch driver: on submit it enqueues subscription.process_all
	for every non-cancelled Subscription (or just one when a subscription is named)."""

	def setUp(self):
		frappe.set_user("Administrator")
		create_plan(plan_name="_Test Plan Name", currency="INR")

	def enqueued_subscriptions(self, subscription=None):
		"""Submit a Process Subscription while capturing what gets enqueued."""
		calls = []

		def capture(*args, **kwargs):
			calls.append(kwargs)

		with patch("frappe.enqueue", side_effect=capture):
			create_subscription_process(subscription=subscription, posting_date="2026-06-15")

		# each enqueue is handed a batch (list) of subscription names
		return [name for call in calls for name in call.get("subscription", [])]

	def test_named_subscription_is_the_only_one_enqueued(self):
		sub = create_subscription(start_date="2026-01-01")
		self.assertEqual(self.enqueued_subscriptions(subscription=sub.name), [sub.name])

	def test_cancelled_subscriptions_are_skipped(self):
		active = create_subscription(start_date="2026-01-01")
		cancelled = create_subscription(start_date="2026-01-01")
		cancelled.cancel_subscription()

		enqueued = self.enqueued_subscriptions()
		self.assertIn(active.name, enqueued)
		self.assertNotIn(cancelled.name, enqueued)
