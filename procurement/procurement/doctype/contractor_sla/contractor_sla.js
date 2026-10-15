// Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

const SLA_METHOD = "procurement.procurement.doctype.contractor_sla.contractor_sla";

frappe.ui.form.on("Contractor SLA", {
	setup(frm) {
		frm.set_query("sla_template", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("responsible_manager", () => ({ filters: { enabled: 1, user_type: "System User" } }));
		frm.set_query("clause_options", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		frappe.require("sla_agreement.bundle.css");
		show_agreement(frm);
		hold_submit(frm, frm.doc.signed_copy && frm.doc.contractor_signed_on && frm.doc.company_signed_on);
		add_status_comment(frm);

		add_signature_buttons(frm);

		if (frm.doc.docstatus !== 1 || ["Terminated", "Cancelled"].includes(frm.doc.status)) return;
		if (!frm.doc.renewed_by && frappe.model.can_create("Contractor SLA")) {
			frm.add_custom_button(__("Renew"), () =>
				frappe.model.open_mapped_doc({ method: `${SLA_METHOD}.make_renewal`, frm })
			);
		}
		if (frappe.model.can_create("Contractor Non-Conformance")) {
			frm.add_custom_button(
				__("Record Non-Conformance"),
				() => frappe.model.open_mapped_doc({ method: `${SLA_METHOD}.make_non_conformance`, frm }),
				__("Performance")
			);
		}
		if (frappe.model.can_create("Contractor SLA Termination")) {
			frm.add_custom_button(
				__("Terminate"),
				() => frappe.model.open_mapped_doc({ method: `${SLA_METHOD}.make_termination`, frm }),
				__("Performance")
			);
		}
	},

	sla_template(frm) {
		if (!frm.doc.sla_template || (frm.doc.penalties || []).length) return refresh_agreement(frm);
		frappe.xcall(`${SLA_METHOD}.get_template_defaults`, { sla_template: frm.doc.sla_template }).then((r) => {
			frm.clear_table("penalties");
			r.penalties.forEach((row) => frm.add_child("penalties", row));
			frm.refresh_field("penalties");
			refresh_agreement(frm);
		});
	},

	company(frm) {
		fill_party(frm, "company");
	},

	supplier(frm) {
		fill_party(frm, "supplier");
	},

	branch(frm) {
		if (frm.doc.branch && !frm.doc.operation_name) frm.set_value("operation_name", frm.doc.branch);
	},

	duration_basis: refresh_agreement,
	start_date: refresh_agreement,
	end_date: refresh_agreement,
});

frappe.ui.form.on("Contractor SLA Rate", {
	qty: calculate_rate,
	rate: calculate_rate,
	rates_remove(frm) {
		set_total(frm);
	},
});

function calculate_rate(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.qty) * flt(row.rate));
	set_total(frm);
}

function set_total(frm) {
	frm.set_value(
		"total_monthly_value",
		(frm.doc.rates || []).reduce((total, row) => total + flt(row.amount), 0)
	);
}

// Party details come from the last SLA with that party (or its master record);
// only blanks are filled, so typed details survive a party change.
function fill_party(frm, party_type) {
	const party = frm.doc[party_type];
	if (!party || frm.doc.docstatus !== 0) return;
	frappe
		.xcall(`${SLA_METHOD}.get_party_defaults`, {
			party_type,
			party,
			exclude: frm.is_new() ? null : frm.doc.name,
		})
		.then((values) => {
			Object.entries(values).forEach(([fieldname, value]) => {
				if (!frm.doc[fieldname]) frm.set_value(fieldname, value);
			});
		});
}

// Drafts show the wording as it would render now (unsaved changes included);
// once issued for signature, the frozen wording that went out.
function show_agreement(frm) {
	const $field = frm.fields_dict.agreement_preview.$wrapper;
	if (frm.doc.docstatus !== 0 || frm.doc.sent_for_signature_on) {
		$field.html(`<div class="sla-agreement-preview">${frm.doc.rendered_agreement || ""}</div>`);
		return;
	}
	refresh_agreement(frm);
}

function refresh_agreement(frm) {
	frm.__sla_render = frm.__sla_render || frappe.utils.debounce(render_agreement, 500);
	frm.__sla_render(frm);
}

function render_agreement(frm) {
	const $field = frm.fields_dict.agreement_preview && frm.fields_dict.agreement_preview.$wrapper;
	if (!$field || frm.doc.docstatus !== 0 || frm.doc.sent_for_signature_on) return;
	if (!frm.doc.sla_template) {
		$field.html(`<p class="text-muted">${__("Choose an SLA Template to see the agreement wording.")}</p>`);
		return;
	}
	frappe.xcall(`${SLA_METHOD}.render_preview`, { doc: frm.doc }).then((html) => {
		$field.html(
			`<p class="text-muted small">${__(
				"Live preview: saving re-renders it; submitting freezes it for signature. Blank lines show values still to fill in."
			)}</p><div class="sla-agreement-preview">${html}</div>`
		);
	});
}

function add_status_comment(frm) {
	const doc = frm.doc;
	if (doc.status === "Draft" && !frm.is_new()) {
		frm.dashboard.add_comment(
			__("When the terms are final, use Issue for Signature, print the agreement and have both parties sign it."),
			"blue",
			true
		);
		return;
	}
	if (doc.status === "Outstanding" && !(doc.signed_copy && doc.contractor_signed_on && doc.company_signed_on)) {
		const days = frappe.datetime.get_day_diff(frappe.datetime.get_today(), doc.sent_for_signature_on);
		frm.dashboard.add_comment(
			__(
				"Issued for signature {0} days ago ({1}). Record both signature dates and attach the signed copy on the Signatures tab, then Submit. To change the terms, Withdraw from Signature first.",
				[days, __(doc.signature_status)]
			),
			"orange",
			true
		);
		return;
	}
	if (doc.docstatus !== 1) return;
	if (doc.status === "Expiring Soon") {
		const days = frappe.datetime.get_day_diff(doc.end_date, frappe.datetime.get_today());
		frm.dashboard.add_comment(
			__("Expires in {0} days, on {1}. Use Renew to draft its successor.", [
				days,
				frappe.datetime.str_to_user(doc.end_date),
			]),
			"orange",
			true
		);
	} else if (doc.status === "Expired") {
		frm.dashboard.add_comment(__("This SLA has expired and was not renewed."), "red", true);
	} else if (doc.status === "Terminated") {
		frm.dashboard.add_comment(
			__("Terminated on {0}: {1}", [frappe.datetime.str_to_user(doc.terminated_on), doc.termination_reason]),
			"red",
			true
		);
	}
	if (doc.renewed_by) {
		frm.dashboard.add_comment(
			__("Renewed by {0}.", [`<a href="/desk/contractor-sla/${doc.renewed_by}">${doc.renewed_by}</a>`]),
			"green",
			true
		);
	}
}

function add_signature_buttons(frm) {
	if (frm.doc.docstatus !== 0 || frm.is_new() || !frappe.model.can_write("Contractor SLA")) return;
	const call = (method, message) =>
		frappe
			.xcall(`${SLA_METHOD}.${method}`, { name: frm.doc.name })
			.then(() => frm.reload_doc())
			.then(() => frappe.show_alert({ message, indicator: "green" }));
	if (!frm.doc.sent_for_signature_on) {
		frm.add_custom_button(__("Issue for Signature"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the SLA first."));
				return;
			}
			frappe.confirm(
				__("Freeze the agreement wording for signature? Terms that change the wording can then only be edited after withdrawing it."),
				() => call("issue_for_signature", __("Issued for signature"))
			);
		});
	} else {
		frm.add_custom_button(__("Withdraw from Signature"), () =>
			frappe.confirm(
				__("Withdraw this SLA from signature? Any copy already sent out should be treated as void."),
				() => call("withdraw_from_signature", __("Withdrawn from signature"))
			)
		);
	}
}

// Submit stays hidden until it can succeed (signed copy attached, or a case
// closed through Actions), replacing Frappe's "Submit this document" prompt.
function hold_submit(frm, ready) {
	if (frm.doc.docstatus !== 0 || frm.is_new() || frm.is_dirty() || ready) return;
	frm.page.clear_primary_action();
	frm.dashboard.clear_comment();
}
