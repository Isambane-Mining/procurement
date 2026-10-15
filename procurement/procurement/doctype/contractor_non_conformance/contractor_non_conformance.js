// Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

const NC_METHOD = "procurement.procurement.doctype.contractor_non_conformance.contractor_non_conformance";

frappe.ui.form.on("Contractor Non-Conformance", {
	setup(frm) {
		frm.set_query("contractor_sla", () => ({
			filters: { docstatus: 1, status: ["not in", ["Terminated", "Cancelled"]] },
		}));
	},

	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0) return;
		hold_submit(frm, false);
		show_escalation(frm);
		if (!frappe.model.can_write("Contractor Non-Conformance")) return;

		const group = __("Actions");
		frm.add_custom_button(
			__("Issue Warning"),
			() => frappe.model.open_mapped_doc({ method: `${NC_METHOD}.make_warning`, frm }),
			group
		);
		frm.add_custom_button(__("Close - Remediated"), () => close_case(frm, "Remediated"), group);
		frm.add_custom_button(__("Close - No Further Action"), () => close_case(frm, "No Further Action"), group);
		if (frappe.model.can_create("Contractor SLA Termination")) {
			frm.add_custom_button(
				__("Escalate to Termination"),
				() => frappe.model.open_mapped_doc({ method: `${NC_METHOD}.make_termination`, frm }),
				group
			);
		}
		frm.page.set_inner_btn_group_as_primary(group);
	},
});

// The warnings in force on this SLA and what the next step should be.
function show_escalation(frm) {
	frappe.xcall(`${NC_METHOD}.get_case_summary`, { name: frm.doc.name }).then((summary) => {
		const active = summary.active
			.map((w) => `${w.name} (${w.warning_level}, ${__("until")} ${frappe.datetime.str_to_user(w.valid_until)})`)
			.join(", ");
		let message = active
			? __("Warnings in force on this SLA: {0}.", [active])
			: __("No warnings in force on this SLA.");
		if (summary.recommend_termination) {
			message += " " + __("A final warning is in force: consider Escalate to Termination.");
		} else if (summary.level) {
			message += " " + __("A new warning would be a {0}.", [summary.level]);
		}
		if (
			frm.doc.remediation_due_date &&
			!frm.doc.remediation_verified_on &&
			frm.doc.remediation_due_date < frappe.datetime.get_today()
		) {
			message += " " + __("Remediation was due on {0}.", [frappe.datetime.str_to_user(frm.doc.remediation_due_date)]);
		}
		frm.dashboard.add_comment(message, summary.recommend_termination ? "red" : "blue", true);
	});
}

function close_case(frm, outcome) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the non-conformance first."));
		return;
	}
	frappe.prompt(
		[
			{
				fieldtype: "Small Text",
				fieldname: "notes",
				label: __("Closing Notes"),
				reqd: outcome === "No Further Action" ? 1 : 0,
				default: frm.doc.closing_notes,
			},
		],
		(values) =>
			frappe
				.xcall(`${NC_METHOD}.close_case`, { name: frm.doc.name, outcome, notes: values.notes })
				.then(() => frm.reload_doc()),
		outcome === "Remediated" ? __("Close as Remediated") : __("Close - No Further Action"),
		__("Close")
	);
}

// Submit stays hidden until it can succeed (signed copy attached, or a case
// closed through Actions), replacing Frappe's "Submit this document" prompt.
function hold_submit(frm, ready) {
	if (frm.doc.docstatus !== 0 || frm.is_new() || frm.is_dirty() || ready) return;
	frm.page.clear_primary_action();
	frm.dashboard.clear_comment();
}
