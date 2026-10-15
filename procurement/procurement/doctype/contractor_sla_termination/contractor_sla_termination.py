# Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
# For license information, please see license.txt

"""Contractor SLA Termination: ends a signed Contractor SLA.

Submitted only with the signed notice (or signed mutual termination)
attached. Submitting marks the SLA Terminated, which takes it out of every
expiry and unsigned notice, and closes the non-conformance it escalates.
Cancelling it restores the SLA.

The grounds follow the termination clause of the standard SLA; the two
objective notice rules are checked: a termination for the Company's
convenience needs 48 hours' notice, and one for an unremedied material breach
should follow a documented warning with 10 days to remedy.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, getdate, today

from procurement.procurement.doctype.contractor_sla.contractor_sla import CLOSED_STATUSES, compute_status

COMPANY_GROUNDS = (
	"Material Breach Not Remedied",
	"Regulatory or Tax Non-Compliance",
	"Unauthorised Cession or Assignment",
	"Contractor Insolvency",
	"Operation Suspended",
	"Contractor Abandoned or Suspended Work",
	"Failure to Secure Insurance",
	"Contractor Warranties Invalid",
	"Financial Causes",
	"Convenience of the Company",
)
CONTRACTOR_GROUNDS = (
	"Company Material Breach Not Remedied",
	"Company Default on Site Access",
	"Operation Suspended by the Company",
	"Company Insolvency",
	"Company Cancelled or Suspended Operations",
)
COMMON_GROUNDS = ("Force Majeure Exceeding 21 Days", "Other")
GROUNDS = {
	"Company": COMPANY_GROUNDS + COMMON_GROUNDS,
	"Contractor": CONTRACTOR_GROUNDS + COMMON_GROUNDS,
	"Mutual": ("Mutual Agreement", *COMMON_GROUNDS),
}
BREACH_CURE_DAYS = 10
CONVENIENCE_NOTICE_DAYS = 2  # 48 hours


class ContractorSLATermination(Document):
	def validate(self):
		sla = frappe.db.get_value(
			"Contractor SLA", self.contractor_sla, ["docstatus", "status", "sla_termination"], as_dict=True
		)
		if not sla or sla.docstatus != 1 or (sla.status in CLOSED_STATUSES and sla.sla_termination != self.name):
			frappe.throw(_("Only a signed SLA that is not already terminated can be terminated."))
		if self.termination_ground not in GROUNDS[self.initiated_by]:
			frappe.throw(
				_("{0} is not a ground the {1} can terminate on.").format(
					frappe.bold(self.termination_ground), _(self.initiated_by).lower()
				)
			)
		if getdate(self.effective_date) < getdate(self.notice_date):
			frappe.throw(_("The Effective Termination Date cannot be before the Notice Date."))
		self.notice_days = date_diff(self.effective_date, self.notice_date)
		if self.termination_ground == "Convenience of the Company" and self.notice_days < CONVENIENCE_NOTICE_DAYS:
			frappe.throw(_("Termination for the Company's convenience needs at least 48 hours' notice."))
		if self.non_conformance:
			case_sla = frappe.db.get_value("Contractor Non-Conformance", self.non_conformance, "contractor_sla")
			if case_sla != self.contractor_sla:
				frappe.throw(_("Non-Conformance {0} belongs to a different SLA.").format(self.non_conformance))
		self.warn_on_breach_notice()

	def warn_on_breach_notice(self):
		"""Material breach: the contractor should have had written notice and 10 days to remedy."""
		if self.termination_ground != "Material Breach Not Remedied":
			return
		latest = frappe.get_all(
			"Contractor Warning",
			filters={"contractor_sla": self.contractor_sla, "docstatus": 1, "issue_date": ["<=", self.notice_date]},
			fields=["name", "issue_date"],
			order_by="issue_date desc",
			limit=1,
		)
		if not latest:
			message = _(
				"No warning has been issued on this SLA. A material-breach termination should follow written "
				"notice of the breach and {0} days to remedy it."
			).format(BREACH_CURE_DAYS)
		elif date_diff(self.notice_date, latest[0].issue_date) < BREACH_CURE_DAYS:
			message = _(
				"The latest warning ({0}) was issued {1} days before this notice; the contractor should have "
				"{2} days to remedy a breach."
			).format(latest[0].name, date_diff(self.notice_date, latest[0].issue_date), BREACH_CURE_DAYS)
		else:
			return
		frappe.msgprint(message, title=_("Check the Notice Period"), indicator="orange")

	def before_submit(self):
		if not self.signed_notice:
			frappe.throw(
				_("Attach the signed termination notice (or signed mutual termination) before submitting."),
				title=_("Not Signed Yet"),
			)

	def on_submit(self):
		sla = frappe.get_doc("Contractor SLA", self.contractor_sla)
		sla.terminated_on = self.effective_date
		sla.termination_reason = f"{self.termination_ground}: {self.reason}"
		sla.sla_termination = self.name
		sla.status = compute_status(sla)
		sla.flags.ignore_permissions = True
		sla.save()
		sla.add_comment("Info", _("Terminated by {0} with effect from {1}.").format(
			self.name, frappe.format(self.effective_date, "Date")
		))
		if self.non_conformance:
			case = frappe.get_doc("Contractor Non-Conformance", self.non_conformance)
			if case.docstatus == 0:
				case.outcome = "Terminated"
				case.sla_termination = self.name
				case.closing_notes = case.closing_notes or _("Escalated to termination {0}.").format(self.name)
				case.flags.ignore_permissions = True
				case.submit()

	def on_cancel(self):
		sla = frappe.get_doc("Contractor SLA", self.contractor_sla)
		if sla.sla_termination == self.name:
			sla.terminated_on = None
			sla.termination_reason = None
			sla.sla_termination = None
			sla.status = compute_status(sla)
			sla.flags.ignore_permissions = True
			sla.save()
			sla.add_comment("Info", _("Termination {0} cancelled; the SLA is reinstated.").format(self.name))
		if self.non_conformance and frappe.db.get_value(
			"Contractor Non-Conformance", self.non_conformance, "sla_termination"
		) == self.name:
			frappe.get_doc("Contractor Non-Conformance", self.non_conformance).add_comment(
				"Info",
				_("Termination {0} was cancelled. This case stays closed; record a new one if needed.").format(self.name),
			)


@frappe.whitelist()
def get_grounds(initiated_by: str) -> list[str]:
	return list(GROUNDS.get(initiated_by, ()))
