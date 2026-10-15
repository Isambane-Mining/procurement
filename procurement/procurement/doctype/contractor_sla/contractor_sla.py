# Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
# For license information, please see license.txt

"""Contractor SLA: one Service Level Agreement with a Contractor (Supplier).

Lifecycle (the same signature gate as ir's Contract of Employment)
---------
Draft        the terms are being captured; the wording re-renders on every save
Outstanding  "Issue for Signature" freezes the wording (rendered_agreement) for
             printing and signing; changes that would alter it are refused
             until "Withdraw from Signature". Signature dates and the signed
             copy are recorded on the draft.
Submit       only with both signature dates and the signed copy: the SLA is
             executed and follows its dates: Upcoming -> Active ->
             Expiring Soon -> Expired
Renewal      "Renew" drafts a copy starting the day after this one ends; once
             the renewal is submitted this SLA no longer warns about expiry and
             ends as Renewed instead of Expired
Performance  Contractor Non-Conformance cases, with Contractor Warnings
Termination  a submitted Contractor SLA Termination marks it Terminated, which
             takes it out of every notice

The daily monitor (daily_sla_monitor) keeps statuses current and sends the
expiry, unsigned and overdue-remediation notices configured in Contractor SLA
Settings.
"""

import html
import json
from itertools import groupby

import frappe
from dateutil.relativedelta import relativedelta
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import add_days, cint, date_diff, flt, get_fullname, get_link_to_form, getdate, today

from procurement.procurement.sla_wording import (
	VARIABLES,
	SLAContext,
	format_value,
	parse_wording,
	render_wording,
	used_variables,
)

CLOSED_STATUSES = ("Terminated", "Cancelled")


class ContractorSLA(Document):
	def validate(self):
		self.set_party_names()
		self.validate_dates()
		self.calculate_totals()
		self.validate_signatures()
		self.set_signature_status()
		if self.docstatus == 0:
			if self.sent_for_signature_on and not self.is_new():
				self.check_wording_frozen()
			else:
				self.render_agreement()
		self.status = compute_status(self)

	def before_submit(self):
		missing = [
			self.meta.get_label(fieldname)
			for fieldname in ("contractor_signed_on", "company_signed_on", "signed_copy")
			if not self.get(fieldname)
		]
		if missing:
			frappe.throw(
				_("An SLA can only be submitted once it is signed. Still needed on the Signatures tab: {0}").format(
					", ".join(frappe.bold(label) for label in missing)
				),
				title=_("Not Signed Yet"),
			)
		if not self.sent_for_signature_on:
			# Signed without going through Issue for Signature: freeze what it says now.
			self.check_ready_for_signature()
			self.render_agreement()
			self.sent_for_signature_on = min(getdate(self.contractor_signed_on), getdate(self.company_signed_on))
		self.status = compute_status(self)

	def on_submit(self):
		if self.renewal_of:
			previous = frappe.get_doc("Contractor SLA", self.renewal_of)
			previous.db_set("renewed_by", self.name)
			previous.db_set("status", compute_status(previous), update_modified=False)

	def before_update_after_submit(self):
		self.status = compute_status(self)

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		if self.renewal_of and frappe.db.get_value("Contractor SLA", self.renewal_of, "renewed_by") == self.name:
			previous = frappe.get_doc("Contractor SLA", self.renewal_of)
			previous.db_set("renewed_by", None)
			previous.db_set("status", compute_status(previous), update_modified=False)

	# ---- signature ----

	def check_ready_for_signature(self):
		if frappe.db.get_value("Contractor SLA Template", self.sla_template, "docstatus") != 1:
			frappe.throw(_("SLA Template {0} must be submitted before it can be used.").format(self.sla_template))
		lines, context = self.wording_and_context()
		missing = [
			v.label
			for v in used_variables(lines, context)
			if not v.repeat and v.fmt != "block" and not context.values.get(v.key)
		]
		if missing:
			frappe.throw(
				_("The agreement wording uses these values, which are still blank:<br>{0}").format(
					"<br>".join(f"&bull; {frappe.bold(label)}" for label in missing)
				),
				title=_("Complete the SLA"),
			)

	def check_wording_frozen(self):
		frozen = self.rendered_agreement
		self.render_agreement()
		if self.rendered_agreement != frozen:
			frappe.throw(
				_(
					"This SLA has been issued for signature, so changes that alter the agreement wording are "
					"not allowed. Use Withdraw from Signature to change the terms, then issue it again."
				),
				title=_("Issued for Signature"),
			)

	def issue_for_signature(self):
		if self.docstatus != 0 or self.sent_for_signature_on:
			frappe.throw(_("Only a draft that has not been issued can be issued for signature."))
		self.check_ready_for_signature()
		self.render_agreement()
		self.sent_for_signature_on = today()
		self.save()
		self.add_comment("Info", _("Issued for signature"))

	def withdraw_from_signature(self):
		if self.docstatus != 0 or not self.sent_for_signature_on:
			frappe.throw(_("This SLA has not been issued for signature."))
		self.sent_for_signature_on = None
		self.last_outstanding_notice_on = None
		self.save()
		self.add_comment("Info", _("Withdrawn from signature"))

	# ---- validation ----

	def set_party_names(self):
		# fetch_from only runs after validate(), and the wording needs these now.
		self.supplier_name = frappe.db.get_value("Supplier", self.supplier, "supplier_name") if self.supplier else None
		self.responsible_manager_name = get_fullname(self.responsible_manager) if self.responsible_manager else None

	def validate_dates(self):
		if self.duration_basis == "Fixed Term" and not self.end_date:
			frappe.throw(_("A Fixed Term SLA needs an End Date."))
		if self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date."))
		for row in self.milestones:
			if getdate(row.due_date) < getdate(self.start_date):
				frappe.msgprint(
					_("Milestone row {0} is due before the SLA starts.").format(row.idx), indicator="orange", alert=True
				)

	def validate_signatures(self):
		for fieldname in ("contractor_signed_on", "company_signed_on"):
			value = self.get(fieldname)
			if value and getdate(value) > getdate(today()):
				frappe.throw(_("{0} cannot be in the future.").format(self.meta.get_label(fieldname)))

	def calculate_totals(self):
		for row in self.rates:
			row.amount = flt(row.qty) * flt(row.rate)
		self.total_monthly_value = sum(flt(row.amount) for row in self.rates)

	def set_signature_status(self):
		contractor, company = bool(self.contractor_signed_on), bool(self.company_signed_on)
		self.signature_status = (
			"Fully Signed"
			if contractor and company
			else "Contractor Signed"
			if contractor
			else "Company Signed"
			if company
			else "Unsigned"
		)

	# ---- wording ----

	def wording_and_context(self):
		wording = frappe.db.get_value("Contractor SLA Template", self.sla_template, "sla_wording")
		return parse_wording(wording), build_context(self)

	def render_agreement(self):
		if not self.sla_template:
			self.rendered_agreement = None
			return
		lines, context = self.wording_and_context()
		self.rendered_agreement = render_wording(lines, context)

	def document_title(self):
		return frappe.db.get_value("Contractor SLA Template", self.sla_template, "document_title") or _(
			"SERVICE LEVEL AGREEMENT"
		)


# ---- status ----


def get_settings():
	settings = frappe.get_cached_doc("Contractor SLA Settings")
	thresholds = sorted(
		{cint(part) for part in (settings.expiry_reminder_days or "").split(",") if part.strip().isdigit()},
		reverse=True,
	)
	return frappe._dict(
		warning_days=cint(settings.expiry_warning_days) or 90,
		thresholds=thresholds or [90, 60, 30, 14, 7],
		outstanding_interval=cint(settings.outstanding_reminder_interval),
		notify_role=settings.notify_role,
		send_email=cint(settings.send_email),
	)


def compute_status(doc, on_date=None, warning_days=None) -> str:
	if doc.docstatus == 0:
		return "Outstanding" if doc.sent_for_signature_on else "Draft"
	if doc.docstatus == 2:
		return "Cancelled"
	if doc.terminated_on:
		return "Terminated"
	on_date = getdate(on_date or today())
	if warning_days is None:
		warning_days = get_settings().warning_days
	end = getdate(doc.end_date) if doc.end_date else None
	if end and end < on_date:
		return "Renewed" if doc.renewed_by else "Expired"
	if getdate(doc.start_date) > on_date:
		return "Upcoming"
	# A renewal already in place means there is nothing to warn about.
	if end and date_diff(end, on_date) <= warning_days and not doc.renewed_by:
		return "Expiring Soon"
	return "Active"


# ---- context ----


def build_context(doc) -> SLAContext:
	"""Everything the template can print, formatted, for this SLA."""
	formats = {v.key: v.fmt for v in VARIABLES}

	def value(key, raw):
		return format_value(formats[key], raw)

	start, end = doc.start_date, doc.end_date
	months = whole_months(start, end) if start and end else None
	context = SLAContext(
		values={
			"company_name": value("company_name", doc.company),
			"company_registration_no": value("company_registration_no", doc.company_registration_no),
			"company_address": value("company_address", doc.company_address),
			"company_representative": value("company_representative", doc.company_representative),
			"company_representative_email": value("company_representative_email", doc.company_representative_email),
			"supplier_name": value("supplier_name", doc.supplier_name or doc.supplier),
			"supplier_registration_no": value("supplier_registration_no", doc.supplier_registration_no),
			"supplier_address": value("supplier_address", doc.supplier_address),
			"supplier_representative": value("supplier_representative", doc.supplier_representative),
			"supplier_representative_email": value(
				"supplier_representative_email", doc.supplier_representative_email
			),
			"sla_reference": value("sla_reference", doc.name if not doc.is_new() else ""),
			"scope_of_services": value("scope_of_services", doc.scope_of_services),
			"operation_name": value("operation_name", doc.operation_name),
			"operation_definition": value("operation_definition", (doc.operation_definition or "").rstrip(" ;.")),
			"responsible_manager": value("responsible_manager", doc.responsible_manager_name),
			"pricing_basis": value("pricing_basis", doc.pricing_basis),
			"total_monthly_value": value("total_monthly_value", doc.total_monthly_value),
			"start_date": value("start_date", start),
			"end_date": value("end_date", end),
			"duration_months": value("duration_months", months) if months and months > 0 else "",
			"mobilisation_days": value("mobilisation_days", doc.mobilisation_days),
		}
	)
	context.rows = {
		"services": [
			{"service_description": value("service_description", r.service_description)}
			for r in doc.services
		],
		"milestones": [
			{
				"milestone_description": value("milestone_description", r.milestone_description),
				"milestone_date": value("milestone_date", r.due_date),
			}
			for r in doc.milestones
		],
		"rates": [
			{
				"rate_description": value("rate_description", r.description),
				"rate_basis": value("rate_basis", r.rate_basis),
				"rate_quantity": value("rate_quantity", r.qty),
				"rate_amount": value("rate_amount", r.rate),
			}
			for r in doc.rates
		],
		"equipment": [
			{
				"equipment_make": value("equipment_make", r.make),
				"equipment_type": value("equipment_type", r.equipment_type),
				"equipment_serial_no": value("equipment_serial_no", r.serial_no),
				"equipment_capacity": value("equipment_capacity", r.capacity),
				"equipment_fleet_no": value("equipment_fleet_no", r.fleet_no),
			}
			for r in doc.equipment
		],
		"special_terms": [{"special_term": value("special_term", r.term)} for r in doc.special_terms],
	}
	context.values.update(
		{
			"equipment_table": equipment_table_html(doc.equipment),
			"penalties_table": penalties_table_html(doc.penalties),
			"rates_table": rates_table_html(doc.rates),
			"signature_block": signature_block_html(doc),
		}
	)
	conditions = context.conditions
	conditions.add("duration:project" if doc.duration_basis == "Project Based" else "duration:fixed")
	for kind in ("equipment", "milestones", "penalties", "special_terms"):
		conditions.add(f"{kind}:any" if doc.get(kind) else f"{kind}:none")
	conditions.update(f"option:{row.clause_option}" for row in doc.clause_options)
	return context


def whole_months(start, end) -> int:
	"""Complete months from start to end inclusive: 1 Jan - 31 Dec is 12."""
	span = relativedelta(getdate(add_days(end, 1)), getdate(start))
	return span.years * 12 + span.months


# ---- tables and signature blocks (block variables) ----


def _cell(value, escape=True):
	text = "" if value is None else str(value)
	return html.escape(text).replace("\n", "<br>") if escape else text


def equipment_table_html(rows) -> str:
	if not rows:
		return ""
	head = "".join(
		f"<th>{_(label)}</th>"
		for label in ("Make", "Equipment Type", "Equipment S/N / Reg. No.", "Equipment Capacity", "Fleet No.")
	)
	body = "".join(
		"<tr>"
		+ "".join(_cell(r.get(f)).join(("<td>", "</td>")) for f in ("make", "equipment_type", "serial_no", "capacity", "fleet_no"))
		+ "</tr>"
		for r in rows
	)
	return f'<table class="sla-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def penalties_table_html(rows) -> str:
	"""One table per Table caption. With areas: Area | Criteria | Penalty, runs of
	the same area merged; without: No | Description | Amount and/or Action."""
	if not rows:
		return ""
	out = []
	for caption, group in groupby(rows, key=lambda r: (r.get("penalty_table") or "").strip()):
		group = list(group)
		if caption:
			out.append(f'<p class="sla-table-caption">{_cell(caption)}</p>')
		if any((r.get("area") or "").strip() for r in group):
			body = []
			for area, run in groupby(group, key=lambda r: (r.get("area") or "").strip()):
				run = list(run)
				for i, r in enumerate(run):
					area_cell = f'<td rowspan="{len(run)}">{_cell(area)}</td>' if i == 0 else ""
					body.append(f"<tr>{area_cell}<td>{_cell(r.get('criteria'))}</td><td>{_cell(r.get('penalty'))}</td></tr>")
			head = f"<th>{_('Area')}</th><th>{_('Criteria')}</th><th>{_('Penalty / Action')}</th>"
		else:
			body = [
				f'<tr><td class="sla-center">{n}</td><td>{_cell(r.get("criteria"))}</td><td>{_cell(r.get("penalty"))}</td></tr>'
				for n, r in enumerate(group, 1)
			]
			head = f"<th>{_('No')}</th><th>{_('Description')}</th><th>{_('Amount and/or Action')}</th>"
		out.append(f'<table class="sla-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>')
	return "".join(out)


def rates_table_html(rows) -> str:
	if not rows:
		return ""
	head = "".join(f"<th>{_(label)}</th>" for label in ("Description", "Basis", "Quantity", "Rate", "Amount"))
	body = "".join(
		f"<tr><td>{_cell(r.get('description'))}</td><td>{_cell(r.get('rate_basis'))}</td>"
		f'<td class="sla-right">{flt(r.get("qty")):g}</td>'
		f'<td class="sla-right">{_money(r.get("rate"))}</td><td class="sla-right">{_money(r.get("amount"))}</td></tr>'
		for r in rows
	)
	return f'<table class="sla-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _money(value) -> str:
	return "R " + f"{flt(value):,.2f}".replace(",", " ")


def signature_block_html(doc, escape=True) -> str:
	"""'For the Contractor' and 'For the Company' blocks, as on Isambane's SLAs."""
	line = "_" * 26

	def block(heading, party_label, representative):
		name = _cell(representative, escape) if representative else line
		return (
			'<div class="sla-signature">'
			f"<p><b>{heading}</b></p>"
			f"<p>{_('Thus done and signed at')} ____________________ {_('on this')} ________ {_('day of')} "
			f"______________ 20___ {_('in the presence of the undersigned witnesses.')}</p>"
			'<table class="sla-signature-table">'
			f"<tr><td><u>{_('As Witnesses:')}</u></td><td><u>{party_label}</u></td></tr>"
			f'<tr class="sla-sign-row"><td>1. {line}</td><td>{name}<br><i>({_("Names in Full")})</i></td></tr>'
			f'<tr class="sla-sign-row"><td>2. {line}</td><td>{line}<br><i>({_("Signature")})</i></td></tr>'
			"</table></div>"
		)

	return block(_("FOR THE CONTRACTOR"), _("As the Contractor:"), doc.get("supplier_representative")) + block(
		_("FOR THE COMPANY"), _("As the Company:"), doc.get("company_representative")
	)


# ---- form helpers ----


PARTY_FIELDS = {
	"company": ("company_registration_no", "company_address", "company_representative", "company_representative_email"),
	"supplier": (
		"supplier_registration_no",
		"supplier_address",
		"supplier_representative",
		"supplier_representative_email",
	),
}


@frappe.whitelist()
def get_party_defaults(party_type: str, party: str, exclude: str | None = None) -> dict:
	"""Party details for a new SLA: from the latest other SLA with this party,
	falling back to the Company/Supplier record for anything still blank."""
	if party_type not in PARTY_FIELDS or not party:
		return {}
	frappe.has_permission("Contractor SLA", "read", throw=True)
	fields = PARTY_FIELDS[party_type]
	filters = {party_type: party, "docstatus": ["<", 2]}
	if exclude:
		filters["name"] = ["!=", exclude]
	previous = frappe.get_all(
		"Contractor SLA", filters=filters, fields=list(fields), order_by="creation desc", limit=1
	)
	values = dict(previous[0]) if previous else {}

	if party_type == "company":
		# za_business_address comes from za_local; fall back to an Address linked to the Company.
		address_field = "za_business_address" if frappe.get_meta("Company").has_field("za_business_address") else None
		record = frappe.db.get_value("Company", party, ["email", address_field or "name"], as_dict=True) or {}
		values["company_representative_email"] = values.get("company_representative_email") or record.get("email")
		if not values.get("company_address"):
			values["company_address"] = _address_text(
				(address_field and record.get(address_field)) or _linked_address("Company", party)
			)
	else:
		record = (
			frappe.db.get_value(
				"Supplier", party, ["supplier_primary_address", "supplier_primary_contact", "email_id"], as_dict=True
			)
			or {}
		)
		if not values.get("supplier_address"):
			values["supplier_address"] = _address_text(
				record.get("supplier_primary_address") or _linked_address("Supplier", party)
			)
		if record.get("supplier_primary_contact") and not values.get("supplier_representative"):
			contact = frappe.db.get_value(
				"Contact", record["supplier_primary_contact"], ["full_name", "email_id"], as_dict=True
			)
			if contact:
				values["supplier_representative"] = contact.full_name
				values["supplier_representative_email"] = values.get("supplier_representative_email") or contact.email_id
		values["supplier_representative_email"] = values.get("supplier_representative_email") or record.get("email_id")
	return {k: v for k, v in values.items() if k in fields and v}


def _linked_address(doctype, name):
	return frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Address", "link_doctype": doctype, "link_name": name},
		"parent",
	)


def _address_text(address_name) -> str | None:
	if not address_name or not frappe.db.exists("Address", address_name):
		return None
	a = frappe.db.get_value(
		"Address", address_name, ["address_line1", "address_line2", "city", "state", "pincode"], as_dict=True
	)
	return ", ".join(part for part in (a.address_line1, a.address_line2, a.city, a.state, a.pincode) if part)


@frappe.whitelist()
def get_template_defaults(sla_template: str) -> dict:
	frappe.has_permission("Contractor SLA Template", "read", doc=sla_template, throw=True)
	template = frappe.get_doc("Contractor SLA Template", sla_template)
	return {
		"penalties": [
			{"penalty_table": r.penalty_table, "area": r.area, "criteria": r.criteria, "penalty": r.penalty}
			for r in template.penalties
		]
	}


@frappe.whitelist()
def render_preview(doc) -> str:
	"""The agreement as it would render with the form's unsaved values."""
	doc = frappe.get_doc(json.loads(doc) if isinstance(doc, str) else doc)
	if doc.docstatus != 0 or doc.sent_for_signature_on:
		return doc.rendered_agreement or ""
	doc.check_permission("write" if not doc.is_new() else "create")
	doc.calculate_totals()
	doc.render_agreement()
	return doc.rendered_agreement or ""


@frappe.whitelist()
def issue_for_signature(name: str):
	doc = frappe.get_doc("Contractor SLA", name)
	doc.check_permission("write")
	doc.issue_for_signature()
	return doc.status


@frappe.whitelist()
def withdraw_from_signature(name: str):
	doc = frappe.get_doc("Contractor SLA", name)
	doc.check_permission("write")
	doc.withdraw_from_signature()
	return doc.status


@frappe.whitelist()
def make_non_conformance(source_name: str, target_doc=None):
	return _make_from_sla(source_name, "Contractor Non-Conformance")


@frappe.whitelist()
def make_termination(source_name: str, target_doc=None):
	return _make_from_sla(source_name, "Contractor SLA Termination")


def _make_from_sla(source_name, doctype):
	source = frappe.get_doc("Contractor SLA", source_name)
	source.check_permission("read")
	if source.docstatus != 1 or source.status in CLOSED_STATUSES:
		frappe.throw(_("Only a signed, open SLA can have a {0}.").format(_(doctype)))
	target = frappe.new_doc(doctype)
	target.contractor_sla = source.name
	for fieldname in ("supplier", "supplier_name", "company", "branch", "responsible_manager"):
		if target.meta.has_field(fieldname):
			target.set(fieldname, source.get(fieldname))
	return target


@frappe.whitelist()
def make_renewal(source_name: str, target_doc=None):
	"""A draft SLA continuing this one: same terms, starting the day after it ends."""
	source = frappe.get_doc("Contractor SLA", source_name)
	source.check_permission("read")
	if source.docstatus != 1:
		frappe.throw(_("Only a submitted SLA can be renewed."))
	if source.renewed_by:
		frappe.throw(_("This SLA has already been renewed by {0}.").format(get_link_to_form("Contractor SLA", source.renewed_by)))

	def postprocess(source, target):
		target.renewal_of = source.name
		target.status = "Draft"
		if source.end_date:
			target.start_date = add_days(source.end_date, 1)
			length = date_diff(source.end_date, source.start_date)
			target.end_date = add_days(target.start_date, length) if source.duration_basis == "Fixed Term" else None
		# Use the newest submitted version of the same template, if there is one.
		template_name = frappe.db.get_value("Contractor SLA Template", source.sla_template, "template_name")
		latest = frappe.get_all(
			"Contractor SLA Template",
			filters={"template_name": template_name, "docstatus": 1},
			order_by="creation desc",
			pluck="name",
			limit=1,
		)
		if latest:
			target.sla_template = latest[0]
		target.set("milestones", [])

	return get_mapped_doc(
		"Contractor SLA",
		source_name,
		{"Contractor SLA": {"doctype": "Contractor SLA", "validation": {"docstatus": ["=", 1]}}},
		target_doc,
		postprocess,
	)


# ---- daily monitor and notices ----


def daily_sla_monitor():
	"""Keep statuses current and send expiry / unsigned / overdue-remediation
	notices (scheduler: daily). Terminated and cancelled SLAs are left alone."""
	from procurement.procurement.doctype.contractor_non_conformance.contractor_non_conformance import (
		check_overdue_remediation,
	)
	from procurement.procurement.doctype.contractor_warning.contractor_warning import expire_warnings

	settings = get_settings()
	on_date = getdate(today())
	for name in monitored_slas():
		try:
			check_sla(frappe.get_doc("Contractor SLA", name), settings, on_date)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Contractor SLA monitor failed for {name}")

	for job in (expire_warnings, check_overdue_remediation):
		try:
			job(settings, on_date)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Contractor SLA monitor: {job.__name__} failed")


def monitored_slas() -> list[str]:
	"""Signed SLAs that are not terminated or cancelled, plus drafts out for signature."""
	return frappe.get_all(
		"Contractor SLA",
		filters={"docstatus": 1, "status": ["not in", CLOSED_STATUSES]},
		pluck="name",
	) + frappe.get_all("Contractor SLA", filters={"docstatus": 0, "status": "Outstanding"}, pluck="name")


def check_sla(doc, settings, on_date):
	updates = {}
	status = compute_status(doc, on_date, settings.warning_days)
	if status != doc.status:
		updates["status"] = status

	threshold = due_expiry_notice(doc, status, settings.thresholds, on_date)
	if threshold is not None:
		days_left = date_diff(doc.end_date, on_date)
		if days_left < 0:
			subject = _("SLA expired: {0}").format(sla_label(doc))
			message = _("{0} expired on {1}.").format(sla_label(doc), frappe.format(doc.end_date, "Date"))
		else:
			subject = _("SLA expires in {0} days: {1}").format(days_left, sla_label(doc))
			message = _("{0} expires on {1} ({2} days from today).").format(
				sla_label(doc), frappe.format(doc.end_date, "Date"), days_left
			)
		message += " " + _("Renew it from the SLA, or let it lapse.")
		if send_notice(doc, settings, subject, message):
			sent = [part for part in (doc.expiry_notices_sent or "").split(",") if part]
			updates["expiry_notices_sent"] = ",".join([*sent, str(threshold)])

	if status == "Outstanding" and settings.outstanding_interval > 0:
		since = getdate(doc.last_outstanding_notice_on or doc.sent_for_signature_on or doc.creation)
		if date_diff(on_date, since) >= settings.outstanding_interval:
			outstanding_for = date_diff(on_date, doc.sent_for_signature_on or doc.creation)
			pending = {
				"Unsigned": _("the Contractor and the Company"),
				"Contractor Signed": _("the Company"),
				"Company Signed": _("the Contractor"),
			}.get(doc.signature_status, _("both parties"))
			if send_notice(
				doc,
				settings,
				_("SLA awaiting signature: {0}").format(sla_label(doc)),
				_("{0} was issued for signature {1} days ago and still needs to be signed by {2}.").format(
					sla_label(doc), outstanding_for, pending
				),
			):
				updates["last_outstanding_notice_on"] = on_date

	if updates:
		frappe.db.set_value("Contractor SLA", doc.name, updates, update_modified=False)


def due_expiry_notice(doc, status, thresholds, on_date) -> int | None:
	"""The notice threshold (days before End Date) this SLA has reached and not yet
	been told about; -1 is the "has expired" notice, only sent within a week of
	expiry so old SLAs don't all fire when the monitor first runs."""
	if doc.docstatus != 1 or not doc.end_date or doc.renewed_by or status in CLOSED_STATUSES:
		return None
	days_left = date_diff(doc.end_date, on_date)
	if days_left < 0:
		threshold = -1 if days_left >= -7 else None
	else:
		reached = [t for t in thresholds if days_left <= t]
		threshold = min(reached) if reached else None
	if threshold is None:
		return None
	sent = {cint(part) for part in (doc.expiry_notices_sent or "").split(",") if part.strip()}
	return None if threshold in sent else threshold


def sla_label(doc) -> str:
	return f"{doc.name} ({doc.supplier_name or doc.supplier}: {doc.sla_title})"


def notice_recipients(doc, settings, extra=()) -> list[str]:
	users = {doc.responsible_manager, doc.owner, *extra}
	if settings.notify_role:
		users.update(
			frappe.get_all(
				"Has Role",
				filters={"role": settings.notify_role, "parenttype": "User"},
				pluck="parent",
			)
		)
	users.discard(None)
	users -= {"Administrator", "Guest"}
	return sorted(frappe.get_all("User", filters={"name": ["in", list(users)], "enabled": 1}, pluck="name")) if users else []


def send_notice(doc, settings, subject, message, extra_recipients=()) -> bool:
	"""Bell notice (and email, if enabled) to the SLA's people. False when there
	is nobody to tell, so the notice is retried once someone is configured.
	`doc` may be any document with responsible_manager/owner (an SLA or a case)."""
	users = notice_recipients(doc, settings, extra_recipients)
	if not users:
		return False
	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	enqueue_create_notification(
		users,
		{
			"type": "Alert",
			"document_type": doc.doctype,
			"document_name": doc.name,
			"subject": subject,
			"email_content": message,
		},
	)
	if settings.send_email:
		# The bell notice stands even if email can't go out (e.g. no outgoing account).
		try:
			frappe.sendmail(
				recipients=users,
				subject=subject,
				message=f"<p>{html.escape(message)}</p><p>{get_link_to_form(doc.doctype, doc.name, _('Open {0}').format(doc.name))}</p>",
				reference_doctype=doc.doctype,
				reference_name=doc.name,
			)
		except frappe.OutgoingEmailError:
			if not frappe.flags.sla_email_error_logged:  # once per run, not once per notice
				frappe.flags.sla_email_error_logged = True
				frappe.log_error(title="Contractor SLA notice email not sent")
	return True
