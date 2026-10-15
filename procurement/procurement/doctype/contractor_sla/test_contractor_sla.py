# Copyright (c) 2026, Isambane Mining (Pty) Ltd and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from procurement.procurement.doctype.contractor_sla.contractor_sla import (
	check_sla,
	compute_status,
	due_expiry_notice,
	get_settings,
	make_renewal,
	whole_months,
)
from procurement.procurement.doctype.contractor_sla_template.contractor_sla_template import (
	load_standard_template,
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Company",
	"Supplier",
	"Branch",
	"Project",
	"User",
	"Currency",
	"Contractor SLA Template",
	"Contractor SLA Termination",
	"Contractor Non-Conformance",
	"Contractor Warning",
	"Contractor Warning Level",
]

SUPPLIER = "_Test SLA Contractor"
MANAGER = "_test_sla_manager@example.com"


def get_company():
	return frappe.db.get_value("Company", {"company_name": "Isambane Mining (Pty) Ltd"}) or frappe.get_all(
		"Company", pluck="name", limit=1
	)[0]


def ensure_manager():
	if not frappe.db.exists("User", MANAGER):
		frappe.get_doc(
			{"doctype": "User", "email": MANAGER, "first_name": "SLA Manager", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return MANAGER


def ensure_supplier():
	if not frappe.db.exists("Supplier", SUPPLIER):
		frappe.get_doc(
			{"doctype": "Supplier", "supplier_name": SUPPLIER, "supplier_group": frappe.get_all("Supplier Group", pluck="name", limit=1)[0]}
		).insert()
	return SUPPLIER


class SLAFixtures:
	"""Shared by the SLA, non-conformance, warning and termination tests."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.template = load_standard_template(submit=True)
		cls.company = get_company()
		cls.supplier = ensure_supplier()

	def make_sla(self, **overrides):
		values = {
			"doctype": "Contractor SLA",
			"sla_title": "Lighting Plants - MMS",
			"sla_template": self.template,
			"company": self.company,
			"supplier": self.supplier,
			"scope_of_services": "provision and maintenance of Lighting Plants",
			"operation_name": "Middelburg Mining Services",
			"operation_definition": "collectively, the operations of the Company at its client's operations",
			"pricing_basis": "a Rand per lighting plant, per month",
			"duration_basis": "Fixed Term",
			"start_date": today(),
			"end_date": add_days(today(), 364),
			"mobilisation_days": 1,
			"company_registration_no": "2005/016301/07",
			"company_address": "Plot 22, Middelburg, Mpumalanga, 1050",
			"company_representative": "Jozi Mthsali",
			"company_representative_email": "jozi@example.com",
			"supplier_registration_no": "2018/558304/07",
			"supplier_address": "L39, Masakhane Village, eMalahleni",
			"supplier_representative": "Themba Gulube",
			"supplier_representative_email": "contractor@example.com",
			"responsible_manager": "Administrator",
			"services": [
				{"service_description": "The provision, support and maintenance of twelve (12) suitable, approved Lighting Plants"},
				{"service_description": "Sufficient employees for the supervision and maintenance of the lighting plants"},
			],
			"rates": [{"description": "Lighting Plant", "rate_basis": "per lighting plant, per month", "qty": 12, "rate": 14000}],
			"equipment": [{"make": "DIY", "equipment_type": "Lighting Plant", "serial_no": "SDDT2503003", "capacity": "120 Liter", "fleet_no": "LPX214"}],
			"penalties": [{"penalty_table": "Table 2: General", "criteria": "No induction", "penalty": "R 2 500.00 per person"}],
			"clause_options": [{"clause_option": "Diesel Supplied by Company"}],
		}
		values.update(overrides)
		return frappe.get_doc(values)

	def sign(self, sla, on=None):
		"""Record both signatures and the signed copy on the draft."""
		sla.contractor_signed_on = on or today()
		sla.company_signed_on = on or today()
		sla.signed_copy = "/private/files/signed-sla.pdf"
		sla.save()
		return sla

	def execute(self, sla):
		"""Issue, sign and submit: a fully executed SLA."""
		if not sla.get("creation"):
			sla.insert()
		sla.issue_for_signature()
		self.sign(sla)
		sla.submit()
		return sla


class TestContractorSLA(SLAFixtures, IntegrationTestCase):
	def test_draft_renders_and_totals(self):
		sla = self.make_sla().insert()
		self.assertEqual(sla.status, "Draft")
		self.assertEqual(sla.total_monthly_value, 168000)
		html = sla.rendered_agreement
		self.assertIn("2.1.1.</td><td>The provision, support and maintenance of twelve (12)", html)
		self.assertIn("Lighting Plant: R 14 000.00 (Fourteen Thousand Rand Only) per lighting plant, per month", html)
		self.assertIn("diesel will be supplied by the Company", html)
		self.assertNotIn("conditional upon 100% availability", html)  # option not ticked
		self.assertIn("ANNEXURE A", html)
		self.assertIn("LPX214", html)
		self.assertIn("within one (1) working days", html)
		self.assertIn("as referred in clause 9;", html)

	def test_issue_requires_values_the_wording_uses(self):
		sla = self.make_sla(company_registration_no=None).insert()
		with self.assertRaises(frappe.ValidationError) as caught:
			sla.issue_for_signature()
		self.assertIn("Company Registration No.", str(caught.exception))

	def test_submit_only_once_signed(self):
		sla = self.make_sla().insert()
		with self.assertRaises(frappe.ValidationError) as caught:
			sla.submit()
		self.assertIn("Signed Copy", str(caught.exception))
		sla.reload()
		sla.issue_for_signature()
		self.assertEqual(sla.status, "Outstanding")
		sla.contractor_signed_on = today()
		sla.save()
		self.assertEqual((sla.signature_status, sla.status), ("Contractor Signed", "Outstanding"))
		sla.company_signed_on = today()
		sla.save()
		with self.assertRaises(frappe.ValidationError):
			sla.submit()  # still no signed copy
		sla.reload()
		sla.signed_copy = "/private/files/signed-sla.pdf"
		sla.save()
		sla.submit()
		self.assertEqual((sla.docstatus, sla.signature_status, sla.status), (1, "Fully Signed", "Active"))

	def test_issued_wording_is_frozen_until_withdrawn(self):
		sla = self.make_sla().insert()
		sla.issue_for_signature()
		frozen = sla.rendered_agreement
		sla.reload()
		sla.rates[0].rate = 15000
		with self.assertRaises(frappe.ValidationError):
			sla.save()
		sla.reload()
		sla.sla_title = "Renamed - not in the wording"
		sla.save()
		self.assertEqual(sla.rendered_agreement, frozen)
		sla.withdraw_from_signature()
		self.assertEqual(sla.status, "Draft")
		sla.rates[0].rate = 15000
		sla.save()
		self.assertIn("R 15 000.00", sla.rendered_agreement)

	def test_signed_without_issuing_freezes_on_submit(self):
		sla = self.make_sla().insert()
		self.sign(sla, on=add_days(today(), -2))
		sla.submit()
		self.assertEqual(str(sla.sent_for_signature_on), add_days(today(), -2))
		self.assertIn("ANNEXURE A", sla.rendered_agreement)

	def test_compute_status(self):
		sla = self.make_sla(start_date=add_days(today(), 10), end_date=add_days(today(), 200))
		self.assertEqual(compute_status(sla), "Draft")
		sla.sent_for_signature_on = today()
		self.assertEqual(compute_status(sla), "Outstanding")
		sla.docstatus = 1
		self.assertEqual(compute_status(sla, warning_days=90), "Upcoming")
		self.assertEqual(compute_status(sla, add_days(today(), 20), 90), "Active")
		self.assertEqual(compute_status(sla, add_days(today(), 120), 90), "Expiring Soon")
		self.assertEqual(compute_status(sla, add_days(today(), 201), 90), "Expired")
		sla.renewed_by = "SLA-X"
		self.assertEqual(compute_status(sla, add_days(today(), 120), 90), "Active")
		self.assertEqual(compute_status(sla, add_days(today(), 201), 90), "Renewed")
		sla.terminated_on = today()
		self.assertEqual(compute_status(sla), "Terminated")

	def test_expiry_notice_thresholds(self):
		sla = self.make_sla(end_date=add_days(today(), 45))
		sla.docstatus = 1
		thresholds = [90, 60, 30, 7]
		self.assertEqual(due_expiry_notice(sla, "Expiring Soon", thresholds, today()), 60)
		sla.expiry_notices_sent = "60"
		self.assertIsNone(due_expiry_notice(sla, "Expiring Soon", thresholds, today()))
		self.assertEqual(due_expiry_notice(sla, "Expiring Soon", thresholds, add_days(today(), 20)), 30)
		self.assertEqual(due_expiry_notice(sla, "Expired", thresholds, add_days(today(), 46)), -1)
		self.assertIsNone(due_expiry_notice(sla, "Expired", thresholds, add_days(today(), 60)))
		self.assertIsNone(due_expiry_notice(sla, "Terminated", thresholds, add_days(today(), 20)))
		sla.renewed_by = "SLA-X"
		self.assertIsNone(due_expiry_notice(sla, "Expiring Soon", thresholds, add_days(today(), 20)))

	def test_monitor_updates_status_and_notifies(self):
		sla = self.execute(
			self.make_sla(
				start_date=add_days(today(), -300), end_date=add_days(today(), 40), responsible_manager=ensure_manager()
			)
		)
		self.assertEqual(sla.status, "Expiring Soon")
		frappe.db.set_value("Contractor SLA", sla.name, "status", "Active", update_modified=False)
		check_sla(frappe.get_doc("Contractor SLA", sla.name), get_settings(), getdate(today()))
		status, sent = frappe.db.get_value("Contractor SLA", sla.name, ["status", "expiry_notices_sent"])
		self.assertEqual(status, "Expiring Soon")
		self.assertEqual(sent, "60")
		self.assertTrue(frappe.db.exists("Notification Log", {"document_name": sla.name, "for_user": MANAGER}))

	def test_notice_not_recorded_without_recipients(self):
		settings = get_settings()
		settings.notify_role = None
		sla = self.execute(self.make_sla(start_date=add_days(today(), -300), end_date=add_days(today(), 40)))
		check_sla(frappe.get_doc("Contractor SLA", sla.name), settings, getdate(today()))
		self.assertFalse(frappe.db.get_value("Contractor SLA", sla.name, "expiry_notices_sent"))

	def test_outstanding_reminder(self):
		sla = self.make_sla(responsible_manager=ensure_manager()).insert()
		sla.issue_for_signature()
		frappe.db.set_value("Contractor SLA", sla.name, "sent_for_signature_on", add_days(today(), -10))
		check_sla(frappe.get_doc("Contractor SLA", sla.name), get_settings(), getdate(today()))
		self.assertEqual(str(frappe.db.get_value("Contractor SLA", sla.name, "last_outstanding_notice_on")), today())

	def test_renewal(self):
		sla = self.execute(self.make_sla(start_date="2026-01-01", end_date="2026-12-31"))
		renewal = make_renewal(sla.name)
		self.assertEqual(renewal.renewal_of, sla.name)
		self.assertEqual(str(renewal.start_date), "2027-01-01")
		self.assertEqual(str(renewal.end_date), "2027-12-31")
		self.assertEqual(renewal.status, "Draft")
		self.assertFalse(renewal.contractor_signed_on or renewal.signed_copy or renewal.sent_for_signature_on)
		self.execute(renewal)
		self.assertEqual(frappe.db.get_value("Contractor SLA", sla.name, "renewed_by"), renewal.name)
		renewal.cancel()
		self.assertIsNone(frappe.db.get_value("Contractor SLA", sla.name, "renewed_by"))

	def test_whole_months(self):
		self.assertEqual(whole_months("2026-01-01", "2026-12-31"), 12)
		self.assertEqual(whole_months("2026-01-22", "2026-03-31"), 2)

	def test_project_based_needs_no_end_date(self):
		sla = self.make_sla(duration_basis="Project Based", end_date=None).insert()
		self.assertIn("endure for as long as the Company", sla.rendered_agreement)
		with self.assertRaises(frappe.ValidationError):
			self.make_sla(end_date=None).insert()
