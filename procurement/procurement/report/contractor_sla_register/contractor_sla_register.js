// Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Contractor SLA Register"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "supplier", label: __("Contractor"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "branch", label: __("Site"), fieldtype: "Link", options: "Branch" },
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: [
				"",
				"Draft",
				"Outstanding",
				"Upcoming",
				"Active",
				"Expiring Soon",
				"Expired",
				"Renewed",
				"Terminated",
			],
		},
		{
			fieldname: "expiring_within",
			label: __("Ending Within (days)"),
			fieldtype: "Int",
		},
		{
			fieldname: "include_closed",
			label: __("Include Draft / Closed"),
			fieldtype: "Check",
			description: __("By default only current SLAs (Outstanding, Upcoming, Active, Expiring Soon) are listed."),
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "days_to_expiry" && data.days_to_expiry != null && data.days_to_expiry <= 90) {
			return `<span style="color: var(--${data.days_to_expiry < 0 ? "red" : "orange"}-600); font-weight: 600">${value}</span>`;
		}
		if (column.fieldname === "days_unsigned" && data.days_unsigned) {
			return `<span style="color: var(--red-600); font-weight: 600">${value}</span>`;
		}
		return value;
	},
};
