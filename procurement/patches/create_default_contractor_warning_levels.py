"""Seed the escalating Contractor Warning Levels (verbal, written, final written)
on sites that have none, so the non-conformance process works out of the box."""

import frappe

LEVELS = (
	("Verbal Warning", 1, 90, 0, "Recorded verbal warning for a minor non-conformance."),
	("Written Warning", 2, 180, 0, "Written warning; a repeat leads to a final written warning."),
	("Final Written Warning", 3, 365, 1, "Last warning before termination of the Agreement."),
)


def execute():
	if frappe.db.count("Contractor Warning Level"):
		return
	for name, severity, validity_days, is_final, description in LEVELS:
		frappe.get_doc(
			{
				"doctype": "Contractor Warning Level",
				"level_name": name,
				"severity": severity,
				"validity_days": validity_days,
				"is_final": is_final,
				"description": description,
			}
		).insert(ignore_permissions=True)
