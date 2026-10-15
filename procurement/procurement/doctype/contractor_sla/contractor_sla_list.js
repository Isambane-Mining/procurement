// Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

const SLA_STATUS_COLORS = {
	Draft: "gray",
	Outstanding: "orange",
	Upcoming: "blue",
	Active: "green",
	"Expiring Soon": "yellow",
	Expired: "red",
	Renewed: "purple",
	Terminated: "red",
	Cancelled: "red",
};

frappe.listview_settings["Contractor SLA"] = {
	add_fields: ["status", "end_date", "signature_status"],
	has_indicator_for_draft: true,
	get_indicator(doc) {
		return [__(doc.status), SLA_STATUS_COLORS[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
