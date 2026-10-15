// Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

const SLA_TEMPLATE_METHOD = "procurement.procurement.doctype.contractor_sla_template.contractor_sla_template";

frappe.ui.form.on("Contractor SLA Template", {
	async refresh(frm) {
		await frappe.require(["sla_template_editor.bundle.js", "sla_agreement.bundle.css"]);
		const editor = await procurement.sla_template_editor.attach(frm);
		editor.on_after_change = frappe.utils.debounce(() => sync_markdown_from_editor(frm), 600);

		frm.add_custom_button(__("Preview"), () => show_preview(frm, editor.config));
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("New SLA"), () =>
				frappe.new_doc("Contractor SLA", { sla_template: frm.doc.name })
			);
		}
	},

	// Markdown tab -> editor, unless this change is the editor's own echo.
	sla_markdown: frappe.utils.debounce((frm) => {
		const markdown = frm.doc.sla_markdown || "";
		if (markdown === frm.__sla_markdown_from_editor || frm.doc.docstatus !== 0) return;
		frappe
			.xcall(`${SLA_TEMPLATE_METHOD}.markdown_to_wording`, { sla_markdown: markdown })
			.then(({ sla_wording, errors }) => {
				const editor = frm.__sla_editor;
				if (editor) {
					editor.set_value(sla_wording);
					editor.last_synced = sla_wording;
				}
				frm.set_value("sla_wording", sla_wording);
				frm.dashboard.clear_comment();
				if (errors.length) {
					frm.dashboard.add_comment(errors.join("<br>"), "orange", true);
				}
			});
	}, 800),
});

function sync_markdown_from_editor(frm) {
	frappe
		.xcall(`${SLA_TEMPLATE_METHOD}.wording_to_markdown`, { sla_wording: frm.doc.sla_wording })
		.then((markdown) => {
			frm.__sla_markdown_from_editor = markdown;
			if (markdown !== frm.doc.sla_markdown) frm.set_value("sla_markdown", markdown);
		});
}

// One sample SLA at a time: placeholders for every value, two rows per table,
// and the duration basis / optional parts / clause options it has.
function show_preview(frm, config) {
	const options = (config.conditions || [])
		.filter((c) => c.key.startsWith("option:"))
		.map((c) => c.key.slice("option:".length));
	const yes_no = (fieldname, label) => ({
		fieldtype: "Select",
		fieldname,
		label,
		options: [
			{ value: "yes", label: __("Yes") },
			{ value: "no", label: __("No") },
		],
		default: "yes",
	});

	const dialog = new frappe.ui.Dialog({
		title: __("Preview: {0}", [frm.doc.template_name || __("New Template")]),
		size: "extra-large",
		fields: [
			{
				fieldtype: "Select",
				fieldname: "duration_basis",
				label: __("Duration"),
				options: [
					{ value: "fixed", label: __("Fixed term") },
					{ value: "project", label: __("Project based") },
				],
				default: "fixed",
			},
			yes_no("equipment", __("Has Equipment")),
			{ fieldtype: "Column Break" },
			yes_no("milestones", __("Has Milestones")),
			yes_no("penalties", __("Has Penalties")),
			{ fieldtype: "Column Break" },
			yes_no("special_terms", __("Has Special Terms")),
			{
				fieldtype: "MultiSelectList",
				fieldname: "options",
				label: __("Clause Options"),
				get_data: (txt) =>
					options
						.filter((o) => !txt || o.toLowerCase().includes(txt.toLowerCase()))
						.map((o) => ({ value: o, description: "" })),
				default: options,
			},
			{ fieldtype: "Section Break" },
			{ fieldtype: "HTML", fieldname: "preview" },
		],
	});

	const render = frappe.utils.debounce(() => {
		frappe
			.xcall(`${SLA_TEMPLATE_METHOD}.preview_wording`, {
				sla_wording: frm.doc.sla_wording,
				scenario: dialog.get_values(true),
			})
			.then((html) => dialog.fields_dict.preview.$wrapper.html(`<div class="sla-preview">${html}</div>`));
	}, 300);
	Object.values(dialog.fields_dict).forEach((field) => {
		if (field.df.fieldname !== "preview") field.df.onchange = render;
	});
	dialog.show();
	render();
}
