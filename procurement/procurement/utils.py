import frappe

def check_app_permission():
    """Check if the user has permission to access the app (for showing it on the app screen)"""
    # Administrator always has access
    if frappe.session.user == "Administrator":
        return True

    # Check if the user has any of the required roles
    required_roles = ["System Manager", "Procurement Admin", "Procurement User"]
    user_roles = frappe.get_roles(frappe.session.user)

    # Grant access if the user has at least one of the required roles
    if any(role in user_roles for role in required_roles):
        return True

    return False


@frappe.whitelist()
def filter_users_by_role(doctype, txt, searchfield, start, page_len, filters):
    """Link-field query for "who can be picked here" fields (e.g. Buyer) that
    need to filter User by an actually ASSIGNED role.

    This can't be done through the field's own `link_filters` property: that
    JSON is parsed entirely client-side (see the Link control's own
    `parse_filters`), which discards the "doctype" element of every
    [doctype, fieldname, op, value] triple before it ever reaches the server
    - so a filter like ["Has Role", "role", "in", [...]] silently collapses
    into the same filter on User's own `role` column that
    ["User", "role", "in", [...]] would have produced. That column is a
    long-dead, almost entirely unused scalar field from before roles were
    tracked via the "Has Role" child table - it is NOT what Role-based
    permissions actually use, so filtering by it (which is all
    `link_filters` can ever do here) matches nobody that doesn't happen to
    have that legacy field manually set. A real role filter needs a genuine
    Has Role join, which only a server-side query can do - hence this
    function, wired up via `frm.set_query()` instead.
    """
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    roles = filters.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if not roles:
        return []

    query_filters = [
        ["Has Role", "role", "in", roles],
        ["User", "enabled", "=", 1],
    ]
    if txt:
        query_filters.append(["User", searchfield or "name", "like", f"%{txt}%"])

    return frappe.get_list(
        "User",
        filters=query_filters,
        fields=["name", "full_name"],
        limit_start=start,
        limit_page_length=page_len,
        order_by="name asc",
        as_list=True,
        distinct=True,
    )
