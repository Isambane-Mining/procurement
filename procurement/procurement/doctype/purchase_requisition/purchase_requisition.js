// Copyright (c) 2025, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on('Purchase Requisition', {
    company: function (frm) {
        if (frm.doc.company) {
            // Call server script to fetch company details
            frappe.call({
                method: "procurement.procurement.doctype.purchase_requisition.purchase_requisition.get_company_details",
                args: { company: frm.doc.company },
                callback: function (r) {
                    if (r.message) {
                        frm.set_value("letter_head", r.message.default_letter_head);
                        frm.set_value("company_abbr", r.message.company_abbr);
                    }
                }
            });
        } else {
            // Clear fields if company is unset
            frm.set_value("letter_head", null);
            frm.set_value("company_abbr", null);
        }
    },










    refresh: function(frm) {
        frm.fields_dict['item_list'].grid.wrapper.on('change', 'input[data-fieldname="qty"], input[data-fieldname="unit_price"]', function() {
            calculate_total_cost(frm);
            calculate_totals(frm);
        });

        apply_item_account_filter(frm);
        apply_asset_location_filter(frm);
        apply_parts_requisition_filter(frm);
        apply_buyer_role_filter(frm);

        frm.trigger('update_employee_names');

        if (frappe.user.has_role('Procurement Admin')) {
            frm.add_custom_button(__('Generate Order Number'), function() {
                frappe.call({
                    method: "procurement.procurement.doctype.purchase_requisition.purchase_requisition.generate_order_number",
                    args: {
                        doc: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.exc) {
                            frappe.msgprint(__("Error: {0}").format(r.exc));
                        } else {
                            frappe.msgprint(__("Order Number generated successfully."));
                            frm.reload_doc();
                        }
                    }
                });
            });
        }

        if (frm.doc.official_company_order_no && !frm.is_new()) {
            frm.add_custom_button(__('Generate Purchase Order'), function() {
                frappe.call({
                    method: "procurement.procurement.doctype.purchase_requisition.purchase_requisition.make_purchase_order",
                    args: {
                        source_name: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frappe.msgprint(__("Purchase Order created/opened: {0}").format(r.message));
                            frappe.set_route("Form", "Purchase Order", r.message);
                        }
                    },
                    error: function(r) {
                        let msg = r.message || r._server_messages || r.exc || "Purchase Order could not be created.";
                        frappe.msgprint({
                            title: __("Purchase Order Error"),
                            message: msg,
                            indicator: "red"
                        });
                    }
                });
            });
        }
    },








    validate: function(frm) {
        calculate_totals(frm);
    },

    // Trigger the update when the linked fields are changed
    requested_by: function (frm) {
        frm.trigger('update_employee_names');
    },
    deliver_to: function (frm) {
        frm.trigger('update_employee_names');
    },
    authorized_by: function (frm) {
        frm.trigger('update_employee_names');
    },

    update_employee_names: function (frm) {
        if (frm.doc.requested_by) {
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Employee",
                    filters: { name: frm.doc.requested_by },
                    fieldname: "employee_name"
                },
                callback: function (r) {
                    frm.set_value("req_name", r.message.employee_name);
                }
            });
        }

        if (frm.doc.deliver_to) {
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Employee",
                    filters: { name: frm.doc.deliver_to },
                    fieldname: "employee_name"
                },
                callback: function (r) {
                    frm.set_value("del_name", r.message.employee_name);
                }
            });
        }

        if (frm.doc.authorized_by) {
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Employee",
                    filters: { name: frm.doc.authorized_by },
                    fieldname: "employee_name"
                },
                callback: function (r) {
                    frm.set_value("auth_name", r.message.employee_name);
                }
            });
        }
    },




    asset: function (frm) {
        frm.set_value("parts_requisition", null);
        apply_parts_requisition_filter(frm);

        if (!frm.doc.asset) {
            frm.set_value("machine_hours", null);
            return;
        }

        frappe.call({
            method: "procurement.procurement.doctype.purchase_requisition.purchase_requisition.get_latest_machine_hours_for_asset",
            args: {
                asset: frm.doc.asset
            },
            callback: function (r) {
                if (r.message !== null && r.message !== undefined) {
                    frm.set_value("machine_hours", r.message);
                }
            }
        });
    },

    account: function (frm) {
        apply_item_account_filter(frm);
    },

    parts_requisition: function (frm) {
        if (!frm.doc.parts_requisition) {
            return;
        }

        frappe.call({
            method: "procurement.procurement.doctype.purchase_requisition.purchase_requisition.get_parts_requisition_items",
            args: {
                parts_requisition: frm.doc.parts_requisition
            },
            callback: function (r) {
                frm.clear_table("item_list");

                (r.message || []).forEach(function (part) {
                    let row = frm.add_child("item_list");

                    row.qty = part.qty;
                    row.item = part.item_code;
                    row.item_group = part.item_group;
                    row.description_and_part_no = [part.part_name, part.part_no].filter(Boolean).join(" - ");
                    row.unit_price = 0;
                    row.total_cost = 0;
                });

                frm.refresh_field("item_list");
                calculate_totals(frm);
            }
        });
    },


    site_code: function (frm) {
        frm.set_value("parts_requisition", null);
        apply_parts_requisition_filter(frm);

        if (frm.doc.site_code) {
            // Fetch the location from the linked Site Code document
            frappe.db.get_value('Site Code', frm.doc.site_code, 'location', (r) => {
                if (r && r.location) {
                    // Set the location field in the Purchase Requisition document
                    frm.set_value('location', r.location);
                    frm.set_value('asset', null);
                    apply_asset_location_filter(frm);
                }
            });
        
            // Fetch Buyer using custom server-side method
            frappe.call({
                method: "procurement.procurement.doctype.purchase_requisition.purchase_requisition.get_buyer_for_site",
                args: { site_code: frm.doc.site_code },
                callback: function(response) {
                    if (response.message) {
                        frm.set_value("buyer", response.message);
                    } else {
                        frm.set_value("buyer", null);
                    }
                }
            });
        
        } else {
            // Clear fields if site_code is not set
            frm.set_value('location', null);
            frm.set_value('buyer', null);
        }
    }
});

frappe.ui.form.on('Purchase Requisition List', {
    qty: function(frm, cdt, cdn) {
        update_row_totals(frm, cdt, cdn);
    },

    unit_price: function(frm, cdt, cdn) {
        update_row_totals(frm, cdt, cdn);
    },

    item: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.item) {
            frappe.db.get_value('Item', row.item, 'item_name', (r) => {
                frappe.model.set_value(cdt, cdn, 'description_and_part_no', r.item_name);
            });
        }
    }
});

function update_row_totals(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    row.total_cost = row.qty * row.unit_price;
    frm.refresh_field('item_list');
    calculate_totals(frm);
}

function calculate_total_cost(frm) {
    frm.doc.item_list.forEach(row => {
        row.total_cost = row.qty * row.unit_price;
    });
    frm.refresh_field('item_list');
}

function calculate_totals(frm) {
    let subtotal = 0;
    frm.doc.item_list.forEach(row => {
        subtotal += row.total_cost;
    });
    frm.set_value('subtotal', subtotal);

    let vat = subtotal * 0.15;
    frm.set_value('vat', vat);

    frm.set_value('total', subtotal + vat);
}

function apply_item_account_filter(frm) {
    frm.set_query("item", "item_list", function () {
        if (!frm.doc.account) {
            return {};
        }

        return {
            query: "procurement.procurement.doctype.purchase_requisition.purchase_requisition.get_items_by_expense_account",
            filters: {
                expense_account: frm.doc.account
            }
        };
    });
}


function apply_asset_location_filter(frm) {
    frm.set_query("asset", function () {
        return {
            filters: {
                docstatus: 1,
                location: frm.doc.location || ""
            }
        };
    });
}

function apply_buyer_role_filter(frm) {
    // link_filters on this field used to read ["User", "role", "=", "Procurement
    // Admin"] - that's parsed entirely client-side and can only ever filter a
    // plain column on User itself, never an actually assigned Role (which
    // lives in the "Has Role" child table), so it silently matched nobody.
    // See filter_users_by_role's own docstring for the full explanation.
    frm.set_query("buyer", function () {
        return {
            query: "procurement.procurement.utils.filter_users_by_role",
            filters: {
                roles: ["Procurement Admin"]
            }
        };
    });
}

function apply_parts_requisition_filter(frm) {
    frm.set_query("parts_requisition", function () {
        return {
            query: "procurement.procurement.doctype.purchase_requisition.purchase_requisition.get_available_parts_requisitions",
            filters: {
                site_code: frm.doc.site_code,
                asset: frm.doc.asset,
                current_purchase_requisition: frm.doc.name
            }
        };
    });
}