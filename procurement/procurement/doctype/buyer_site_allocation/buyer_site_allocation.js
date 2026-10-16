// Copyright (c) 2025, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Buyer Site Allocation", {
    onload: function(frm) {
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
    },

    refresh: function(frm) {

    },
});

frappe.ui.form.on('Site Code List', {
    site_code: function(frm, cdt, cdn) {
        let row = frappe.get_doc(cdt, cdn);
        if (row.site_code) {
            frappe.db.get_value('Site Code', row.site_code, 'location', function(data) {
                if (data && data.location) {
                    frappe.model.set_value(cdt, cdn, 'location', data.location);
                }
            });
        }
    }
});