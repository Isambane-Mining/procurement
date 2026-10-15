app_name = "procurement"
app_title = "Procurement"
app_publisher = "Isambane Mining (Pty) Ltd"
app_description = "Isambane Mining Procurement Migration Suite"
app_email = "eben@isambane.co.za"
app_license = "mit"
app_version = "16.0.0"
required_apps = ["erpnext"]
source_link = "http://github.com/buff0k/procurement"
app_logo_url = "/assets/procurement/images/is-logo.png"
app_home = "/desk/procurement"
add_to_apps_screen = [
	{
		"name": app_name,
		"logo": "/assets/procurement/images/is-logo.png",
		"title": app_title,
		"route": app_home,
		"has_permission": "procurement.procurement.utils.check_app_permission",
	}
]
fixtures = [
	{"dt": "Role", "filters": [["name", "in", ["Procurement Admin",	"Procurement User", "Procurement Manager"]]]}, 
	{"dt": "Custom DocPerm", "filters": [["role", "in", ["Procurement Admin", "Procurement User", "Procurement Manager", "Supplier"]]]},
	{"dt": "Client Script", "filters": [["name", "in", ["Auto Populate ESD Suppliers"]]]}
]
website_route_rules = [
	{"from_route": "/request_for_quotation_list/<name>", "to_route": "request_for_quotation_detail"},
	{"from_route": "/supplier_quotation_list/<name>", "to_route": "supplier_quotation_detail"}
]
api_routes = [
	{"from_route": "/api/method/procurement.api.get_rfq_image", "to_route": "procurement.api.get_rfq_image"}
]
doc_events = {
	"Purchase Requisition": {
		"before_submit": "procurement.procurement.doctype.purchase_requisition.purchase_requisition.validate_before_submit"
	}
}
scheduler_events = {
	"daily": [
		"procurement.procurement.doctype.contractor_sla.contractor_sla.daily_sla_monitor",
	]
}
standard_portal_menu_items = [
	{
		"title": "Open RFQs",
		"route": "/request_for_quotation_list",
		"reference_doctype": "Request for Quotation",
		"role": "Supplier",
	},
	{
		"title": "My Quotations",
		"route": "/supplier_quotation_list",
		"reference_doctype": "Supplier Quotation",
		"role": "Supplier",
	}
]