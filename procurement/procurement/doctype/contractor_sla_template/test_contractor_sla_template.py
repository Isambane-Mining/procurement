# Copyright (c) 2026, Isambane Mining (Pty) Ltd and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from procurement.procurement.doctype.contractor_sla_template.contractor_sla_template import (
	STANDARD_CLAUSE_OPTIONS,
	STANDARD_TEMPLATE_FILE,
)
from procurement.procurement.sla_wording import (
	SLAContext,
	format_value,
	int_words,
	long_date,
	number_lines,
	parse_markdown,
	parse_wording,
	preview_context,
	rand_words,
	render_wording,
	to_delta,
	to_markdown,
	validate_lines,
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


def ensure_clause_options():
	for option in STANDARD_CLAUSE_OPTIONS:
		if not frappe.db.exists("Contractor SLA Clause Option", option):
			frappe.get_doc({"doctype": "Contractor SLA Clause Option", "option_name": option}).insert()


def standard_markdown():
	with open(STANDARD_TEMPLATE_FILE) as fh:
		return fh.read()


class TestSLAWording(IntegrationTestCase):
	def setUp(self):
		ensure_clause_options()

	def test_markdown_round_trip(self):
		lines = parse_markdown(standard_markdown())
		self.assertEqual(to_markdown(parse_markdown(to_markdown(lines))), to_markdown(lines))
		# Delta round trip keeps every line, format and embed.
		self.assertEqual(to_markdown(parse_wording(to_delta(lines))), to_markdown(lines))

	def test_standard_template_is_valid(self):
		lines = parse_markdown(standard_markdown())
		self.assertEqual(validate_lines(lines, for_submit=True), [])
		kinds = {line.kind for line in lines}
		self.assertEqual(kinds, {"part", "heading", "clause", "text"})

	def test_part_restarts_numbering(self):
		lines = parse_markdown("# One\n1. a\n    1. b\n# Two\n1. c\n## ANNEXURE A\n# First\n1. d\n")
		self.assertEqual(number_lines(lines), ["1", "1.1", "1.1.1", "2", "2.1", None, "1", "1.1"])

	def test_block_variable_must_stand_alone(self):
		errors = validate_lines(parse_markdown("# One\n1. See {{penalties_table}}\n"))
		self.assertTrue(any("own unnumbered Text line" in e for e in errors))
		self.assertEqual(validate_lines(parse_markdown("# One\n1. See below\n{{penalties_table}}\n")), [])

	def test_row_variable_needs_repeat(self):
		errors = validate_lines(parse_markdown("# One\n1. {{service_description}}\n"))
		self.assertTrue(any("Repeat for each Service" in e for e in errors))

	def test_unknown_condition_and_option(self):
		errors = validate_lines(parse_markdown('# One\n1. x {when="option:No Such Option"}\n1. y {when=nope}\n'))
		self.assertEqual(len(errors), 2)
		self.assertEqual(
			validate_lines(parse_markdown('# One\n1. x {when="option:Diesel Supplied by Company"}\n')), []
		)

	def test_hidden_lines_close_numbering_and_refs_follow(self):
		lines = parse_markdown(
			"# A\n1. fixed {when=duration:fixed}\n1. project {when=duration:project}\n"
			"1. Target {#target}\n1. See [x](#target).\n"
		)
		context = SLAContext(conditions={"duration:project"})
		html = render_wording(lines, context)
		self.assertNotIn("fixed", html)
		self.assertIn("1.2.</td><td>Target", html)
		self.assertIn("See 1.2.", html)

	def test_repeat_rows_and_formatting(self):
		lines = parse_markdown("# A\n1. Services:\n    1. **{{service_description}}**; {repeat=services}\n")
		context = SLAContext(rows={"services": [{"service_description": "Lights"}, {"service_description": "Vehicles"}]})
		html = render_wording(lines, context)
		self.assertIn("1.1.1.</td><td><b>Lights</b>;", html)
		self.assertIn("1.1.2.</td><td><b>Vehicles</b>;", html)

	def test_value_formats(self):
		self.assertEqual(rand_words(14000), "R 14 000.00 (Fourteen Thousand Rand Only)")
		self.assertEqual(rand_words(1250.5), "R 1 250.50 (One Thousand Two Hundred and Fifty Rand and Fifty Cents Only)")
		self.assertEqual(format_value("words_int", 12), "twelve (12)")
		self.assertEqual(int_words(21), "Twenty-One")
		self.assertEqual(long_date("2026-03-31"), "31 March 2026")
		self.assertEqual(format_value("text", "Plot 22\nMiddelburg\n"), "Plot 22, Middelburg")
		self.assertEqual(format_value("text", "<b>"), "&lt;b&gt;")

	def test_preview_renders_standard_template(self):
		lines = parse_markdown(standard_markdown())
		html = render_wording(lines, preview_context({"duration_basis": "project", "equipment": "no"}))
		self.assertIn("ANNEXURE A", html)
		self.assertIn("[Service 1]", html)
		self.assertNotIn("sla-block-equipment_table", html)
		self.assertIn("FOR THE CONTRACTOR", html)


class TestContractorSLATemplate(IntegrationTestCase):
	def test_naming_and_markdown_sync(self):
		ensure_clause_options()
		doc = frappe.get_doc(
			{
				"doctype": "Contractor SLA Template",
				"template_name": "_Test SLA Template Naming",
				"sla_markdown": "# Scope\n1. The {{scope_of_services}}.\n",
			}
		).insert()
		self.assertTrue(doc.name.startswith("_Test SLA Template Naming - "))
		self.assertIn('"sla-var":"scope_of_services"', doc.sla_wording)
		self.assertEqual(doc.sla_markdown, "# Scope\n1. The {{scope_of_services}}.\n")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Contractor SLA Template", "template_name": "_Test SLA Template Naming"}
			).insert()

	def test_submit_needs_wording(self):
		doc = frappe.get_doc({"doctype": "Contractor SLA Template", "template_name": "_Test SLA Empty"}).insert()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
