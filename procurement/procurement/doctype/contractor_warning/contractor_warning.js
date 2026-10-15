// Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Contractor Warning", {
	setup(frm) {
		frm.set_query("non_conformance", () => ({ filters: { docstatus: 0 } }));
		frm.set_query("warning_level", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		hold_submit(frm, frm.doc.signed_acknowledgement);
		if (frm.doc.docstatus === 0 && !frm.is_new() && !frm.doc.signed_acknowledgement) {
			frm.dashboard.add_comment(
				__(
					"Print the warning, have the contractor sign it (or keep proof of delivery), attach it under Acknowledgement and Submit."
				),
				"blue",
				true
			);
		}
	},
});

// Submit stays hidden until it can succeed (signed copy attached, or a case
// closed through Actions), replacing Frappe's "Submit this document" prompt.
function hold_submit(frm, ready) {
	if (frm.doc.docstatus !== 0 || frm.is_new() || frm.is_dirty() || ready) return;
	frm.page.clear_primary_action();
	frm.dashboard.clear_comment();
}
