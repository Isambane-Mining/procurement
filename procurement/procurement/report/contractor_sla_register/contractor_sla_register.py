# Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, today

CURRENT_STATUSES = ("Outstanding", "Upcoming", "Active", "Expiring Soon")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = get_data(filters)
	return get_columns(), rows, None, get_chart(rows), get_summary(rows)


def get_columns():
	return [
		{"fieldname": "name", "label": _("SLA"), "fieldtype": "Link", "options": "Contractor SLA", "width": 140},
		{"fieldname": "sla_title", "label": _("Title"), "fieldtype": "Data", "width": 200},
		{"fieldname": "supplier", "label": _("Contractor"), "fieldtype": "Link", "options": "Supplier", "width": 180},
		{"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 170},
		{"fieldname": "branch", "label": _("Site"), "fieldtype": "Link", "options": "Branch", "width": 120},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "signature_status", "label": _("Signature"), "fieldtype": "Data", "width": 130},
		{"fieldname": "start_date", "label": _("Start"), "fieldtype": "Date", "width": 100},
		{"fieldname": "end_date", "label": _("End"), "fieldtype": "Date", "width": 100},
		{"fieldname": "days_to_expiry", "label": _("Days to Expiry"), "fieldtype": "Int", "width": 110},
		{"fieldname": "days_unsigned", "label": _("Days Unsigned"), "fieldtype": "Int", "width": 110},
		{"fieldname": "total_monthly_value", "label": _("Monthly Value"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "responsible_manager_name", "label": _("Responsible Manager"), "fieldtype": "Data", "width": 160},
		{"fieldname": "renewed_by", "label": _("Renewed By"), "fieldtype": "Link", "options": "Contractor SLA", "width": 130},
	]


def get_data(filters):
	conditions = {"docstatus": ["<", 2]}
	for field in ("company", "supplier", "branch"):
		if filters.get(field):
			conditions[field] = filters[field]
	if filters.get("status"):
		conditions["status"] = filters.status
	elif not filters.get("include_closed"):
		conditions["status"] = ["in", CURRENT_STATUSES]
	if filters.get("expiring_within"):
		conditions["end_date"] = ["between", [today(), frappe.utils.add_days(today(), int(filters.expiring_within))]]

	rows = frappe.get_list(
		"Contractor SLA",
		filters=conditions,
		fields=[
			"name", "sla_title", "supplier", "supplier_name", "company", "branch", "status", "signature_status",
			"start_date", "end_date", "total_monthly_value", "responsible_manager_name", "renewed_by",
			"sent_for_signature_on",
		],
		order_by="end_date asc",
	)
	on_date = getdate(today())
	for row in rows:
		row.days_to_expiry = date_diff(row.end_date, on_date) if row.end_date else None
		row.days_unsigned = (
			date_diff(on_date, row.sent_for_signature_on) if row.status == "Outstanding" and row.sent_for_signature_on else None
		)
	return rows


def get_chart(rows):
	counts = {}
	for row in rows:
		counts[row.status] = counts.get(row.status, 0) + 1
	if not counts:
		return None
	return {
		"data": {"labels": list(counts), "datasets": [{"name": _("SLAs"), "values": list(counts.values())}]},
		"type": "bar",
		"colors": ["#5e64ff"],
	}


def get_summary(rows):
	return [
		{"label": _("SLAs"), "value": len(rows), "indicator": "blue", "datatype": "Int"},
		{
			"label": _("Expiring Soon"),
			"value": sum(1 for r in rows if r.status == "Expiring Soon"),
			"indicator": "orange",
			"datatype": "Int",
		},
		{
			"label": _("Awaiting Signature"),
			"value": sum(1 for r in rows if r.status == "Outstanding"),
			"indicator": "red",
			"datatype": "Int",
		},
		{
			"label": _("Monthly Value (current)"),
			"value": sum(r.total_monthly_value or 0 for r in rows if r.status in CURRENT_STATUSES),
			"indicator": "green",
			"datatype": "Currency",
		},
	]
