# Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
# For license information, please see license.txt

"""Contractor SLA Template: the reusable SLA wording.

The wording engine lives in procurement.procurement.sla_wording; Contractor
SLA renders its agreements through it. See that module for the storage format,
dynamic clauses and numbering rule.
"""

import json
import os

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime

from procurement.procurement.sla_wording import (
	editor_config,
	load_delta,
	parse_markdown,
	parse_wording,
	preview_context,
	render_wording,
	to_delta,
	to_markdown,
	validate_lines,
)


class ContractorSLATemplate(Document):
	def autoname(self):
		# Amendments never reach here - Frappe names them "<name>-1" first.
		template_name = (self.template_name or "").strip()
		if not template_name:
			frappe.throw(_("Template Name is required before naming."))

		created = getdate(self.creation or now_datetime()).strftime("%d-%m-%Y")
		candidate_name = f"{template_name} - {created}"
		if frappe.db.exists(self.doctype, candidate_name):
			frappe.throw(
				_(
					"A Contractor SLA Template named {0} already exists. Amend the existing "
					"template instead, or use a different name."
				).format(frappe.bold(candidate_name)),
				title=_("Duplicate Contractor SLA Template"),
			)
		self.template_name = template_name
		self.name = candidate_name

	def validate(self):
		lines = self.lines_from_input()
		self.raise_for(validate_lines(lines))
		# Store only what the editor can produce, and keep the Markdown tab in step.
		self.sla_wording = json.dumps(to_delta(lines), ensure_ascii=False, separators=(",", ":"))
		self.sla_markdown = to_markdown(lines)

	def lines_from_input(self):
		"""The editor wins, unless only the Markdown tab was edited."""
		markdown_edited = self.has_value_changed("sla_markdown") and (self.sla_markdown or "").strip()
		wording_edited = self.has_value_changed("sla_wording") and load_delta(self.sla_wording)["ops"]
		if markdown_edited and not wording_edited:
			return parse_markdown(self.sla_markdown)
		return parse_wording(self.sla_wording)

	def before_submit(self):
		lines = parse_wording(self.sla_wording)
		if not any(line.kind in ("heading", "clause") for line in lines):
			frappe.throw(_("Add the SLA wording before submitting."))
		self.raise_for(validate_lines(lines, for_submit=True))

	@staticmethod
	def raise_for(errors):
		if errors:
			frappe.throw("<br>".join(errors), title=_("SLA Wording"))


@frappe.whitelist()
def get_editor_config():
	frappe.has_permission("Contractor SLA Template", "read", throw=True)
	return editor_config()


@frappe.whitelist()
def preview_wording(sla_wording=None, scenario=None):
	"""Render the wording for a sample scenario (see sla_wording.preview_context)."""
	frappe.has_permission("Contractor SLA Template", "read", throw=True)
	scenario = frappe.parse_json(scenario) if isinstance(scenario, str) else (scenario or {})
	return render_wording(parse_wording(sla_wording), preview_context(scenario))


@frappe.whitelist()
def wording_to_markdown(sla_wording=None):
	frappe.has_permission("Contractor SLA Template", "read", throw=True)
	return to_markdown(parse_wording(sla_wording))


@frappe.whitelist()
def markdown_to_wording(sla_markdown=None):
	"""Markdown tab -> editor content; problems come back as messages, not errors,
	so half-typed Markdown never interrupts the user."""
	frappe.has_permission("Contractor SLA Template", "read", throw=True)
	lines = parse_markdown(sla_markdown or "")
	return {"sla_wording": json.dumps(to_delta(lines), ensure_ascii=False), "errors": validate_lines(lines)}


# ---- Standard template (transcribed from Isambane's ESD SLA) ----

STANDARD_TEMPLATE_NAME = "Standard Contractor SLA"
STANDARD_TEMPLATE_FILE = os.path.join(os.path.dirname(__file__), "standard_contractor_sla.md")
STANDARD_CLAUSE_OPTIONS = {
	"Diesel Supplied by Company": "The Company supplies diesel, subject to a diesel cap set out in Annexure A.",
	"Rates Conditional on Availability": "Rates are payable at 100% availability; non-available units are paid pro rata.",
}
STANDARD_PENALTIES = [
	# (table, area, criteria, penalty)
	("Table 1: Penalty and/or Action items applicable to the Contractor", "Environmental Management", "Non compliance penalty for each instance", "Any section 54/55 applied by the authorities results in R 40 000.00 per day of such stoppage"),
	("Table 1: Penalty and/or Action items applicable to the Contractor", "Environmental Management", "Late report submissions or documentation to DMR or DWS as and when required by the client or the Company", "R 40 000.00 for each late submission"),
	("Table 1: Penalty and/or Action items applicable to the Contractor", "Environmental Management", "Non-conformance to instructions", "R 20 000.00 for each non-conformance"),
	("Table 1: Penalty and/or Action items applicable to the Contractor", "Environmental Management", "Failure to rectify any deviations (such as sub-standard illumination) in an agreed time", "R 10 000.00 for each non-conformance"),
	("Table 1: Penalty and/or Action items applicable to the Contractor", "Environmental Management", "Failure to complete over exposure within prescribed time limits", "R 10 000.00 for each non-conformance"),
	("Table 1: Penalty and/or Action items applicable to the Contractor", "Safety, governance, and assurance structure", "Late submissions of reports to the client's Line Management, the Company and/or the DMR", "R 20 000.00 for each late submission"),
	("Table 1: Penalty and/or Action items applicable to the Contractor", "Safety, governance, and assurance structure", "Failure to close out any safety incidents within reasonable time", "R 5 000.00 for failure to close out safety incidents"),
	("Table 1: Penalty and/or Action items applicable to the Contractor", "Safety, governance, and assurance structure", "", "Any section 54/55 applied by the authorities results in R 40 000.00 per day of such stoppage"),
	("Table 1: Penalty and/or Action items applicable to the Contractor", "Compliance to Maintenance Requirement", "Non-compliance to maintenance activities required as per Scope of Work will result in a penalty", "R 20 000.00 for each non-compliance and additional R 10 000.00 for repetitive (for same item) non-compliance"),
	("Table 2: General non-compliance penalties", "", "Unauthorized entry on the Site/s", "Removed from Site/s immediately and possible criminal charges"),
	("Table 2: General non-compliance penalties", "", "No induction and working on the Site/s", "R 2 500.00 per person"),
	("Table 2: General non-compliance penalties", "", "No medical and working on Site/s", "R 2 500.00 per person"),
	("Table 2: General non-compliance penalties", "", "Non-compliance to Zivikele Pledge, Fatal Risk Standards", "R 20 000.00 (per transgression) or termination due to breach of the Zivikele Pledge"),
	("Table 2: General non-compliance penalties", "", "Not reporting incidents / accidents", "R 20 000.00 (per transgression)"),
	("Table 2: General non-compliance penalties", "", "Unsafe working on heights and unsafe scaffolding", "Removed from Site/s immediately and R 5 000.00 (value per transgression)"),
	("Table 2: General non-compliance penalties", "", "Working near O/H power lines - no permit", "R 15 000.00 (per transgression)"),
	("Table 2: General non-compliance penalties", "", "Excavating without permit", "R 15 000.00 (per transgression)"),
	("Table 2: General non-compliance penalties", "", "Endangering own life", "R 15 000.00 (per transgression)"),
	("Table 2: General non-compliance penalties", "", "Endangering life of others", "R 15 000.00 (per transgression)"),
	("Table 2: General non-compliance penalties", "", "Breach of any rigging rule/standard", "R 10 000.00 (per transgression)"),
]


def load_standard_template(submit: bool = False) -> str:
	"""Create (or refresh the draft of) the Standard Contractor SLA template from
	standard_contractor_sla.md, with its clause options and default penalties.
	Once a version is submitted this returns it unchanged.
	Run with `bench --site <site> execute
	procurement.procurement.doctype.contractor_sla_template.contractor_sla_template.load_standard_template`.
	"""
	for option, description in STANDARD_CLAUSE_OPTIONS.items():
		if not frappe.db.exists("Contractor SLA Clause Option", option):
			frappe.get_doc(
				{"doctype": "Contractor SLA Clause Option", "option_name": option, "description": description}
			).insert()

	with open(STANDARD_TEMPLATE_FILE) as fh:
		markdown = fh.read()

	existing = frappe.db.get_value(
		"Contractor SLA Template", {"template_name": STANDARD_TEMPLATE_NAME, "docstatus": 0}, "name"
	)
	if not existing:
		# Already loaded and submitted: change its wording by amending it in the UI.
		submitted = frappe.db.get_value(
			"Contractor SLA Template", {"template_name": STANDARD_TEMPLATE_NAME, "docstatus": 1}, "name"
		)
		if submitted:
			return submitted
	doc = (
		frappe.get_doc("Contractor SLA Template", existing)
		if existing
		else frappe.new_doc("Contractor SLA Template")
	)
	doc.template_name = STANDARD_TEMPLATE_NAME
	doc.document_title = "SERVICE LEVEL AGREEMENT"
	doc.description = "Isambane's standard subcontractor SLA (from ESD_01), with Annexure A."
	doc.sla_markdown = markdown
	doc.sla_wording = None  # rebuild from the Markdown
	doc.set(
		"penalties",
		[
			{"penalty_table": table, "area": area, "criteria": criteria, "penalty": penalty}
			for table, area, criteria, penalty in STANDARD_PENALTIES
		],
	)
	doc.save()
	if submit:
		doc.submit()
	return doc.name
