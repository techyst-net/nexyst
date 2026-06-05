# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Shared exceptions for stock transactions.

Raised by the stock services (serial/batch bundle, quality inspection) and
re-exported from ``stock_controller`` for backward compatibility, so the services
do not have to import back from the controller they were extracted out of.
"""

import frappe


class QualityInspectionRequiredError(frappe.ValidationError):
	pass


class QualityInspectionRejectedError(frappe.ValidationError):
	pass


class QualityInspectionNotSubmittedError(frappe.ValidationError):
	pass


class BatchExpiredError(frappe.ValidationError):
	pass
