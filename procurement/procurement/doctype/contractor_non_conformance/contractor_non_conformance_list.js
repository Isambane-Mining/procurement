// Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

frappe.listview_settings["Contractor Non-Conformance"] = {
	add_fields: ["status", "remediation_due_date"],
	has_indicator_for_draft: true,
	get_indicator(doc) {
		const colors = {
			Open: "orange",
			Remediation: "yellow",
			"Closed - Remediated": "green",
			"Closed - No Further Action": "gray",
			"Escalated to Termination": "red",
			Cancelled: "red",
		};
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
