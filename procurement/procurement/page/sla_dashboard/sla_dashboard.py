# Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_months, date_diff, flt, get_first_day, getdate, today

from procurement.procurement.doctype.contractor_sla.contractor_sla import get_settings

CURRENT_STATUSES = ("Outstanding", "Upcoming", "Active", "Expiring Soon")


@frappe.whitelist()
def get_dashboard_data(company=None, supplier=None, branch=None):
	"""Every figure the SLA Dashboard shows, from SLAs the user may read."""
	filters = {"docstatus": ["<", 2]}
	for field, value in (("company", company), ("supplier", supplier), ("branch", branch)):
		if value:
			filters[field] = value

	slas = frappe.get_list(
		"Contractor SLA",
		filters=filters,
		fields=[
			"name", "sla_title", "supplier", "supplier_name", "company", "branch", "status", "signature_status",
			"start_date", "end_date", "total_monthly_value", "responsible_manager_name", "sent_for_signature_on",
			"renewed_by", "duration_basis",
		],
		order_by="end_date asc",
		limit_page_length=0,
	)
	on_date = getdate(today())
	for sla in slas:
		sla.days_to_expiry = date_diff(sla.end_date, on_date) if sla.end_date else None
		sla.days_unsigned = (
			date_diff(on_date, sla.sent_for_signature_on)
			if sla.status == "Outstanding" and sla.sent_for_signature_on
			else None
		)

	current = [s for s in slas if s.status in CURRENT_STATUSES]
	recently_expired = [
		s for s in slas if s.status == "Expired" and s.days_to_expiry is not None and s.days_to_expiry >= -90
	]
	counts = {status: sum(1 for s in slas if s.status == status) for status in (*CURRENT_STATUSES, "Expired")}

	return {
		"warning_days": get_settings().warning_days,
		"counts": counts,
		"monthly_value": sum(flt(s.total_monthly_value) for s in current if s.status != "Outstanding"),
		"expiring": [s for s in current if s.status == "Expiring Soon"],
		"outstanding": sorted(
			(s for s in current if s.status == "Outstanding"), key=lambda s: -(s.days_unsigned or 0)
		),
		"expired": recently_expired,
		"current": current,
		"expiry_by_month": expiry_by_month(current, on_date),
		"drafts": sum(1 for s in slas if s.status == "Draft"),
		**non_conformance_data(filters, on_date),
	}


def non_conformance_data(filters, on_date):
	"""Open non-conformance cases and the warnings in force, under the same filters."""
	case_filters = {k: v for k, v in filters.items() if k != "docstatus"}
	cases = frappe.get_list(
		"Contractor Non-Conformance",
		filters={**case_filters, "docstatus": 0},
		fields=[
			"name", "contractor_sla", "supplier", "supplier_name", "branch", "category", "severity", "status",
			"report_date", "remediation_due_date", "remediation_verified_on", "warning",
		],
		order_by="remediation_due_date asc, report_date asc",
		limit_page_length=0,
	)
	levels = dict(
		frappe.get_all(
			"Contractor Warning",
			filters={"name": ["in", [c.warning for c in cases if c.warning] or [""]]},
			fields=["name", "warning_level"],
			as_list=True,
		)
	)
	for case in cases:
		case.warning_level = levels.get(case.warning)
		case.days_overdue = (
			date_diff(on_date, case.remediation_due_date)
			if case.remediation_due_date and not case.remediation_verified_on and getdate(case.remediation_due_date) < on_date
			else None
		)
	warning_filters = {k: v for k, v in case_filters.items() if k != "branch"}
	return {
		"non_conformances": cases,
		"remediation_overdue": sum(1 for c in cases if c.days_overdue),
		"warnings_in_force": frappe.db.count(
			"Contractor Warning", {**warning_filters, "docstatus": 1, "valid_until": [">=", on_date]}
		),
	}


def expiry_by_month(slas, on_date, months=12):
	"""Current SLAs ending in each of the next `months` calendar months."""
	start = get_first_day(on_date)
	buckets = [add_months(start, i) for i in range(months)]
	counts = [0] * months
	for sla in slas:
		if not sla.end_date:
			continue
		end = getdate(sla.end_date)
		index = (end.year - start.year) * 12 + end.month - start.month
		if 0 <= index < months:
			counts[index] += 1
	return {"labels": [_(b.strftime("%b")) + b.strftime(" %Y") for b in buckets], "values": counts}
