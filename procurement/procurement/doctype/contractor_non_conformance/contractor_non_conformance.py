# Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
# For license information, please see license.txt

"""Contractor Non-Conformance: one documented case of a contractor failing its
SLA, worked like ir's Poor Performance process.

The case stays open (draft) while it is worked:
Open           recorded, with evidence and the contractor's history
Remediation    a Contractor Warning has been issued and/or corrective actions
               are set; the daily monitor flags them once overdue
Closing (submit) is always through an outcome:
  Closed - Remediated          every corrective action done and verified
  Closed - No Further Action   with closing notes
  Escalated to Termination     set by a submitted Contractor SLA Termination

Warnings escalate: the suggested level is one above the contractor's most
serious warning still in force on the SLA; with a final warning in force the
case points to termination instead.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, getdate, today

from procurement.procurement.doctype.contractor_sla.contractor_sla import CLOSED_STATUSES, send_notice

OUTCOME_STATUS = {
	"Remediated": "Closed - Remediated",
	"No Further Action": "Closed - No Further Action",
	"Terminated": "Escalated to Termination",
}


class ContractorNonConformance(Document):
	def validate(self):
		if self.is_new() or self.has_value_changed("contractor_sla"):
			self.validate_sla()
		self.validate_actions()
		self.set_history()
		self.status = self.compute_status()

	def before_submit(self):
		if self.outcome not in OUTCOME_STATUS:
			frappe.throw(
				_(
					"Close a non-conformance through its Actions: Close - Remediated, Close - No Further Action, "
					"or Escalate to Termination."
				),
				title=_("Choose an Outcome"),
			)
		if self.outcome == "Remediated":
			open_actions = [row.idx for row in self.corrective_actions if not row.completed_on]
			if open_actions or not self.corrective_actions:
				frappe.throw(_("Every corrective action needs a Completed On date before closing as remediated."))
			if not self.remediation_verified_on:
				frappe.throw(_("Set Remediation Verified On before closing as remediated."))
		if self.outcome == "No Further Action" and not (self.closing_notes or "").strip():
			frappe.throw(_("Give the reason for taking no further action in Closing Notes."))
		self.closed_on = self.closed_on or today()
		self.status = self.compute_status()

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def validate_sla(self):
		docstatus, status = frappe.db.get_value("Contractor SLA", self.contractor_sla, ["docstatus", "status"])
		if docstatus != 1 or status in CLOSED_STATUSES:
			frappe.throw(_("Non-conformances can only be recorded against a signed SLA that is not terminated."))

	def validate_actions(self):
		for row in self.corrective_actions:
			if row.completed_on and getdate(row.completed_on) > getdate(today()):
				frappe.throw(_("Corrective action row {0}: Completed On cannot be in the future.").format(row.idx))
		due = [getdate(row.due_date) for row in self.corrective_actions if row.due_date]
		self.remediation_due_date = max(due) if due else None
		if self.remediation_verified_on and any(not row.completed_on for row in self.corrective_actions):
			frappe.throw(_("Remediation can only be verified once every corrective action is completed."))

	def compute_status(self):
		if self.docstatus == 2:
			return "Cancelled"
		if self.docstatus == 1 or self.outcome in OUTCOME_STATUS:
			return OUTCOME_STATUS.get(self.outcome, "Open")
		return "Remediation" if (self.warning or self.corrective_actions) else "Open"

	def set_history(self):
		self.set("history", contractor_history(self.supplier, exclude=self.name))


def contractor_history(supplier, exclude=None) -> list[dict]:
	"""Every earlier non-conformance for this contractor, newest first, with its latest warning."""
	if not supplier:
		return []
	filters = {"supplier": supplier, "docstatus": ["<", 2]}
	if exclude and not str(exclude).startswith("new-"):
		filters["name"] = ["!=", exclude]
	cases = frappe.get_all(
		"Contractor Non-Conformance",
		filters=filters,
		fields=["name", "report_date", "contractor_sla", "category", "severity", "status", "warning"],
		order_by="report_date desc, creation desc",
	)
	rows = []
	for case in cases:
		warning = (
			frappe.db.get_value("Contractor Warning", case.warning, ["warning_level", "valid_until"], as_dict=True)
			if case.warning
			else None
		) or {}
		rows.append(
			{
				"non_conformance": case.name,
				"report_date": case.report_date,
				"contractor_sla": case.contractor_sla,
				"category": case.category,
				"severity": case.severity,
				"outcome": case.status,
				"warning_level": warning.get("warning_level"),
				"valid_until": warning.get("valid_until"),
			}
		)
	return rows


def active_warnings(contractor_sla, on_date=None) -> list[dict]:
	"""Submitted warnings on this SLA still in force, most serious first."""
	on_date = on_date or today()
	warnings = frappe.get_all(
		"Contractor Warning",
		filters={"contractor_sla": contractor_sla, "docstatus": 1, "valid_until": [">=", on_date]},
		fields=["name", "warning_level", "valid_until", "issue_date"],
	)
	levels = {
		level.name: level
		for level in frappe.get_all("Contractor Warning Level", fields=["name", "severity", "is_final"])
	}
	for warning in warnings:
		level = levels.get(warning.warning_level) or frappe._dict(severity=0, is_final=0)
		warning.severity, warning.is_final = level.severity, level.is_final
	return sorted(warnings, key=lambda w: -w.severity)


def suggested_level(contractor_sla) -> dict:
	"""The warning level to issue next, or a termination recommendation."""
	in_force = active_warnings(contractor_sla)
	top = in_force[0] if in_force else None
	if top and top.is_final:
		return {"recommend_termination": True, "active": in_force, "level": None}
	floor = top.severity if top else -1
	levels = frappe.get_all(
		"Contractor Warning Level",
		filters={"disabled": 0, "severity": [">", floor]},
		fields=["name", "severity", "is_final"],
		order_by="severity asc",
		limit=1,
	)
	return {
		"recommend_termination": not levels and bool(top),
		"active": in_force,
		"level": levels[0].name if levels else None,
	}


# ---- actions ----


@frappe.whitelist()
def get_case_summary(name: str) -> dict:
	doc = frappe.get_doc("Contractor Non-Conformance", name)
	doc.check_permission("read")
	return suggested_level(doc.contractor_sla)


@frappe.whitelist()
def make_warning(source_name: str, target_doc=None):
	case = frappe.get_doc("Contractor Non-Conformance", source_name)
	case.check_permission("write")
	if case.docstatus != 0:
		frappe.throw(_("Warnings can only be issued on an open non-conformance."))
	suggestion = suggested_level(case.contractor_sla)
	warning = frappe.new_doc("Contractor Warning")
	warning.non_conformance = case.name
	for fieldname in ("contractor_sla", "supplier", "supplier_name", "company"):
		warning.set(fieldname, case.get(fieldname))
	warning.warning_level = suggestion["level"]
	warning.details = case.description
	open_actions = [row for row in case.corrective_actions if not row.completed_on]
	warning.corrective_action_required = "\n".join(f"- {row.action}" for row in open_actions)
	# An already-passed due date can't be a new deadline: give a week by default.
	due = case.remediation_due_date
	warning.remediation_due_date = due if due and getdate(due) >= getdate(today()) else add_days(today(), 7)
	warning.recipient, warning.recipient_email = frappe.db.get_value(
		"Contractor SLA", case.contractor_sla, ["supplier_representative", "supplier_representative_email"]
	)
	return warning


@frappe.whitelist()
def close_case(name: str, outcome: str, notes: str | None = None):
	if outcome not in ("Remediated", "No Further Action"):
		frappe.throw(_("Invalid outcome."))
	doc = frappe.get_doc("Contractor Non-Conformance", name)
	doc.check_permission("submit")
	doc.outcome = outcome
	if notes:
		doc.closing_notes = notes
	doc.submit()
	return doc.status


@frappe.whitelist()
def make_termination(source_name: str, target_doc=None):
	case = frappe.get_doc("Contractor Non-Conformance", source_name)
	case.check_permission("read")
	if case.docstatus != 0:
		frappe.throw(_("Only an open non-conformance can be escalated."))
	termination = frappe.new_doc("Contractor SLA Termination")
	termination.contractor_sla = case.contractor_sla
	termination.non_conformance = case.name
	termination.initiated_by = "Company"
	termination.termination_ground = "Material Breach Not Remedied"
	for fieldname in ("supplier", "supplier_name", "company", "branch"):
		termination.set(fieldname, case.get(fieldname))
	termination.reason = case.description
	return termination


# ---- daily monitor ----


def check_overdue_remediation(settings, on_date):
	"""Tell the SLA's people once when an open case's remediation falls overdue."""
	cases = frappe.get_all(
		"Contractor Non-Conformance",
		filters={
			"docstatus": 0,
			"remediation_due_date": ["<", on_date],
			"remediation_verified_on": ["is", "not set"],
			"overdue_notified_on": ["is", "not set"],
		},
		pluck="name",
	)
	for name in cases:
		case = frappe.get_doc("Contractor Non-Conformance", name)
		if any(row.completed_on is None for row in case.corrective_actions) or not case.corrective_actions:
			days = date_diff(on_date, case.remediation_due_date)
			if send_notice(
				case,
				settings,
				_("Remediation overdue: {0} ({1})").format(case.name, case.supplier_name),
				_(
					"{0} ({1}, {2}) was due to be remediated on {3}, {4} days ago. Verify the remediation, "
					"issue a further warning, or escalate to termination."
				).format(
					case.name, case.supplier_name, case.category, frappe.format(case.remediation_due_date, "Date"), days
				),
				extra_recipients=(case.reported_by,),
			):
				case.db_set("overdue_notified_on", on_date, update_modified=False)
