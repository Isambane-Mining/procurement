// Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

const SLT_METHOD = "procurement.procurement.doctype.contractor_sla_termination.contractor_sla_termination";

frappe.ui.form.on("Contractor SLA Termination", {
	setup(frm) {
		frm.set_query("contractor_sla", () => ({
			filters: { docstatus: 1, status: ["not in", ["Terminated", "Cancelled"]] },
		}));
		frm.set_query("non_conformance", () => ({
			filters: { contractor_sla: frm.doc.contractor_sla, docstatus: 0 },
		}));
	},

	refresh(frm) {
		set_grounds(frm);
		hold_submit(frm, frm.doc.signed_notice);
		if (frm.doc.docstatus === 0 && !frm.is_new() && !frm.doc.signed_notice) {
			frm.dashboard.add_comment(
				__(
					"Print the notice, have it signed and delivered, attach it and Submit. Submitting marks the SLA as Terminated and stops its notices."
				),
				"orange",
				true
			);
		}
	},

	initiated_by(frm) {
		set_grounds(frm, true);
	},

	notice_date: set_notice_days,
	effective_date: set_notice_days,
});

// Only the grounds open to whoever is terminating.
function set_grounds(frm, reset) {
	if (frm.doc.docstatus !== 0) return;
	frappe.xcall(`${SLT_METHOD}.get_grounds`, { initiated_by: frm.doc.initiated_by }).then((grounds) => {
		frm.set_df_property("termination_ground", "options", ["", ...grounds]);
		if (reset && !grounds.includes(frm.doc.termination_ground)) frm.set_value("termination_ground", "");
	});
}

function set_notice_days(frm) {
	if (frm.doc.notice_date && frm.doc.effective_date) {
		frm.set_value("notice_days", frappe.datetime.get_day_diff(frm.doc.effective_date, frm.doc.notice_date));
	}
}

// Submit stays hidden until it can succeed (signed copy attached, or a case
// closed through Actions), replacing Frappe's "Submit this document" prompt.
function hold_submit(frm, ready) {
	if (frm.doc.docstatus !== 0 || frm.is_new() || frm.is_dirty() || ready) return;
	frm.page.clear_primary_action();
	frm.dashboard.clear_comment();
}
