# Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
# For license information, please see license.txt

"""Contractor Warning: a written warning issued on a Contractor Non-Conformance.

Like a Contract of Employment, it is submitted only once the signed
acknowledgement (or proof of delivery) is attached. Submitting records it on
the case, adds its required corrective action there, and puts it in force
until Valid Until; the daily monitor marks it Expired after that.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, getdate, today


class ContractorWarning(Document):
	def validate(self):
		case = frappe.db.get_value(
			"Contractor Non-Conformance", self.non_conformance, ["docstatus", "contractor_sla"], as_dict=True
		)
		if not case or case.docstatus != 0:
			frappe.throw(_("Warnings can only be issued on an open non-conformance."))
		level = frappe.get_cached_doc("Contractor Warning Level", self.warning_level)
		self.valid_until = add_days(self.issue_date, cint(level.validity_days))
		if self.remediation_due_date and getdate(self.remediation_due_date) < getdate(self.issue_date):
			frappe.throw(_("Remediate By cannot be before the Issue Date."))
		self.consequence = consequence_text(level)
		self.status = compute_status(self)

	def before_submit(self):
		if not self.signed_acknowledgement:
			frappe.throw(
				_("Attach the warning signed by the contractor, or proof of its delivery, before submitting."),
				title=_("Not Acknowledged Yet"),
			)
		self.acknowledged_on = self.acknowledged_on or today()
		self.status = compute_status(self)

	def on_submit(self):
		case = frappe.get_doc("Contractor Non-Conformance", self.non_conformance)
		case.warning = self.name
		case.outcome = "Warning Issued"
		open_actions = [row for row in case.corrective_actions if not row.completed_on]
		if open_actions:
			# The warning sets the deadline for what is still outstanding.
			for row in open_actions:
				if getdate(row.due_date) < getdate(self.remediation_due_date):
					row.due_date = self.remediation_due_date
			case.overdue_notified_on = None
		elif (self.corrective_action_required or "").strip():
			case.append(
				"corrective_actions",
				{"action": self.corrective_action_required.strip(), "due_date": self.remediation_due_date},
			)
		case.flags.ignore_permissions = True
		case.save()
		case.add_comment("Info", _("Warning {0} ({1}) issued, valid until {2}.").format(
			self.name, self.warning_level, frappe.format(self.valid_until, "Date")
		))

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		case = frappe.get_doc("Contractor Non-Conformance", self.non_conformance)
		if case.docstatus == 0 and case.warning == self.name:
			previous = frappe.get_all(
				"Contractor Warning",
				filters={"non_conformance": case.name, "docstatus": 1, "name": ["!=", self.name]},
				order_by="issue_date desc",
				pluck="name",
				limit=1,
			)
			case.warning = previous[0] if previous else None
			case.outcome = "Warning Issued" if previous else None
			case.flags.ignore_permissions = True
			case.save()


def compute_status(doc, on_date=None):
	if doc.docstatus == 0:
		return "Draft"
	if doc.docstatus == 2:
		return "Cancelled"
	return "Expired" if getdate(doc.valid_until) < getdate(on_date or today()) else "Active"


def consequence_text(level) -> str:
	if level.is_final:
		return _(
			"This is a final warning. Any further non-conformance while it is in force may lead to termination "
			"of the Agreement."
		)
	following = frappe.get_all(
		"Contractor Warning Level",
		filters={"disabled": 0, "severity": [">", level.severity]},
		order_by="severity asc",
		pluck="name",
		limit=1,
	)
	if following:
		return _(
			"Any further non-conformance while this warning is in force may lead to a {0}, and ultimately to "
			"termination of the Agreement."
		).format(following[0])
	return _("Any further non-conformance while this warning is in force may lead to termination of the Agreement.")


def expire_warnings(settings, on_date):
	for name in frappe.get_all(
		"Contractor Warning",
		filters={"docstatus": 1, "status": "Active", "valid_until": ["<", on_date]},
		pluck="name",
	):
		frappe.db.set_value("Contractor Warning", name, "status", "Expired", update_modified=False)
