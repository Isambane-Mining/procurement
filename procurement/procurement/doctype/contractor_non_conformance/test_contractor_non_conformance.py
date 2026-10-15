# Copyright (c) 2026, Isambane Mining (Pty) Ltd and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from procurement.patches.create_default_contractor_warning_levels import execute as create_levels
from procurement.procurement.doctype.contractor_non_conformance.contractor_non_conformance import (
	check_overdue_remediation,
	close_case,
	make_termination,
	make_warning,
	suggested_level,
)
from procurement.procurement.doctype.contractor_sla.contractor_sla import (
	get_settings,
	make_non_conformance,
	monitored_slas,
)
from procurement.procurement.doctype.contractor_warning.contractor_warning import expire_warnings
from procurement.procurement.doctype.contractor_sla.test_contractor_sla import (
	MANAGER,
	SLAFixtures,
	ensure_manager,
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Company",
	"Supplier",
	"Branch",
	"Project",
	"User",
	"Currency",
	"Contractor SLA",
	"Contractor SLA Template",
	"Contractor Warning",
	"Contractor SLA Termination",
	"Contractor Non-Conformance",
	"Contractor Warning Level",
]


class TestContractorNonConformance(SLAFixtures, IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_levels()

	def setUp(self):
		self.sla = self.execute(self.make_sla(responsible_manager=ensure_manager()))

	def open_case(self, **values):
		case = make_non_conformance(self.sla.name)
		case.update(
			{
				"category": "Safety",
				"severity": "Major",
				"description": "Lighting plant LPX214 operated without a working FRSC.",
				"corrective_actions": [{"action": "Repair the FRSC on LPX214", "due_date": add_days(today(), 7)}],
				**values,
			}
		)
		return case.insert()

	def issue_warning(self, case, level=None):
		warning = make_warning(case.name)
		if level:
			warning.warning_level = level
		warning.insert()
		warning.signed_acknowledgement = "/private/files/ack.pdf"
		warning.submit()
		return warning

	def test_case_needs_signed_open_sla(self):
		draft = self.make_sla().insert()
		case = frappe.new_doc("Contractor Non-Conformance")
		case.update({"contractor_sla": draft.name, "category": "Safety", "severity": "Minor", "description": "x"})
		with self.assertRaises(frappe.ValidationError):
			case.insert()

	def test_case_fetches_sla_and_history(self):
		first = self.open_case()
		self.assertEqual((first.supplier, first.status), (self.sla.supplier, "Remediation"))
		self.assertEqual(str(first.remediation_due_date), add_days(today(), 7))
		second = self.open_case(corrective_actions=[])
		self.assertEqual(second.status, "Open")
		self.assertIn(first.name, [row.non_conformance for row in second.history])

	def test_warning_escalation(self):
		case = self.open_case()
		self.assertEqual(suggested_level(self.sla.name)["level"], "Verbal Warning")

		warning = self.issue_warning(case)
		self.assertEqual(warning.warning_level, "Verbal Warning")
		self.assertEqual(str(warning.valid_until), add_days(today(), 90))
		self.assertEqual(warning.status, "Active")
		self.assertIn("Written Warning", warning.consequence)
		case.reload()
		self.assertEqual((case.warning, case.outcome, case.status), (warning.name, "Warning Issued", "Remediation"))

		second = self.open_case()
		self.assertEqual(self.issue_warning(second).warning_level, "Written Warning")
		third = self.open_case()
		final = self.issue_warning(third)
		self.assertEqual(final.warning_level, "Final Written Warning")
		self.assertIn("final warning", final.consequence)
		self.assertTrue(suggested_level(self.sla.name)["recommend_termination"])

	def test_warning_needs_acknowledgement(self):
		warning = make_warning(self.open_case().name).insert()
		with self.assertRaises(frappe.ValidationError):
			warning.submit()

	def test_warning_adds_corrective_action_to_case(self):
		case = self.open_case(corrective_actions=[])
		warning = make_warning(case.name)
		warning.corrective_action_required = "Replace all FRSC units"
		warning.remediation_due_date = add_days(today(), 10)
		warning.insert()
		warning.signed_acknowledgement = "/private/files/ack.pdf"
		warning.submit()
		case.reload()
		self.assertEqual([row.action for row in case.corrective_actions], ["Replace all FRSC units"])

	def test_warning_moves_overdue_actions_to_its_deadline(self):
		case = self.open_case(corrective_actions=[{"action": "Repair FRSC", "due_date": add_days(today(), -3)}])
		frappe.db.set_value("Contractor Non-Conformance", case.name, "overdue_notified_on", today())
		warning = self.issue_warning(case)
		case.reload()
		self.assertEqual(str(case.corrective_actions[0].due_date), str(warning.remediation_due_date))
		self.assertEqual(str(warning.remediation_due_date), add_days(today(), 7))
		self.assertIsNone(case.overdue_notified_on)

	def test_close_remediated_needs_verified_actions(self):
		case = self.open_case()
		with self.assertRaises(frappe.ValidationError):
			close_case(case.name, "Remediated")
		case.reload()
		case.corrective_actions[0].completed_on = today()
		case.remediation_verified_on = today()
		case.save()
		self.assertEqual(close_case(case.name, "Remediated"), "Closed - Remediated")

	def test_close_no_further_action_needs_notes(self):
		case = self.open_case()
		with self.assertRaises(frappe.ValidationError):
			close_case(case.name, "No Further Action")
		self.assertEqual(
			close_case(case.name, "No Further Action", "Equipment was the client's"), "Closed - No Further Action"
		)

	def test_plain_submit_is_refused(self):
		case = self.open_case()
		with self.assertRaises(frappe.ValidationError):
			case.submit()

	def test_overdue_remediation_notice(self):
		case = self.open_case()
		frappe.db.set_value("Contractor Non-Conformance", case.name, "remediation_due_date", add_days(today(), -3))
		check_overdue_remediation(get_settings(), getdate(today()))
		self.assertEqual(
			str(frappe.db.get_value("Contractor Non-Conformance", case.name, "overdue_notified_on")), today()
		)
		self.assertTrue(frappe.db.exists("Notification Log", {"document_name": case.name, "for_user": MANAGER}))

	def test_warning_expires(self):
		warning = self.issue_warning(self.open_case())
		frappe.db.set_value("Contractor Warning", warning.name, "valid_until", add_days(today(), -1))
		expire_warnings(get_settings(), getdate(today()))
		self.assertEqual(frappe.db.get_value("Contractor Warning", warning.name, "status"), "Expired")
		self.assertEqual(suggested_level(self.sla.name)["level"], "Verbal Warning")


class TestContractorSLATermination(SLAFixtures, IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_levels()

	def terminate(self, sla, **values):
		termination = frappe.new_doc("Contractor SLA Termination")
		termination.update(
			{
				"contractor_sla": sla.name,
				"initiated_by": "Company",
				"termination_ground": "Convenience of the Company",
				"notice_date": today(),
				"effective_date": add_days(today(), 3),
				"reason": "Project ended early.",
				**values,
			}
		)
		return termination.insert()

	def test_termination_removes_sla_from_notices(self):
		sla = self.execute(
			self.make_sla(start_date=add_days(today(), -300), end_date=add_days(today(), 40), responsible_manager=ensure_manager())
		)
		termination = self.terminate(sla)
		with self.assertRaises(frappe.ValidationError):
			termination.submit()  # no signed notice
		termination.reload()
		termination.signed_notice = "/private/files/notice.pdf"
		termination.save()
		termination.submit()
		sla.reload()
		self.assertEqual((sla.status, str(sla.terminated_on), sla.sla_termination), ("Terminated", add_days(today(), 3), termination.name))

		self.assertNotIn(sla.name, monitored_slas())
		with self.assertRaises(frappe.ValidationError):
			make_non_conformance(sla.name)
		with self.assertRaises(frappe.ValidationError):
			self.terminate(sla)

		termination.cancel()
		sla.reload()
		self.assertEqual((sla.status, sla.terminated_on), ("Expiring Soon", None))

	def test_notice_rules(self):
		sla = self.execute(self.make_sla())
		with self.assertRaises(frappe.ValidationError):
			self.terminate(sla, effective_date=add_days(today(), 1))  # convenience needs 48 hours
		with self.assertRaises(frappe.ValidationError):
			self.terminate(sla, termination_ground="Company Insolvency")  # a contractor ground
		self.terminate(sla, initiated_by="Contractor", termination_ground="Company Insolvency")

	def test_escalated_case_closes_on_termination(self):
		sla = self.execute(self.make_sla())
		case = make_non_conformance(sla.name)
		case.update({"category": "Conduct", "severity": "Critical", "description": "Assault on site."})
		case.insert()
		termination = make_termination(case.name)
		self.assertEqual((termination.non_conformance, termination.termination_ground), (case.name, "Material Breach Not Remedied"))
		termination.effective_date = today()
		termination.signed_notice = "/private/files/notice.pdf"
		termination.insert()
		termination.submit()
		case.reload()
		self.assertEqual((case.docstatus, case.status, case.sla_termination), (1, "Escalated to Termination", termination.name))
