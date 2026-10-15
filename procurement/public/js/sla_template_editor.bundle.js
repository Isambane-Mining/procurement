// Copyright (c) 2026, BuFf0k and contributors
// For license information, please see license.txt

// Contractor SLA Template wording editor (adapted from ir's Contract of
// Employment Template editor).
//
// A deliberately small Quill instance: Annexure (part break) / Heading /
// numbered Clause (any depth) / unnumbered Text lines, bold-italic-underline,
// variable chips (block variables such as {{penalties_table}} sit on their own
// line), clause cross-references, and per-line "Show when" (a condition decided
// per SLA) and "Repeat for each" (one sub-paragraph per service, rate ...).
// Stored as a Quill Delta in `sla_wording`; the server side
// (procurement/procurement/sla_wording.py) owns validation and numbering, and
// the CSS counters below follow the same rule so the editor shows the real numbers.
//
// This bundle imports its own Quill so the formats registered here (deeper
// indents, single heading level, our embeds) never leak into desk's Text
// Editor fields.

import Quill from "quill";

const Parchment = Quill.import("parchment");
const Embed = Quill.import("blots/embed");
const Header = Quill.import("formats/header");

const VAR_EMBED = "sla-var";
const REF_EMBED = "sla-ref";
const ANCHOR_ATTR = "sla-anchor";
const WHEN_ATTR = "sla-when";
const REPEAT_ATTR = "sla-repeat";
const INLINE = ["bold", "italic", "underline"];
const FORMATS = [
	"header",
	"list",
	"indent",
	"bold",
	"italic",
	"underline",
	VAR_EMBED,
	REF_EMBED,
	ANCHOR_ATTR,
	WHEN_ATTR,
	REPEAT_ATTR,
];

let registered_max_indent = null;
const variable_labels = {};
const block_variables = new Set();

function register_formats(max_indent) {
	if (registered_max_indent !== null) return;
	registered_max_indent = max_indent;

	// Two heading levels: H1 is a numbered section, H2 an Annexure title that
	// restarts the numbering.
	class SectionHeading extends Header {
		static create(value) {
			return super.create(Number(value) === 2 ? 2 : 1);
		}
	}
	SectionHeading.tagName = ["H1", "H2"];
	Quill.register(SectionHeading, true);

	// Quill ships indent 1..8; clauses may nest as deep as the server allows.
	const StockIndent = Quill.import("formats/indent");
	const Indent = new StockIndent.constructor("indent", "ql-indent", {
		scope: Parchment.Scope.BLOCK,
		whitelist: Array.from({ length: max_indent }, (_, i) => i + 1),
	});
	Quill.register(Indent, true);

	// Stable id on a heading/clause, so references survive renumbering.
	const Anchor = new Parchment.Attributor(ANCHOR_ATTR, "data-anchor", { scope: Parchment.Scope.BLOCK });
	Quill.register(Anchor, true);

	// "Show when" condition (e.g. duration:fixed); Enter carries it to the next line.
	const When = new Parchment.Attributor(WHEN_ATTR, "data-when", { scope: Parchment.Scope.BLOCK });
	Quill.register(When, true);

	// Repeat kind (services, milestones, rates, equipment, special_terms): one line per row.
	const Repeat = new Parchment.Attributor(REPEAT_ATTR, "data-repeat", { scope: Parchment.Scope.BLOCK });
	Quill.register(Repeat, true);

	class VariableBlot extends Embed {
		static create(key) {
			const node = super.create(key);
			node.setAttribute("data-var", key);
			if (block_variables.has(key)) node.classList.add("sla-var-block");
			node.textContent = variable_labels[key] || key;
			return node;
		}
		static value(node) {
			return node.getAttribute("data-var");
		}
	}
	VariableBlot.blotName = VAR_EMBED;
	VariableBlot.tagName = "SPAN";
	VariableBlot.className = "sla-var";
	Quill.register(VariableBlot, true);

	class ReferenceBlot extends Embed {
		static create(value) {
			const node = super.create(value);
			node.setAttribute("data-anchor-ref", value.anchor || "");
			node.setAttribute("data-label", value.label || "");
			node.textContent = `§ ${value.label || "?"}`;
			return node;
		}
		static value(node) {
			return { anchor: node.getAttribute("data-anchor-ref"), label: node.getAttribute("data-label") };
		}
	}
	ReferenceBlot.blotName = REF_EMBED;
	ReferenceBlot.tagName = "SPAN";
	ReferenceBlot.className = "sla-ref";
	Quill.register(ReferenceBlot, true);

	inject_styles(max_indent);
}

// ---- numbering (CSS counters; same rule as number_lines() in sla_wording.py) ----

function inject_styles(max_indent) {
	if (document.getElementById("sla-template-editor-styles")) return;
	const levels = max_indent + 1; // clause level k uses counter sla-(k+1)
	const counter = (n) => `sla-${n}`;
	const clear_from = (n) =>
		Array.from({ length: levels - n + 1 }, (_, i) => `${counter(n + i)} 0`).join(" ") || "none";
	const number_for = (k) =>
		Array.from({ length: k + 2 }, (_, i) => `counter(${counter(i)})`).join(' "." ') + ' "."';
	// Text starts after the widest number at that depth.
	const text_offset = (k) => `${k * 1.5 + 2 + (k + 2) * 1.1}em`;
	const root = ".sla-template-editor .ql-editor";

	let css = `
		${root} { counter-reset: ${Array.from({ length: levels + 1 }, (_, i) => counter(i)).join(" ")};
			min-height: 420px; font-size: var(--text-base); line-height: 1.6; }
		${root} h1 { counter-increment: ${counter(0)}; counter-set: ${clear_from(1)};
			font-size: var(--text-lg); font-weight: 700; margin: 1em 0 0.35em; position: relative; padding-left: 2.5em; }
		${root} h1::before { content: counter(${counter(0)}) "."; position: absolute; left: 0; }
		${root} h2 { counter-set: ${clear_from(0)}; font-size: var(--text-lg); font-weight: 700; text-align: center;
			margin: 1.5em 0 0.5em; padding-top: 0.75em; border-top: 2px dashed var(--border-color); }
		${root} .sla-var-block { display: inline-block; }
		${root} .sla-var-block > [contenteditable=false] { background: var(--bg-green); color: var(--text-on-green); padding: 2px 8px; }
		${root} li[data-list] { counter-set: none; counter-increment: none; }
		${root} li[data-list] > .ql-ui:before { width: auto; margin: 0; text-align: left; font-weight: 600; }
		${root} li[data-list=bullet] > .ql-ui:before { content: ""; }
		/* Style the chip's inner (non-editable) span only: text typed next to an
		   embed lands in the outer span first, and white-space: nowrap there makes
		   Chrome type U+00A0 instead of a space. */
		${root} .sla-var > [contenteditable=false], ${root} .sla-ref > [contenteditable=false] {
			border-radius: 4px; padding: 0 4px; white-space: nowrap;
			font-size: 0.9em; background: var(--bg-blue); color: var(--text-on-blue); }
		${root} .sla-ref > [contenteditable=false] { background: var(--bg-purple); color: var(--text-on-purple); }
		.sla-template-editor .sla-toolbar { display: flex; flex-wrap: wrap; gap: 4px; align-items: center;
			padding: 6px; border: 1px solid var(--border-color); border-bottom: none;
			border-radius: var(--border-radius) var(--border-radius) 0 0; background: var(--subtle-fg); }
		.sla-template-editor .sla-toolbar .btn.active { background: var(--gray-300); }
		.sla-template-editor .sla-toolbar .sla-edit,
		.sla-template-editor .sla-toolbar .sla-view { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
		.sla-template-editor .sla-toolbar .sla-view { margin-left: auto; }
		.sla-template-editor .sla-toolbar .sla-view select { width: auto; height: 24px; padding: 0 24px 0 6px; }
		.sla-template-editor .sla-toolbar .sla-sep { width: 1px; align-self: stretch; background: var(--border-color); margin: 0 4px; }
		.sla-template-editor .ql-container { border: 1px solid var(--border-color);
			border-radius: 0 0 var(--border-radius) var(--border-radius); font-family: inherit; }
		.sla-picker { position: absolute; z-index: 1050; width: 320px; max-height: 360px; overflow: auto;
			background: var(--fg-color); border: 1px solid var(--border-color); border-radius: var(--border-radius);
			box-shadow: var(--shadow-lg); padding: 6px; }
		.sla-picker input { margin-bottom: 6px; }
		.sla-picker .sla-picker-group { font-size: var(--text-xs); color: var(--text-muted); padding: 6px 6px 2px; text-transform: uppercase; }
		.sla-picker .sla-picker-item { padding: 4px 6px; border-radius: 4px; cursor: pointer; }
		.sla-picker .sla-picker-item:hover, .sla-picker .sla-picker-item.selected { background: var(--subtle-accent); }
		.sla-picker .sla-picker-item small { display: block; color: var(--text-muted); }
		.sla-preview-var { background: var(--bg-blue); color: var(--text-on-blue); border-radius: 4px; padding: 0 3px; }
	`;
	for (let k = 0; k <= max_indent; k++) {
		const sel = k === 0 ? `${root} li[data-list=ordered]` : `${root} li[data-list=ordered].ql-indent-${k}`;
		css += `
			${sel} { counter-increment: ${counter(k + 1)}; counter-set: ${clear_from(k + 2)}; }
			${sel} > .ql-ui:before { content: ${number_for(k)}; }
		`;
		const indented = k === 0 ? "" : `.ql-indent-${k}`;
		css += `
			${root} li${indented}:not(.ql-direction-rtl) { padding-left: ${text_offset(k)}; }
			${root} li${indented} > .ql-ui { left: ${k * 1.5}em; }
			${root} p${indented}:not(.ql-direction-rtl) { padding-left: ${k === 0 ? 0 : text_offset(k)}; }
		`;
	}
	const style = document.createElement("style");
	style.id = "sla-template-editor-styles";
	style.textContent = css;
	document.head.appendChild(style);
}

// Badges for "Show when" / "Repeat for each", and the View as hide rules.
// Labels travel in custom properties so one ::after can show both options.
function inject_line_option_styles(conditions, repeats) {
	if (document.getElementById("sla-template-line-option-styles")) return;
	const root = ".sla-template-editor .ql-editor";
	const str = (text) => JSON.stringify(text);
	let css = `
		${root} [data-repeat] { box-shadow: inset 3px 0 0 var(--blue-400); }
		${root} [data-when] { box-shadow: inset 3px 0 0 var(--orange-400); }
		${root} [data-when] { --sla-when: ${str(__("When: {0}", [__("condition")]))}; }
		${root} [data-repeat] { --sla-repeat: ${str(__("Each row"))}; }
		${root} [data-when][data-repeat] { --sla-gap: "  \\00b7  "; }
		${root} [data-when]::after, ${root} [data-repeat]::after {
			content: var(--sla-when, "") var(--sla-gap, "") var(--sla-repeat, "");
			display: inline-block; margin-left: 8px; padding: 0 6px; border-radius: 8px;
			font-size: var(--text-xs); font-weight: 400; background: var(--bg-orange); color: var(--text-on-orange);
			vertical-align: middle; white-space: nowrap; }
		${root} [data-repeat]:not([data-when])::after { background: var(--bg-blue); color: var(--text-on-blue); }
	`;
	conditions.forEach((c) => {
		const key = CSS.escape(c.key);
		css += `${root} [data-when="${key}"] { --sla-when: ${str(__("When: {0}", [c.label]))}; }\n`;
		if (c.exclusive) {
			css += `.sla-template-editor[data-hide~="${key}"] .ql-editor [data-when="${key}"] { display: none; }\n`;
		}
	});
	repeats.forEach((r) => {
		css += `${root} [data-repeat="${CSS.escape(r.key)}"] { --sla-repeat: ${str(__("Each {0}", [r.label]))}; }\n`;
	});
	const style = document.createElement("style");
	style.id = "sla-template-line-option-styles";
	style.textContent = css;
	document.head.appendChild(style);
}

function condition_groups(conditions) {
	const groups = {};
	conditions.forEach((c) => (groups[c.group] = groups[c.group] || []).push(c));
	return groups;
}

// ---- line helpers ----

function line_kind(formats) {
	if (Number(formats.header) === 2) return "part";
	if (formats.header) return "heading";
	if (formats.list === "ordered") return "clause";
	return "text";
}

// Mirrors number_lines() in sla_wording.py; used for the reference picker.
function numbered_lines(quill) {
	const out = [];
	let section = 0;
	let levels = [];
	for (const line of quill.getLines()) {
		const formats = line.formats();
		const kind = line_kind(formats);
		let number = null;
		if (kind === "part") {
			section = 0;
			levels = [];
		} else if (kind === "heading") {
			section += 1;
			levels = [];
			number = String(section);
		} else if (kind === "clause") {
			const k = Number(formats.indent || 0);
			levels = levels.concat(Array(k + 1).fill(0)).slice(0, k + 1);
			levels[k] += 1;
			number = [section, ...levels].join(".");
		}
		out.push({ line, kind, number, anchor: formats[ANCHOR_ATTR] || null, text: line.domNode.innerText.trim() });
	}
	return out;
}

function new_anchor() {
	return "a" + Math.random().toString(36).slice(2, 10);
}

// ---- editor ----

class SLATemplateEditor {
	constructor({ wrapper, config, on_change }) {
		register_formats(config.max_indent);
		inject_line_option_styles(config.conditions || [], config.repeats || []);
		config.variables.forEach((v) => {
			variable_labels[v.key] = v.label;
			if (v.block) block_variables.add(v.key);
		});

		this.config = config;
		this.on_change = on_change;
		this.last_range = null;
		this.read_only = false;
		this.view = {}; // exclusive condition group -> chosen key ("" = show every line)

		this.$wrapper = $(wrapper).empty().addClass("sla-template-editor");
		this.$toolbar = $('<div class="sla-toolbar"></div>').appendTo(this.$wrapper);
		const $editor = $("<div></div>").appendTo(this.$wrapper);

		this.quill = new Quill($editor[0], {
			formats: FORMATS,
			placeholder: __(
				"Start with a Heading, then add numbered Clauses. Tab / Shift+Tab changes clause depth. Annexure starts a new, separately numbered part."
			),
			modules: {
				toolbar: false,
				keyboard: {
					bindings: {
						"list autofill": false,
						indent: false,
						outdent: false,
						tab: {
							key: "Tab",
							shiftKey: null, // Quill only matches Shift+Tab when shiftKey isn't false
							handler: (range, context) => {
								this.shift_depth(context.event && context.event.shiftKey ? -1 : 1);
								return false;
							},
						},
					},
				},
			},
		});

		this.make_toolbar();
		this.quill.on("selection-change", (range) => {
			if (range) this.last_range = range;
			this.refresh_toolbar();
		});
		this.quill.on("text-change", (delta, old, source) => {
			if (source !== "user") return;
			this.dedupe_anchors();
			this.refresh_toolbar();
			this.on_change && this.on_change(this.get_value());
			this.on_after_change && this.on_after_change();
		});
	}

	get_value() {
		return JSON.stringify(this.quill.getContents());
	}

	set_value(value) {
		let delta = { ops: [] };
		if (value) {
			try {
				delta = typeof value === "string" ? JSON.parse(value) : value;
			} catch (e) {
				delta = { ops: [] };
			}
		}
		this.quill.setContents(delta, "silent");
	}

	set_read_only(read_only) {
		this.read_only = read_only;
		this.$toolbar.find(".sla-edit").toggle(!read_only);
		this.$wrapper.toggleClass("read-only", read_only);
		this.apply_view();
	}

	// "View as" hides the other alternatives of each chosen group. Editing is
	// off while filtered: hidden lines could otherwise be deleted unseen.
	apply_view() {
		const hide = (this.config.conditions || [])
			.filter((c) => this.view[c.group] && this.view[c.group] !== c.key)
			.map((c) => c.key);
		this.$wrapper.attr("data-hide", hide.join(" "));
		const filtered = Object.values(this.view).some(Boolean);
		this.quill.enable(!this.read_only && !filtered);
		this.$toolbar.find(".sla-edit button").prop("disabled", filtered);
		this.$toolbar.find(".sla-view-note").toggle(filtered && !this.read_only);
	}

	range() {
		return this.quill.getSelection() || this.last_range || { index: this.quill.getLength() - 1, length: 0 };
	}

	// ---- toolbar ----

	make_toolbar() {
		const $edit = $('<div class="sla-edit"></div>').appendTo(this.$toolbar);
		const button = (label, title, action) =>
			$(`<button type="button" class="btn btn-default btn-xs" title="${title}">${label}</button>`)
				.on("mousedown", (e) => e.preventDefault()) // keep the editor selection
				.on("click", action)
				.appendTo($edit);
		const sep = () => $('<span class="sla-sep"></span>').appendTo($edit);

		this.buttons = {
			part: button(__("Annexure"), __("Annexure title: starts a new page and restarts the numbering"), () =>
				this.set_line_kind("part")
			),
			heading: button(__("Heading"), __("Numbered section heading"), () => this.set_line_kind("heading")),
			clause: button(__("Clause"), __("Numbered clause"), () => this.set_line_kind("clause")),
			text: button(__("Text"), __("Unnumbered text"), () => this.set_line_kind("text")),
		};
		sep();
		button(frappe.utils.icon("list-indent-decrease", "sm"), __("Up a level (Shift+Tab)"), () => this.shift_depth(-1));
		button(frappe.utils.icon("list-indent-increase", "sm"), __("Down a level (Tab)"), () => this.shift_depth(1));
		sep();
		Object.assign(this.buttons, {
			bold: button("<b>B</b>", __("Bold (Ctrl+B)"), () => this.toggle_inline("bold")),
			italic: button("<i>I</i>", __("Italic (Ctrl+I)"), () => this.toggle_inline("italic")),
			underline: button("<u>U</u>", __("Underline (Ctrl+U)"), () => this.toggle_inline("underline")),
		});
		sep();
		const $var = button(__("Insert Variable"), __("Insert an SLA variable"), () => this.open_variable_picker($var));
		const $ref = button(__("Insert Reference"), __("Insert the number of another heading or clause"), () =>
			this.open_reference_picker($ref)
		);
		sep();
		this.$show = button(__("Show: Always"), __("Show the selected lines only in SLAs where a condition holds"), () =>
			this.open_condition_picker(this.$show)
		);
		this.$repeat = button(__("Repeat: Off"), __("Write the selected line once per service, milestone, rate, equipment row or special term"), () =>
			this.open_repeat_picker(this.$repeat)
		);
		this.make_view_switch();
	}

	make_view_switch() {
		const $view = $('<div class="sla-view"></div>').appendTo(this.$toolbar);
		$(`<span class="text-muted small">${__("View as")}</span>`).appendTo($view);
		const exclusive = (this.config.conditions || []).filter((c) => c.exclusive);
		Object.entries(condition_groups(exclusive)).forEach(([group, conditions]) => {
			const $select = $('<select class="form-control input-xs"></select>').appendTo($view);
			$select.append($("<option></option>").val("").text(__("{0}: all lines", [group])));
			conditions.forEach((c) => $select.append($("<option></option>").val(c.key).text(c.label)));
			$select.on("change", () => {
				this.view[group] = $select.val();
				this.apply_view();
			});
		});
		$(`<span class="sla-view-note text-muted small">${__("Viewing only - choose all lines to edit")}</span>`)
			.hide()
			.appendTo($view);
	}

	open_condition_picker($anchor) {
		const items = [
			{ group: __("Every SLA") },
			{ label: __("Always"), search: `${__("Always")} all every none`, pick: () => this.set_condition(false) },
		];
		Object.entries(condition_groups(this.config.conditions)).forEach(([group, conditions]) => {
			items.push({ group });
			conditions.forEach((c) =>
				items.push({
					label: __("When: {0}", [c.label]),
					hint: c.description,
					search: `${c.label} ${group}`,
					pick: () => this.set_condition(c.key),
				})
			);
		});
		this.open_picker($anchor, items, __("Search conditions"));
	}

	set_condition(key) {
		const { index, length } = this.range();
		this.quill.formatLine(index, length, WHEN_ATTR, key || false, "user");
		this.refresh_toolbar();
	}

	open_repeat_picker($anchor) {
		const items = [
			{ group: __("Written once") },
			{ label: __("Off"), search: `${__("Off")} once none`, pick: () => this.set_repeat(false) },
			{ group: __("One line per row") },
			...(this.config.repeats || []).map((r) => ({
				label: __("Each {0}", [r.label]),
				hint: r.description,
				search: `${r.label} ${r.key}`,
				pick: () => this.set_repeat(r.key),
			})),
		];
		this.open_picker($anchor, items, __("Search repeats"));
	}

	set_repeat(key) {
		const { index, length } = this.range();
		this.quill.formatLine(index, length, REPEAT_ATTR, key || false, "user");
		this.refresh_toolbar();
	}

	refresh_toolbar() {
		if (!this.buttons) return;
		const range = this.quill.getSelection();
		const formats = range ? this.quill.getFormat(range) : {};
		const kind = line_kind(formats);
		["part", "heading", "clause", "text"].forEach((k) =>
			this.buttons[k].toggleClass("active", range != null && kind === k)
		);
		INLINE.forEach((f) => this.buttons[f].toggleClass("active", !!formats[f]));
		const when = formats[WHEN_ATTR];
		const condition = (this.config.conditions || []).find((c) => c.key === when);
		this.$show.text(when ? __("Show: When {0}", [condition ? condition.label : when]) : __("Show: Always"));
		this.$show.toggleClass("active", !!when);
		const repeat = (this.config.repeats || []).find((r) => r.key === formats[REPEAT_ATTR]);
		this.$repeat.text(repeat ? __("Repeat: Each {0}", [repeat.label]) : __("Repeat: Off"));
		this.$repeat.toggleClass("active", !!repeat);
	}

	set_line_kind(kind) {
		const { index, length } = this.range();
		if (kind === "part") {
			this.quill.formatLine(index, length, { header: 2, list: false, indent: false }, "user");
		} else if (kind === "heading") {
			this.quill.formatLine(index, length, { header: 1, indent: false }, "user");
		} else if (kind === "clause") {
			this.quill.formatLine(index, length, { list: "ordered" }, "user");
		} else {
			this.quill.formatLine(index, length, { header: false, list: false }, "user");
		}
		this.quill.setSelection(index, length, "silent");
	}

	shift_depth(step) {
		const { index, length } = this.range();
		this.quill.getLines(index, length || 1).forEach((line) => {
			const formats = line.formats();
			if (formats.header) return;
			const current = Number(formats.indent || 0);
			const next = Math.max(0, Math.min(current + step, this.config.max_indent));
			if (next !== current) {
				this.quill.formatLine(this.quill.getIndex(line), 1, "indent", next || false, "user");
			}
		});
	}

	toggle_inline(format) {
		const range = this.range();
		const current = this.quill.getFormat(range)[format];
		this.quill.format(format, !current, "user");
		this.refresh_toolbar();
	}

	// ---- variables ----

	// Block variables (tables, signature blocks) get an unnumbered line of their own.
	insert_block_variable(variable) {
		let { index } = this.range();
		const [, offset] = this.quill.getLine(index);
		if (offset > 0) {
			this.quill.insertText(index, "\n", "user");
			index += 1;
		}
		const [line] = this.quill.getLine(index);
		if (line && line.length() > 1) this.quill.insertText(index, "\n", "user");
		this.quill.formatLine(index, 1, { header: false, list: false, indent: false, [REPEAT_ATTR]: false }, "user");
		this.quill.insertEmbed(index, VAR_EMBED, variable.key, "user");
		this.quill.setSelection(index + 1, 0, "user");
		this.refresh_toolbar();
	}

	insert_variable(variable) {
		if (variable.block) return this.insert_block_variable(variable);
		const { index } = this.range();
		this.quill.insertEmbed(index, VAR_EMBED, variable.key, "user");
		if (variable.repeat) {
			// Row values only exist on a repeating line: make this line repeat.
			this.quill.formatLine(index, 1, REPEAT_ATTR, variable.repeat, "user");
		}
		this.quill.setSelection(index + 1, 0, "user");
		this.refresh_toolbar();
	}

	open_variable_picker($anchor) {
		const groups = {};
		this.config.variables.forEach((v) => (groups[v.group] = groups[v.group] || []).push(v));
		const items = [];
		Object.entries(groups).forEach(([group, vars]) => {
			items.push({ group });
			vars.forEach((v) =>
				items.push({
					label: v.label,
					hint: v.block
						? __("Inserted on a line of its own. {0}", [v.description || ""])
						: v.repeat
						? __("Sets the line to Repeat for each {0}. {1}", [
								((this.config.repeats || []).find((r) => r.key === v.repeat) || {}).label || v.repeat,
								v.description || "",
						  ])
						: v.description,
					search: `${v.label} ${v.key} ${group}`,
					pick: () => this.insert_variable(v),
				})
			);
		});
		this.open_picker($anchor, items, __("Search variables"));
	}

	// ---- references ----

	insert_reference(target) {
		let anchor = target.anchor;
		if (!anchor) {
			anchor = new_anchor();
			this.quill.formatLine(this.quill.getIndex(target.line), 1, ANCHOR_ATTR, anchor, "user");
		}
		const label = target.kind === "heading" ? target.text : `${target.number} ${target.text}`;
		const { index } = this.range();
		this.quill.insertEmbed(index, REF_EMBED, { anchor, label: label.slice(0, 60) }, "user");
		this.quill.setSelection(index + 1, 0, "user");
	}

	open_reference_picker($anchor) {
		const targets = numbered_lines(this.quill).filter((l) => l.number);
		if (!targets.length) {
			frappe.show_alert({ message: __("Add a Heading or Clause first."), indicator: "orange" });
			return;
		}
		const items = targets.map((t) => ({
			label: `${t.number}  ${t.text || __("(empty)")}`.slice(0, 90),
			search: `${t.number} ${t.text}`,
			pick: () => this.insert_reference(t),
		}));
		this.open_picker($anchor, items, __("Search headings and clauses"));
	}

	// Enter on a heading/clause copies its line formats (anchor included) to
	// the new line; the anchor belongs to the first one.
	dedupe_anchors() {
		const seen = new Set();
		for (const line of this.quill.getLines()) {
			const anchor = line.formats()[ANCHOR_ATTR];
			if (!anchor) continue;
			if (seen.has(anchor)) {
				this.quill.formatLine(this.quill.getIndex(line), 1, ANCHOR_ATTR, false, "silent");
			} else {
				seen.add(anchor);
			}
		}
	}

	// ---- shared picker popover ----

	open_picker($anchor, items, placeholder) {
		this.close_picker();
		const $picker = $(`<div class="sla-picker">
			<input type="text" class="form-control input-xs" placeholder="${placeholder}">
			<div class="sla-picker-list"></div>
		</div>`).appendTo(document.body);
		const offset = $anchor.offset();
		$picker.css({ top: offset.top + $anchor.outerHeight() + 4, left: offset.left });

		const $list = $picker.find(".sla-picker-list");
		let visible = [];
		let selected = 0;
		const render = (term) => {
			term = (term || "").toLowerCase();
			$list.empty();
			visible = [];
			let pending_group = null;
			items.forEach((item) => {
				if (item.group) {
					pending_group = item.group;
					return;
				}
				if (term && !item.search.toLowerCase().includes(term)) return;
				if (pending_group) {
					$(`<div class="sla-picker-group"></div>`).text(pending_group).appendTo($list);
					pending_group = null;
				}
				const $item = $('<div class="sla-picker-item"></div>').text(item.label).appendTo($list);
				if (item.hint) $("<small></small>").text(item.hint).appendTo($item);
				const i = visible.length;
				$item.on("mousedown", (e) => {
					e.preventDefault();
					this.choose(visible[i]);
				});
				visible.push({ item, $item });
			});
			selected = 0;
			highlight();
		};
		const highlight = () => visible.forEach((v, i) => v.$item.toggleClass("selected", i === selected));

		const $input = $picker.find("input");
		$input.on("input", () => render($input.val()));
		$input.on("keydown", (e) => {
			if (e.key === "ArrowDown" || e.key === "ArrowUp") {
				selected = Math.max(0, Math.min(visible.length - 1, selected + (e.key === "ArrowDown" ? 1 : -1)));
				highlight();
				visible[selected] && visible[selected].$item[0].scrollIntoView({ block: "nearest" });
				e.preventDefault();
			} else if (e.key === "Enter") {
				visible[selected] && this.choose(visible[selected]);
				e.preventDefault();
			} else if (e.key === "Escape") {
				this.close_picker();
				this.quill.focus();
			}
		});
		render("");
		$input.trigger("focus");

		this.$picker = $picker;
		setTimeout(() => {
			$(document).on("mousedown.sla-picker", (e) => {
				if (!$(e.target).closest(".sla-picker").length) this.close_picker();
			});
		});
	}

	choose(entry) {
		this.close_picker();
		this.quill.focus();
		entry.item.pick();
	}

	close_picker() {
		$(document).off("mousedown.sla-picker");
		this.$picker && this.$picker.remove();
		this.$picker = null;
	}
}

// ---- form glue ----

let config_promise = null;

function get_config() {
	if (!config_promise) {
		config_promise = frappe
			.xcall(
				"procurement.procurement.doctype.contractor_sla_template.contractor_sla_template.get_editor_config"
			)
			.catch((e) => {
				config_promise = null;
				throw e;
			});
	}
	return config_promise;
}

async function attach(frm, { html_field = "text_editor", value_field = "sla_wording" } = {}) {
	const config = await get_config();
	const field = frm.fields_dict[html_field];
	if (!field) return;

	let editor = frm.__sla_editor;
	if (!editor || !document.body.contains(editor.$wrapper[0]) || editor.$wrapper[0] !== field.$wrapper[0]) {
		editor = frm.__sla_editor = new SLATemplateEditor({
			wrapper: field.$wrapper,
			config,
			on_change: (value) => {
				editor.last_synced = value;
				frm.set_value(value_field, value);
			},
		});
		editor.doc_name = null;
	}

	// Reload content on a different document or a server-side change (save
	// re-cleans the wording); leave it alone while it's the user's own edit.
	const value = frm.doc[value_field] || "";
	if (editor.doc_name !== frm.doc.name || !same_content(value, editor.last_synced)) {
		editor.set_value(value);
		editor.last_synced = value;
		editor.doc_name = frm.doc.name;
	}
	editor.set_read_only(frm.doc.docstatus !== 0 || !frappe.model.can_write(frm.doctype, frm.docname));
	return editor;
}

function same_content(a, b) {
	if (a === b) return true;
	try {
		return JSON.stringify(JSON.parse(a || "{}")) === JSON.stringify(JSON.parse(b || "{}"));
	} catch (e) {
		return false;
	}
}

frappe.provide("procurement.sla_template_editor");
Object.assign(procurement.sla_template_editor, { attach, SLATemplateEditor });
