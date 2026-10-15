// Copyright (c) 2026, Isambane Mining (Pty) Ltd and contributors
// For license information, please see license.txt

frappe.pages["sla-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Contractor SLA Dashboard"),
		single_column: true,
	});
	wrapper.sla_dashboard = new SLADashboard(page);
};

frappe.pages["sla-dashboard"].on_page_show = function (wrapper) {
	wrapper.sla_dashboard && wrapper.sla_dashboard.refresh();
};

const SLA_STATUS_COLORS = {
	Outstanding: "orange",
	Upcoming: "blue",
	Active: "green",
	"Expiring Soon": "yellow",
	Expired: "red",
	Renewed: "purple",
	Terminated: "red",
};

class SLADashboard {
	constructor(page) {
		this.page = page;
		this.filters = {};
		this.inject_styles();
		this.make_filters();
		this.page.set_primary_action(__("New SLA"), () => frappe.new_doc("Contractor SLA"), "add");
		this.page.add_inner_button(__("SLA Register"), () =>
			frappe.set_route("query-report", "Contractor SLA Register")
		);
		this.page.add_inner_button(__("All SLAs"), () => frappe.set_route("List", "Contractor SLA"));
		this.$body = $('<div class="sla-dash"></div>').appendTo(this.page.main);
	}

	make_filters() {
		[
			{ fieldname: "company", label: __("Company"), options: "Company" },
			{ fieldname: "supplier", label: __("Contractor"), options: "Supplier" },
			{ fieldname: "branch", label: __("Site"), options: "Branch" },
		].forEach((df) =>
			this.page.add_field({
				...df,
				fieldtype: "Link",
				change: () => {
					const value = this.page.fields_dict[df.fieldname].get_value();
					if ((this.filters[df.fieldname] || "") === (value || "")) return;
					this.filters[df.fieldname] = value;
					this.refresh();
				},
			})
		);
	}

	refresh() {
		frappe
			.xcall("procurement.procurement.page.sla_dashboard.sla_dashboard.get_dashboard_data", this.filters)
			.then((data) => this.render(data));
	}

	render(data) {
		this.data = data;
		const c = data.counts;
		this.$body.html(`
			<div class="sla-tiles"></div>
			<div class="sla-card sla-chart-card">
				<div class="sla-card-head">
					<div>
						<div class="sla-card-title">${__("Current SLAs ending, next 12 months")}</div>
						<div class="sla-card-sub">${__("Plan renewals before the {0}-day warning window opens.", [
							data.warning_days,
						])}</div>
					</div>
				</div>
				<div class="sla-chart"></div>
			</div>
			<div class="sla-section" data-section="expiring"></div>
			<div class="sla-section" data-section="outstanding"></div>
			<div class="sla-section" data-section="non_conformances"></div>
			<div class="sla-section" data-section="expired"></div>
			<div class="sla-section" data-section="current"></div>
		`);

		const tiles = [
			{ label: __("Active"), value: c.Active, color: "green", status: "Active" },
			{
				label: __("Expiring within {0} days", [data.warning_days]),
				value: c["Expiring Soon"],
				color: "yellow",
				status: "Expiring Soon",
			},
			{ label: __("Awaiting Signature"), value: c.Outstanding, color: "orange", status: "Outstanding" },
			{ label: __("Upcoming"), value: c.Upcoming, color: "blue", status: "Upcoming" },
			{ label: __("Expired, not renewed"), value: c.Expired, color: "red", status: "Expired" },
			{
				label: __("Open non-conformances"),
				value: data.non_conformances.length,
				color: "orange",
				route: ["List", "Contractor Non-Conformance", { docstatus: 0 }],
				hint: data.remediation_overdue ? __("{0} remediation overdue", [data.remediation_overdue]) : "",
			},
			{
				label: __("Warnings in force"),
				value: data.warnings_in_force,
				color: "orange",
				route: ["List", "Contractor Warning", { status: "Active" }],
			},
			{
				label: __("Monthly value in force"),
				value: format_currency(data.monthly_value, "ZAR", 0),
				money: true,
				color: "gray",
				hint: __("Signed SLAs only"),
			},
		];
		const $tiles = this.$body.find(".sla-tiles");
		tiles.forEach((tile) => {
			const $tile = $(`
				<div class="sla-tile ${tile.status || tile.route ? "sla-clickable" : ""}">
					<div class="sla-tile-label"><span class="indicator ${tile.color}"></span>${tile.label}</div>
					<div class="sla-tile-value ${tile.money ? "sla-money" : ""}">${tile.value ?? 0}</div>
					${tile.hint ? `<div class="sla-tile-hint">${tile.hint}</div>` : ""}
				</div>`).appendTo($tiles);
			if (tile.status) {
				$tile.on("click", () =>
					frappe.set_route("List", "Contractor SLA", { status: tile.status, ...this.list_filters() })
				);
			} else if (tile.route) {
				$tile.on("click", () => frappe.set_route(...tile.route));
			}
		});

		this.render_chart(data.expiry_by_month);
		this.render_table("expiring", __("Expiring soon"), data.expiring, "expiry", __("Nothing expires in the warning window."));
		this.render_table(
			"outstanding",
			__("Awaiting signature"),
			data.outstanding,
			"unsigned",
			__("Nothing is waiting for signature.")
		);
		this.render_cases(data.non_conformances);
		this.render_table(
			"expired",
			__("Expired in the last 90 days, not renewed"),
			data.expired,
			"expiry",
			__("No recently expired SLAs.")
		);
		this.render_table("current", __("All current SLAs"), data.current, "expiry", __("No current SLAs."));
		if (data.drafts) {
			this.$body
				.find('[data-section="current"]')
				.append(
					`<p class="sla-card-sub sla-drafts"><a href="/desk/contractor-sla?status=Draft">${__(
						"{0} draft SLA(s) not yet submitted",
						[data.drafts]
					)}</a></p>`
				);
		}
	}

	list_filters() {
		return Object.fromEntries(Object.entries(this.filters).filter(([, v]) => v));
	}

	render_cases(cases) {
		const $section = this.$body.find('[data-section="non_conformances"]');
		const esc = frappe.utils.escape_html;
		const body = cases
			.map(
				(c) => `<tr>
					<td><a href="/desk/contractor-non-conformance/${encodeURIComponent(c.name)}">${esc(c.name)}</a></td>
					<td>${esc(c.supplier_name || c.supplier)}<div class="sla-muted">${esc(c.contractor_sla)}</div></td>
					<td class="sla-hide-sm">${esc(c.category || "")}</td>
					<td class="sla-hide-sm">${esc(c.severity || "")}</td>
					<td>${esc(__(c.status))}${c.warning_level ? `<div class="sla-muted">${esc(c.warning_level)}</div>` : ""}</td>
					<td class="sla-hide-sm">${c.remediation_due_date ? frappe.datetime.str_to_user(c.remediation_due_date) : "&ndash;"}</td>
					<td class="sla-num ${c.days_overdue ? "sla-urgent" : ""}">${c.days_overdue ?? "&ndash;"}</td>
				</tr>`
			)
			.join("");
		$section.html(`
			<div class="sla-card">
				<div class="sla-card-head"><div class="sla-card-title">${__("Open non-conformances")}
					<span class="sla-count">${cases.length}</span></div></div>
				${
					cases.length
						? `<div class="sla-table-wrap"><table class="sla-dash-table"><thead><tr>
							<th>${__("Case")}</th><th>${__("Contractor")}</th><th class="sla-hide-sm">${__("Category")}</th>
							<th class="sla-hide-sm">${__("Severity")}</th><th>${__("Stage")}</th>
							<th class="sla-hide-sm">${__("Remediate By")}</th><th class="sla-num">${__("Days overdue")}</th>
						</tr></thead><tbody>${body}</tbody></table></div>`
						: `<p class="sla-empty">${__("No open non-conformances.")}</p>`
				}
			</div>`);
	}

	render_chart(series) {
		const $chart = this.$body.find(".sla-chart");
		if (!series.values.some(Boolean)) {
			$chart.html(`<p class="sla-empty">${__("No current SLA ends in the next 12 months.")}</p>`);
			return;
		}
		new frappe.Chart($chart[0], {
			type: "bar",
			height: 220,
			data: { labels: series.labels, datasets: [{ name: __("SLAs ending"), values: series.values }] },
			colors: ["blue"],
			barOptions: { spaceRatio: 0.5 },
			axisOptions: { xAxisMode: "tick", yAxisMode: "span", xIsSeries: true },
			tooltipOptions: { formatTooltipY: (v) => __("{0} SLA(s)", [v]) },
		});
	}

	render_table(section, title, rows, mode, empty) {
		const $section = this.$body.find(`[data-section="${section}"]`);
		const day_col = mode === "unsigned" ? __("Days unsigned") : __("Days to expiry");
		const body = rows
			.map((r) => {
				const days = mode === "unsigned" ? r.days_unsigned : r.days_to_expiry;
				const urgent =
					mode === "unsigned" ? days >= 14 : days != null && days <= Math.min(30, this.data.warning_days);
				return `<tr>
					<td><a href="/desk/contractor-sla/${encodeURIComponent(r.name)}">${frappe.utils.escape_html(r.name)}</a></td>
					<td>${frappe.utils.escape_html(r.supplier_name || r.supplier)}<div class="sla-muted">${frappe.utils.escape_html(
					r.sla_title
				)}</div></td>
					<td class="sla-hide-sm">${frappe.utils.escape_html(r.branch || "")}</td>
					<td><span class="indicator-pill ${SLA_STATUS_COLORS[r.status] || "gray"}">${__(r.status)}</span>${
					r.status === "Outstanding"
						? `<div class="sla-muted">${__(r.signature_status)}</div>`
						: ""
				}</td>
					<td class="sla-hide-sm">${r.end_date ? frappe.datetime.str_to_user(r.end_date) : __("Open-ended")}</td>
					<td class="sla-num ${urgent ? "sla-urgent" : ""}">${days ?? "&ndash;"}</td>
					<td class="sla-num sla-hide-sm">${format_currency(r.total_monthly_value, "ZAR", 0)}</td>
					<td class="sla-hide-sm">${frappe.utils.escape_html(r.responsible_manager_name || "")}</td>
				</tr>`;
			})
			.join("");
		$section.html(`
			<div class="sla-card">
				<div class="sla-card-head"><div class="sla-card-title">${title}
					<span class="sla-count">${rows.length}</span></div></div>
				${
					rows.length
						? `<div class="sla-table-wrap"><table class="sla-dash-table">
							<thead><tr>
								<th>${__("SLA")}</th><th>${__("Contractor")}</th><th class="sla-hide-sm">${__("Site")}</th>
								<th>${__("Status")}</th><th class="sla-hide-sm">${__("End")}</th>
								<th class="sla-num">${day_col}</th><th class="sla-num sla-hide-sm">${__("Monthly")}</th>
								<th class="sla-hide-sm">${__("Responsible")}</th>
							</tr></thead><tbody>${body}</tbody></table></div>`
						: `<p class="sla-empty">${empty}</p>`
				}
			</div>`);
	}

	inject_styles() {
		if (document.getElementById("sla-dashboard-styles")) return;
		$(`<style id="sla-dashboard-styles">
			.sla-dash { display: flex; flex-direction: column; gap: 16px; padding: 0 15px 32px; }
			.sla-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
			.sla-tile, .sla-card { background: var(--card-bg); border: 1px solid var(--border-color);
				border-radius: var(--border-radius-lg); }
			.sla-tile { padding: 14px 16px; }
			.sla-tile.sla-clickable { cursor: pointer; }
			.sla-tile.sla-clickable:hover { border-color: var(--gray-400); }
			.sla-tile-label { font-size: var(--text-sm); color: var(--text-muted); display: flex; align-items: center; }
			.sla-tile-value { font-size: 26px; font-weight: 600; color: var(--text-color); margin-top: 6px;
				font-variant-numeric: tabular-nums; white-space: nowrap; }
			.sla-tile-value.sla-money { font-size: 20px; }
			.sla-tile-hint { font-size: var(--text-xs); color: var(--text-light); }
			.sla-card { padding: 14px 16px; }
			.sla-card-title { font-weight: 600; color: var(--text-color); }
			.sla-card-sub, .sla-muted { font-size: var(--text-sm); color: var(--text-muted); }
			.sla-count { margin-left: 6px; font-weight: 400; color: var(--text-muted); }
			.sla-empty { color: var(--text-muted); margin: 12px 0 0; }
			.sla-table-wrap { overflow-x: auto; margin-top: 8px; }
			.sla-dash-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
			.sla-dash-table th { color: var(--text-muted); font-weight: 500; text-align: left; padding: 6px 8px;
				border-bottom: 1px solid var(--border-color); white-space: nowrap; }
			.sla-dash-table td { padding: 8px; border-bottom: 1px solid var(--border-color); vertical-align: top; }
			.sla-dash-table tr:last-child td { border-bottom: none; }
			.sla-dash-table .sla-num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
			.sla-dash-table .sla-urgent { color: var(--red-600); font-weight: 600; }
			.sla-drafts { margin: 8px 0 0; }
			@media (max-width: 640px) { .sla-hide-sm { display: none; } }
		</style>`).appendTo(document.head);
	}
}
