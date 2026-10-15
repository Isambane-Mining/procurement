// Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

frappe.listview_settings["Contractor Warning"] = {
	add_fields: ["status", "valid_until"],
	has_indicator_for_draft: true,
	get_indicator(doc) {
		const colors = { Draft: "gray", Active: "orange", Expired: "green", Cancelled: "red" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
