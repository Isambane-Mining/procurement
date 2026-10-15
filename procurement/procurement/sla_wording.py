# Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
# For license information, please see license.txt

"""Contractor SLA wording engine: template lines, dynamic clauses and rendering.

Adapted from ir's Contract of Employment Template engine, with the SLA's own
variables, conditions and repeats, plus two additions an SLA needs:

- part:  an unnumbered title such as "ANNEXURE A" that starts a new page and
         restarts the section numbering (the annexure is numbered 1, 2, 3 ...)
- block variables ({{equipment_table}}, {{penalties_table}}, {{rates_table}},
         {{signature_block}}): a whole table, on its own unnumbered line

Storage
-------
The template editor (procurement/public/js/sla_template_editor.bundle.js)
stores the wording in `sla_wording` as a Quill Delta ({"ops": [...]}); the
Markdown tab (`sla_markdown`) is the same content in SLA Markdown, kept in step
on every save. Every line is one of:

- part:    Quill header 2 - unnumbered title, resets numbering
- heading: Quill header 1 - a numbered section heading (1, 2, 3 ...)
- clause:  a numbered clause; its indent (0..MAX_INDENT) is its depth below
           the heading, so indent 0 -> 4.1, indent 1 -> 4.1.1, and so on
- text:    unnumbered wording; never affects numbering

Inline content is text (bold/italic/underline only), variables
({"sla-var": key}) and cross-references ({"sla-ref": {"anchor", "label"}})
that resolve to the number of the heading/clause carrying that anchor.

Dynamic clauses
---------------
Each line can carry, independently:

- Show when ({"sla-when": key}): the line appears only in SLAs where that
  condition holds - e.g. "duration:fixed", "equipment:any" or a Clause Option
  the SLA ticks ("option:Diesel Supplied by Company").
- Repeat for each ({"sla-repeat": kind}): the line is written once per row of
  that kind (each service, milestone, rate, equipment row or special term).

Hidden lines are dropped and repeats expanded before numbering, so the
numbers always close up.

Numbering rule (shared with the editor's CSS counters, keep them in step):
a part resets everything; a heading increments the section number and clears
every clause level; a clause at indent k increments level k and clears every
level below it; text lines change nothing. Rendered numbers carry a trailing
dot ("4.1."), references don't ("see 4.1").
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

MAX_INDENT = 8
INLINE_FORMATS = ("bold", "italic", "underline")
VAR_EMBED = "sla-var"
REF_EMBED = "sla-ref"
ANCHOR_ATTR = "sla-anchor"
WHEN_ATTR = "sla-when"
REPEAT_ATTR = "sla-repeat"


@dataclass(frozen=True)
class TemplateVariable:
	key: str
	label: str
	group: str
	# How Contractor SLA formats the raw value (see format_value):
	# text | long_date | rand | words_int | number | block
	fmt: str = "text"
	# Row variables only make sense on a line repeating this kind.
	repeat: str | None = None
	description: str = ""


@dataclass(frozen=True)
class TemplateRepeat:
	key: str
	label: str
	description: str = ""


REPEATS: tuple[TemplateRepeat, ...] = (
	TemplateRepeat("services", "Service", "Each service on the SLA's Services table."),
	TemplateRepeat("milestones", "Milestone", "Each delivery/performance milestone with its due date."),
	TemplateRepeat("rates", "Rate", "Each rate on the SLA's Rates table."),
	TemplateRepeat("equipment", "Equipment", "Each equipment row (make, type, serial, fleet number)."),
	TemplateRepeat("special_terms", "Special Term", "Each SLA-specific term typed on the SLA."),
)
REPEATS_BY_KEY = {r.key: r for r in REPEATS}

VARIABLES: tuple[TemplateVariable, ...] = (
	# The Company
	TemplateVariable("company_name", "Company Name", "The Company"),
	TemplateVariable("company_registration_no", "Company Registration No.", "The Company"),
	TemplateVariable("company_address", "Company Address", "The Company"),
	TemplateVariable("company_representative", "Company Representative", "The Company"),
	TemplateVariable("company_representative_email", "Company Representative Email", "The Company"),
	# The Contractor
	TemplateVariable("supplier_name", "Contractor Name", "The Contractor"),
	TemplateVariable("supplier_registration_no", "Contractor Registration No.", "The Contractor"),
	TemplateVariable("supplier_address", "Contractor Address", "The Contractor"),
	TemplateVariable("supplier_representative", "Contractor Representative", "The Contractor"),
	TemplateVariable("supplier_representative_email", "Contractor Representative Email", "The Contractor"),
	# Agreement
	TemplateVariable("sla_reference", "SLA Reference", "Agreement", description="The SLA document number."),
	TemplateVariable(
		"scope_of_services",
		"Scope of Services",
		"Agreement",
		description="e.g. provision and maintenance of Lighting Plants",
	),
	TemplateVariable("operation_name", "Operation", "Agreement", description="e.g. Middelburg Mining Services"),
	TemplateVariable(
		"operation_definition",
		"Operation Definition",
		"Agreement",
		description="What the operation means, e.g. the operations of the Company at its client's ...",
	),
	TemplateVariable("responsible_manager", "Responsible Manager", "Agreement"),
	TemplateVariable(
		"pricing_basis", "Pricing Basis", "Agreement", description="e.g. a Rand per lighting plant, per month"
	),
	TemplateVariable("total_monthly_value", "Total Monthly Value", "Agreement", fmt="rand"),
	# Duration
	TemplateVariable("start_date", "Start Date", "Duration", fmt="long_date"),
	TemplateVariable("end_date", "End Date", "Duration", fmt="long_date"),
	TemplateVariable(
		"duration_months", "Duration (months)", "Duration", fmt="words_int", description="e.g. twelve (12)"
	),
	TemplateVariable(
		"mobilisation_days", "Mobilisation (working days)", "Duration", fmt="words_int", description="e.g. one (1)"
	),
	# Rows
	TemplateVariable("service_description", "Service", "Each Service", repeat="services"),
	TemplateVariable("milestone_description", "Milestone", "Each Milestone", repeat="milestones"),
	TemplateVariable("milestone_date", "Milestone Due Date", "Each Milestone", fmt="long_date", repeat="milestones"),
	TemplateVariable("rate_description", "Rate Description", "Each Rate", repeat="rates"),
	TemplateVariable(
		"rate_basis", "Rate Basis", "Each Rate", repeat="rates", description="e.g. per lighting plant, per month"
	),
	TemplateVariable("rate_quantity", "Rate Quantity", "Each Rate", fmt="number", repeat="rates"),
	TemplateVariable("rate_amount", "Rate", "Each Rate", fmt="rand", repeat="rates"),
	TemplateVariable("equipment_make", "Equipment Make", "Each Equipment", repeat="equipment"),
	TemplateVariable("equipment_type", "Equipment Type", "Each Equipment", repeat="equipment"),
	TemplateVariable("equipment_serial_no", "Equipment S/N / Reg. No.", "Each Equipment", repeat="equipment"),
	TemplateVariable("equipment_capacity", "Equipment Capacity", "Each Equipment", repeat="equipment"),
	TemplateVariable("equipment_fleet_no", "Equipment Fleet No.", "Each Equipment", repeat="equipment"),
	TemplateVariable("special_term", "Special Term", "Each Special Term", repeat="special_terms"),
	# Blocks: a whole table, on its own unnumbered Text line
	TemplateVariable(
		"equipment_table", "Equipment Table", "Tables & Signatures", fmt="block", description="Put on its own Text line."
	),
	TemplateVariable(
		"penalties_table", "Penalties Table(s)", "Tables & Signatures", fmt="block", description="Put on its own Text line."
	),
	TemplateVariable(
		"rates_table", "Rates Table", "Tables & Signatures", fmt="block", description="Put on its own Text line."
	),
	TemplateVariable(
		"signature_block",
		"Signature Blocks",
		"Tables & Signatures",
		fmt="block",
		description="For the Contractor / For the Company, with witnesses. Put on its own Text line.",
	),
)
VARIABLES_BY_KEY = {v.key: v for v in VARIABLES}


@dataclass(frozen=True)
class TemplateCondition:
	key: str
	label: str
	group: str
	# Exclusive groups are alternatives: every SLA is exactly one of them.
	exclusive: bool = True
	description: str = ""


STATIC_CONDITIONS: tuple[TemplateCondition, ...] = (
	TemplateCondition("duration:fixed", "Fixed term", "Duration", description="Runs to an agreed End Date."),
	TemplateCondition(
		"duration:project", "Project based", "Duration", description="Endures while the operation/project continues."
	),
	TemplateCondition("equipment:any", "Has equipment", "Equipment"),
	TemplateCondition("equipment:none", "No equipment", "Equipment"),
	TemplateCondition("milestones:any", "Has milestones", "Milestones"),
	TemplateCondition("milestones:none", "No milestones", "Milestones"),
	TemplateCondition("penalties:any", "Has penalties", "Penalties"),
	TemplateCondition("penalties:none", "No penalties", "Penalties"),
	TemplateCondition("special_terms:any", "Has special terms", "Special Terms"),
	TemplateCondition("special_terms:none", "No special terms", "Special Terms"),
)
OPTION_PREFIX = "option:"
OPTION_DOCTYPE = "Contractor SLA Clause Option"


def clause_options() -> list[dict]:
	return frappe.get_all(
		OPTION_DOCTYPE, filters={"disabled": 0}, fields=["name", "description"], order_by="name"
	)


def all_conditions() -> list[TemplateCondition]:
	return [
		*STATIC_CONDITIONS,
		*(
			TemplateCondition(
				f"{OPTION_PREFIX}{o.name}",
				_("Option: {0}").format(o.name),
				"Clause Options",
				exclusive=False,
				description=o.description or "",
			)
			for o in clause_options()
		),
	]


def is_known_condition(key: str) -> bool:
	if any(c.key == key for c in STATIC_CONDITIONS):
		return True
	if key.startswith(OPTION_PREFIX):
		return bool(frappe.db.exists(OPTION_DOCTYPE, key[len(OPTION_PREFIX) :]))
	return False


def editor_config() -> dict:
	return {
		"max_indent": MAX_INDENT,
		"variables": [
			{"key": v.key, "label": v.label, "group": v.group, "repeat": v.repeat, "block": v.fmt == "block", "description": v.description}
			for v in VARIABLES
		],
		"conditions": [
			{"key": c.key, "label": c.label, "group": c.group, "exclusive": c.exclusive, "description": c.description}
			for c in all_conditions()
		],
		"repeats": [{"key": r.key, "label": r.label, "description": r.description} for r in REPEATS],
	}


@dataclass
class SLAContext:
	"""What one SLA supplies to the template. Every value is ready-to-insert
	HTML (see format_value); rows are keyed by repeat kind; conditions are the
	keys that hold for this SLA."""

	values: dict[str, str] = field(default_factory=dict)
	rows: dict[str, list[dict[str, str]]] = field(default_factory=dict)
	conditions: set[str] = field(default_factory=set)
	# What a missing value prints as.
	blank: str = "_____________________"
	blank_amount: str = "__________"


# ---- lines ----


@dataclass
class Segment:
	kind: str  # text | var | ref
	value: Any
	attrs: dict = field(default_factory=dict)


@dataclass
class Line:
	kind: str  # part | heading | clause | text
	indent: int = 0
	anchor: str | None = None
	segments: list[Segment] = field(default_factory=list)
	when: str | None = None  # condition key; None = every SLA
	repeat: str | None = None  # repeat kind; None = written once
	row: dict | None = None  # set on the copies resolve_lines() expands

	def is_blank(self) -> bool:
		return all(s.kind == "text" and not s.value.strip() for s in self.segments)

	def block_variable(self) -> str | None:
		"""The block variable this line holds, if it holds nothing else."""
		content = [s for s in self.segments if not (s.kind == "text" and not s.value.strip())]
		if len(content) == 1 and content[0].kind == "var":
			var = VARIABLES_BY_KEY.get(content[0].value)
			if var and var.fmt == "block":
				return var.key
		return None


def load_delta(value) -> dict:
	if not value:
		return {"ops": []}
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			frappe.throw(_("SLA Wording is not valid editor content."))
	if isinstance(value, list):
		value = {"ops": value}
	if not isinstance(value, dict) or not isinstance(value.get("ops"), list):
		frappe.throw(_("SLA Wording is not valid editor content."))
	return value


def parse_wording(value) -> list[Line]:
	"""Delta -> lines, dropping every format and embed the template doesn't support."""
	lines: list[Line] = []
	segments: list[Segment] = []

	for op in load_delta(value)["ops"]:
		if not isinstance(op, dict):
			continue
		insert = op.get("insert")
		attrs = op.get("attributes") or {}
		if isinstance(insert, str):
			inline = {k: True for k in INLINE_FORMATS if attrs.get(k)}
			parts = insert.split("\n")
			for i, part in enumerate(parts):
				if part:
					segments.append(Segment("text", _clean_text(part), inline))
				if i < len(parts) - 1:
					lines.append(_make_line(attrs, segments))
					segments = []
		elif isinstance(insert, dict):
			if isinstance(insert.get(VAR_EMBED), str):
				segments.append(Segment("var", insert[VAR_EMBED], {k: True for k in INLINE_FORMATS if attrs.get(k)}))
			elif isinstance(insert.get(REF_EMBED), dict):
				ref = insert[REF_EMBED]
				segments.append(
					Segment("ref", {"anchor": str(ref.get("anchor") or ""), "label": str(ref.get("label") or "")})
				)
	if segments:
		lines.append(_make_line({}, segments))
	return lines


def _clean_text(text: str) -> str:
	return text.replace("\t", " ").replace("\u00a0", " ")


def _make_line(attrs: dict, segments: list[Segment]) -> Line:
	if attrs.get("header") == 2:
		kind = "part"
	elif attrs.get("header"):
		kind = "heading"
	elif attrs.get("list") == "ordered":
		kind = "clause"
	else:
		kind = "text"
	indent = 0 if kind in ("heading", "part") else max(0, min(cint(attrs.get("indent")), MAX_INDENT))
	return Line(
		kind,
		indent,
		str(attrs[ANCHOR_ATTR]) if attrs.get(ANCHOR_ATTR) else None,
		segments,
		str(attrs[WHEN_ATTR]) if attrs.get(WHEN_ATTR) else None,
		str(attrs[REPEAT_ATTR]) if attrs.get(REPEAT_ATTR) else None,
	)


def to_delta(lines: list[Line]) -> dict:
	"""Lines -> the canonical Delta the editor loads. Duplicate anchors keep their first line."""
	ops: list[dict] = []
	seen_anchors: set[str] = set()
	for line in lines:
		for seg in line.segments:
			if seg.kind == "text":
				op = {"insert": seg.value}
				if seg.attrs:
					op["attributes"] = dict(seg.attrs)
				ops.append(op)
			elif seg.kind == "var":
				op = {"insert": {VAR_EMBED: seg.value}}
				if seg.attrs:
					op["attributes"] = dict(seg.attrs)
				ops.append(op)
			elif seg.kind == "ref":
				ops.append({"insert": {REF_EMBED: dict(seg.value)}})
		attrs: dict = {}
		if line.kind == "part":
			attrs["header"] = 2
		elif line.kind == "heading":
			attrs["header"] = 1
		elif line.kind == "clause":
			attrs["list"] = "ordered"
		if line.indent and line.kind not in ("heading", "part"):
			attrs["indent"] = line.indent
		if line.anchor and line.anchor not in seen_anchors:
			attrs[ANCHOR_ATTR] = line.anchor
			seen_anchors.add(line.anchor)
		if line.when:
			attrs[WHEN_ATTR] = line.when
		if line.repeat:
			attrs[REPEAT_ATTR] = line.repeat
		op = {"insert": "\n"}
		if attrs:
			op["attributes"] = attrs
		ops.append(op)
	return {"ops": ops}


def number_lines(lines: list[Line]) -> list[str | None]:
	numbers: list[str | None] = []
	section = 0
	levels: list[int] = []
	for line in lines:
		if line.kind == "part":
			section = 0
			levels = []
			numbers.append(None)
		elif line.kind == "heading":
			section += 1
			levels = []
			numbers.append(str(section))
		elif line.kind == "clause":
			k = line.indent
			levels = (levels + [0] * (k + 1))[: k + 1]
			levels[k] += 1
			numbers.append(".".join(str(n) for n in (section, *levels)))
		else:
			numbers.append(None)
	return numbers


def validate_lines(lines: list[Line], for_submit: bool = False) -> list[str]:
	"""Human-readable problems. Structural ones always block a save; the
	drafting ones (empty or orphan clauses) only block submit."""
	errors: list[str] = []
	numbers = number_lines(lines)
	anchored = {line.anchor: (line, number) for line, number in zip(lines, numbers) if line.anchor}
	seen_heading = False
	known_conditions: dict[str, bool] = {}

	for line, number in zip(lines, numbers):
		where = _("line {0}").format(number) if number else _("an unnumbered line")
		if line.when:
			if line.when not in known_conditions:
				known_conditions[line.when] = is_known_condition(line.when)
			if not known_conditions[line.when]:
				errors.append(_("Unknown condition {0} on {1}.").format(frappe.bold(line.when), where))
		if line.repeat and line.repeat not in REPEATS_BY_KEY:
			errors.append(_("Unknown repeat {0} on {1}.").format(frappe.bold(line.repeat), where))
		for seg in line.segments:
			if seg.kind == "var":
				var = VARIABLES_BY_KEY.get(seg.value)
				if not var:
					errors.append(_("Unknown variable {0} on {1}.").format(frappe.bold(seg.value), where))
				elif var.repeat and var.repeat != line.repeat:
					errors.append(
						_("{0} only works on a line set to Repeat for each {1} ({2}).").format(
							frappe.bold(var.label), REPEATS_BY_KEY[var.repeat].label, where
						)
					)
				elif var.fmt == "block" and (line.kind != "text" or line.repeat or line.block_variable() != var.key):
					errors.append(
						_("{0} must be alone on its own unnumbered Text line ({1}).").format(
							frappe.bold(var.label), where
						)
					)
			elif seg.kind == "ref":
				target = anchored.get(seg.value["anchor"])
				if not target:
					errors.append(
						_("The reference to {0} on {1} points to a heading or clause that no longer exists.").format(
							frappe.bold(seg.value["label"] or "?"), where
						)
					)
				elif not target[1]:
					errors.append(
						_("The reference to {0} on {1} points to unnumbered text.").format(
							frappe.bold(seg.value["label"] or "?"), where
						)
					)

		if line.kind == "part":
			seen_heading = False
		if line.kind == "heading":
			seen_heading = True
		if for_submit and line.kind in ("heading", "clause", "part"):
			if line.is_blank():
				errors.append(_("Line {0} is empty.").format(number or _("(Annexure title)")))
			if line.kind == "clause" and not seen_heading:
				errors.append(_("Clause {0} comes before the first Heading.").format(number))
	return errors


# ---- rendering ----


def resolve_lines(lines: list[Line], context: SLAContext) -> list[Line]:
	"""Drop lines whose condition doesn't hold, then write each repeat line once per row."""
	resolved: list[Line] = []
	for line in lines:
		if line.when and line.when not in context.conditions:
			continue
		if not line.repeat:
			resolved.append(line)
			continue
		for i, row in enumerate(context.rows.get(line.repeat) or []):
			resolved.append(replace(line, anchor=line.anchor if i == 0 else None, row=row))
	return resolved


def used_variables(lines: list[Line], context: SLAContext) -> list[TemplateVariable]:
	"""Variables that actually print for this SLA (after conditions/repeats), in order."""
	seen: dict[str, TemplateVariable] = {}
	for line in resolve_lines(lines, context):
		for seg in line.segments:
			if seg.kind == "var" and seg.value in VARIABLES_BY_KEY:
				seen.setdefault(seg.value, VARIABLES_BY_KEY[seg.value])
	return list(seen.values())


def render_wording(lines: list[Line], context: SLAContext) -> str:
	"""Render to number | wording tables; parts start a new page, blocks sit between tables."""
	lines = resolve_lines(lines, context)
	numbers = number_lines(lines)
	anchors = {line.anchor: number for line, number in zip(lines, numbers) if line.anchor and number}

	out: list[str] = []
	rows: list[str] = []

	def flush():
		if rows:
			out.append('<table class="sla-clauses">' + "".join(rows) + "</table>")
			rows.clear()

	seen_heading = False
	for line, number in zip(lines, numbers):
		if line.kind == "text" and line.is_blank():
			continue
		if line.kind == "part":
			flush()
			seen_heading = False
			content = "".join(_render_segment(seg, line, context, anchors) for seg in line.segments)
			out.append(f'<div class="sla-part"><h3 class="sla-part-title">{content}</h3></div>')
			continue
		block = line.block_variable() if line.kind == "text" else None
		if block:
			flush()
			out.append(f'<div class="sla-block sla-block-{block}">{context.values.get(block) or ""}</div>')
			continue
		content = "".join(_render_segment(seg, line, context, anchors) for seg in line.segments)
		if line.kind == "heading":
			seen_heading = True
			rows.append(f'<tr class="sla-heading"><td class="sla-no">{number}.</td><td>{content}</td></tr>')
		elif line.kind == "clause":
			rows.append(f'<tr class="sla-clause"><td class="sla-no">{number}.</td><td>{content}</td></tr>')
		elif seen_heading:
			rows.append(f'<tr class="sla-text"><td class="sla-no"></td><td>{content}</td></tr>')
		else:
			rows.append(f'<tr class="sla-text"><td colspan="2">{content}</td></tr>')
	flush()
	return '<div class="sla-wording">' + "".join(out) + "</div>"


def _render_segment(seg: Segment, line: Line, context: SLAContext, anchors: dict[str, str]) -> str:
	if seg.kind == "var":
		var = VARIABLES_BY_KEY.get(seg.value)
		if not var:
			return ""
		if var.fmt == "block":
			return context.values.get(var.key) or ""
		source = line.row if var.repeat else context.values
		blank = context.blank_amount if var.fmt in ("rand", "words_int", "number") else context.blank
		out = (source or {}).get(var.key) or blank
	elif seg.kind == "ref":
		return html.escape(anchors.get(seg.value["anchor"], "??"))
	else:
		out = html.escape(seg.value)
	if seg.attrs.get("bold"):
		out = f"<b>{out}</b>"
	if seg.attrs.get("italic"):
		out = f"<i>{out}</i>"
	if seg.attrs.get("underline"):
		out = f"<u>{out}</u>"
	return out


# ---- value formatting ----


def format_value(fmt: str, raw) -> str:
	"""Raw SLA value -> the HTML an SLA shows, per the variable's format."""
	if raw is None or raw == "":
		return ""
	if fmt == "long_date":
		return html.escape(long_date(raw))
	if fmt == "rand":
		return html.escape(rand_words(raw))
	if fmt == "words_int":
		n = cint(raw)
		return html.escape(f"{int_words(n).lower()} ({n})")
	if fmt == "number":
		return html.escape(f"{flt(raw):g}")
	# Multi-line values (addresses) read as one line in running text.
	return html.escape(", ".join(part.strip() for part in str(raw).splitlines() if part.strip()))


def long_date(value) -> str:
	"""'31 March 2026' - the date style SLAs use."""
	d = getdate(value)
	return f"{d.day} {d.strftime('%B %Y')}"


def rand_words(value) -> str:
	"""'R 14 000.00 (Fourteen Thousand Rand Only)'."""
	amount = round(flt(value), 2)
	whole = int(amount)
	cents = round((amount - whole) * 100)
	words = f"{int_words(whole)} Rand"
	if cents:
		words += f" and {int_words(cents)} Cents"
	return f"R {amount:,.2f}".replace(",", " ") + f" ({words} Only)"


_UNITS = ("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine")
_TEENS = ("Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen")
_TENS = ("Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def int_words(n: int) -> str:
	n = int(n)
	if n < 0:
		return "Minus " + int_words(-n)
	if n < 10:
		return _UNITS[n]
	if n < 20:
		return _TEENS[n - 10]
	if n < 100:
		return _TENS[n // 10 - 2] + ("" if n % 10 == 0 else "-" + _UNITS[n % 10])
	if n < 1000:
		return _UNITS[n // 100] + " Hundred" + ("" if n % 100 == 0 else " and " + int_words(n % 100))
	for size, name in ((1_000_000_000, "Billion"), (1_000_000, "Million"), (1000, "Thousand")):
		if n >= size:
			return int_words(n // size) + f" {name}" + ("" if n % size == 0 else " " + int_words(n % size))
	return str(n)


# ---- SLA Markdown (the power-user tab) ----
#
#   ## ANNEXURE A
#   # Price and Payment {#price}
#   1. Paid on {{pricing_basis}} basis.
#       1. {{service_description}}; {repeat=services}
#   1. Diesel is supplied by the Company. {when="option:Diesel Supplied by Company"}
#   1. As set out in [Force Majeure](#force-majeure).
#   {{penalties_table}}
#
# Inline: **bold**, *italic*, <u>underline</u>, {{variable}}, [label](#anchor).
# A trailing {#anchor when=... repeat=...} block sets the line's options.
# Escape a literal * { [ < or \ with a backslash.

MD_INDENT = "    "
_MD_ATTRS = re.compile(r"\s*\{((?:#[\w-]+|when=|repeat=)(?:[^{}\"]|\"[^\"]*\")*)\}\s*$")
_MD_ATTR_ITEM = re.compile(r"#([\w-]+)|(when|repeat)=(\"[^\"]*\"|\S+)")
_MD_INLINE = re.compile(
	r"\\(?P<esc>.)|(?P<bold>\*\*)|(?P<italic>\*)|(?P<u_open><u>)|(?P<u_close></u>)"
	r"|\{\{\s*(?P<var>[\w:.-]+)\s*\}\}|\[(?P<ref_label>[^\]]*)\]\(#(?P<ref_anchor>[\w-]+)\)"
)


def to_markdown(lines: list[Line]) -> str:
	out = []
	for line in lines:
		if line.kind == "part":
			prefix = "## "
		elif line.kind == "heading":
			prefix = "# "
		elif line.kind == "clause":
			prefix = MD_INDENT * line.indent + "1. "
		else:
			prefix = MD_INDENT * line.indent
		text = _segments_to_markdown(line.segments)
		if line.kind == "text":
			text = re.sub(r"^(#)(?=#* )|^(\d+)\.(?=\s)", lambda m: "\\#" if m.group(1) else m.group(2) + "\\.", text)
		attrs = []
		if line.anchor:
			attrs.append(f"#{line.anchor}")
		if line.when:
			attrs.append(f"when={_md_attr_value(line.when)}")
		if line.repeat:
			attrs.append(f"repeat={_md_attr_value(line.repeat)}")
		suffix = (" {" + " ".join(attrs) + "}") if attrs else ""
		if line.kind == "text" and not text and not suffix:
			out.append("")
		else:
			out.append(f"{prefix}{text}{suffix}")
	return "\n".join(out).rstrip("\n") + "\n"


def _md_attr_value(value: str) -> str:
	return f'"{value}"' if re.search(r'[\s{}"]', value) else value


def _segments_to_markdown(segments: list[Segment]) -> str:
	out = []
	state = {"bold": False, "italic": False, "underline": False}
	markers = {"bold": ("**", "**"), "italic": ("*", "*"), "underline": ("<u>", "</u>")}

	def set_state(wanted: dict):
		# close inner-most first, then open
		for fmt in ("underline", "italic", "bold"):
			if state[fmt] and not wanted.get(fmt):
				out.append(markers[fmt][1])
				state[fmt] = False
		for fmt in ("bold", "italic", "underline"):
			if wanted.get(fmt) and not state[fmt]:
				out.append(markers[fmt][0])
				state[fmt] = True

	for seg in segments:
		if seg.kind == "text":
			set_state(seg.attrs)
			out.append(re.sub(r"([\\*{\[<])", r"\\\1", seg.value))
		elif seg.kind == "var":
			set_state(seg.attrs)
			out.append("{{" + seg.value + "}}")
		else:
			set_state({})
			label = re.sub(r"([\\\]\[])", r"\\\1", seg.value["label"])
			out.append(f"[{label}](#{seg.value['anchor']})")
	set_state({})
	return "".join(out).rstrip()


def parse_markdown(text: str) -> list[Line]:
	lines: list[Line] = []
	for raw in (text or "").replace("\r\n", "\n").split("\n"):
		raw = raw.replace("\t", MD_INDENT).rstrip()
		attrs: dict[str, str] = {}
		match = _MD_ATTRS.search(raw)
		if match and not raw[: match.start()].endswith("\\"):
			for item in _MD_ATTR_ITEM.finditer(match.group(1)):
				if item.group(1):
					attrs["anchor"] = item.group(1)
				else:
					attrs[item.group(2)] = item.group(3).strip('"')
			raw = raw[: match.start()]

		stripped = raw.lstrip(" ")
		indent = min((len(raw) - len(stripped)) // len(MD_INDENT), MAX_INDENT)
		if stripped.startswith("## "):
			kind, body, indent = "part", stripped[3:], 0
		elif stripped.startswith("# "):
			kind, body, indent = "heading", stripped[2:], 0
		elif m := re.match(r"\d+\.\s+", stripped):
			kind, body = "clause", stripped[m.end() :]
		else:
			kind, body = "text", stripped
		lines.append(
			Line(kind, indent, attrs.get("anchor"), _parse_inline(body), attrs.get("when"), attrs.get("repeat"))
		)
	while lines and lines[-1].kind == "text" and not lines[-1].segments and not lines[-1].when:
		lines.pop()
	return lines


def _parse_inline(body: str) -> list[Segment]:
	segments: list[Segment] = []
	state = {"bold": False, "italic": False, "underline": False}
	buffer: list[str] = []

	def flush():
		if buffer:
			segments.append(Segment("text", _clean_text("".join(buffer)), {k: True for k, v in state.items() if v}))
			buffer.clear()

	pos = 0
	for m in _MD_INLINE.finditer(body):
		buffer.append(body[pos : m.start()])
		pos = m.end()
		if m.group("esc") is not None:
			buffer.append(m.group("esc"))
			continue
		flush()
		if m.group("bold"):
			state["bold"] = not state["bold"]
		elif m.group("italic"):
			state["italic"] = not state["italic"]
		elif m.group("u_open"):
			state["underline"] = True
		elif m.group("u_close"):
			state["underline"] = False
		elif m.group("var"):
			segments.append(Segment("var", m.group("var"), {k: True for k, v in state.items() if v}))
		else:
			label = re.sub(r"\\(.)", r"\1", m.group("ref_label"))
			segments.append(Segment("ref", {"anchor": m.group("ref_anchor"), "label": label}))
	buffer.append(body[pos:])
	flush()
	return [s for s in segments if s.kind != "text" or s.value]


# ---- preview ----


def preview_context(scenario: dict | None = None) -> SLAContext:
	"""Sample SLA for Preview: every value is a [Label] placeholder, two sample
	rows per repeat, and the scenario picks duration basis and which optional
	parts (equipment, milestones, penalties, special terms, clause options) apply."""
	from procurement.procurement.doctype.contractor_sla.contractor_sla import (
		equipment_table_html,
		penalties_table_html,
		rates_table_html,
		signature_block_html,
	)

	scenario = scenario or {}

	def label(text: str) -> str:
		return f'<span class="sla-preview-var">[{html.escape(text)}]</span>'

	context = SLAContext(
		values={v.key: label(v.label) for v in VARIABLES if not v.repeat and v.fmt != "block"}
	)
	conditions = context.conditions
	conditions.add("duration:project" if scenario.get("duration_basis") == "project" else "duration:fixed")
	for part in ("equipment", "milestones", "penalties", "special_terms"):
		conditions.add(f"{part}:none" if scenario.get(part) == "no" else f"{part}:any")
	conditions.update(f"{OPTION_PREFIX}{o}" for o in scenario.get("options") or [] if o)

	# Services and rates have no "none" alternative: every SLA has some.
	for kind in REPEATS_BY_KEY:
		context.rows[kind] = (
			[]
			if f"{kind}:none" in conditions
			else [{v.key: label(f"{v.label} {n}") for v in VARIABLES if v.repeat == kind} for n in (1, 2)]
		)

	sample = frappe._dict(
		company=label("Company Name"),
		supplier_name=label("Contractor Name"),
		company_representative=label("Company Representative"),
		supplier_representative=label("Contractor Representative"),
	)
	context.values["equipment_table"] = equipment_table_html(
		[
			frappe._dict(make=f"[Make {n}]", equipment_type="[Type]", serial_no="[S/N]", capacity="[Capacity]", fleet_no="[Fleet No.]")
			for n in (1, 2)
		]
		if "equipment:any" in conditions
		else []
	)
	context.values["penalties_table"] = penalties_table_html(
		[
			frappe._dict(penalty_table="[Penalty Table]", area="[Area]", criteria=f"[Criteria {n}]", penalty="[Penalty]")
			for n in (1, 2)
		]
		if "penalties:any" in conditions
		else []
	)
	context.values["rates_table"] = rates_table_html(
		[frappe._dict(description=f"[Rate {n}]", rate_basis="[Basis]", qty=1, rate=0, amount=0) for n in (1, 2)]
	)
	context.values["signature_block"] = signature_block_html(sample, escape=False)
	return context
