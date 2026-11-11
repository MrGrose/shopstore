/* PadelGMarket Admin — tabs, segmented controls, list selection, bulk bar */

function initTabs(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-tabs]").forEach((group) => {
    if (group.dataset.tabsBound === "1") return;
    group.dataset.tabsBound = "1";
    group.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-tab]");
      if (!btn) return;
      group.querySelectorAll("button[data-tab]").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      const target = group.getAttribute("data-tabs-target");
      const panelHost = target ? document.querySelector(target) : null;
      const name = btn.getAttribute("data-tab");
      if (panelHost) {
        panelHost.querySelectorAll("[data-panel]").forEach((pn) => {
          pn.style.display = pn.getAttribute("data-panel") === name ? "" : "none";
        });
      }
    });
  });
}

function initSeg(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-seg]").forEach((group) => {
    if (group.dataset.segBound === "1") return;
    group.dataset.segBound = "1";
    group.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn || btn.closest("[data-seg]") !== group) return;
      group.querySelectorAll("button").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      group.dispatchEvent(new CustomEvent("seg:change", { detail: btn.dataset.value }));
    });
  });
}

function initListSelect(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-list]").forEach((list) => {
    if (list.dataset.listBound === "1") return;
    list.dataset.listBound = "1";
    list.addEventListener("click", (e) => {
      const row = e.target.closest(".lrow");
      if (!row) return;
      list.querySelectorAll(".lrow").forEach((r) => r.classList.remove("is-active"));
      row.classList.add("is-active");
    });
  });
}

function adminProductsSyncSearchUrl() {
  const input = document.getElementById("admin-products-search-input");
  const q = (input?.value || "").trim();
  const qField = document.getElementById("admin-products-q");
  if (qField) qField.value = q;
  const url = new URL(window.location.href);
  if (q) url.searchParams.set("q", q);
  else url.searchParams.delete("q");
  history.replaceState({}, "", url.pathname + url.search);
}

function adminProductsBeforeSearchRequest(event) {
  const q = (document.getElementById("admin-products-search-input")?.value || "").trim();
  adminProductsSetRequestParam(event, "q", q);
  adminProductsSetRequestParam(event, "page", "1");
  const qField = document.getElementById("admin-products-q");
  if (qField) qField.value = q;
  const pageField = document.getElementById("admin-products-page");
  if (pageField) pageField.value = "1";
  adminProductsSyncSearchUrl();
  const clearBtn = document.getElementById("admin-products-search-clear");
  if (clearBtn) clearBtn.hidden = !q;
}

function adminProductsBeforeClearSearchRequest(event) {
  adminProductsSetRequestParam(event, "q", "");
  adminProductsSetRequestParam(event, "page", "1");
  const input = document.getElementById("admin-products-search-input");
  if (input) input.value = "";
  const qField = document.getElementById("admin-products-q");
  if (qField) qField.value = "";
  const pageField = document.getElementById("admin-products-page");
  if (pageField) pageField.value = "1";
  adminProductsSyncSearchUrl();
  const clearBtn = document.getElementById("admin-products-search-clear");
  if (clearBtn) clearBtn.hidden = true;
}

function adminProductsSetRequestParam(event, name, value) {
  const params = event.detail.parameters;
  const text = value == null ? "" : String(value);
  if (params instanceof URLSearchParams) {
    if (!text) params.delete(name);
    else params.set(name, text);
    return;
  }
  if (!params || typeof params !== "object") return;
  if (!text) delete params[name];
  else params[name] = text;
}

function adminProductsBeforeTopChange(event) {
  const top = event.detail.elt?.value;
  if (!top) return;
  adminProductsSetRequestParam(event, "top", top);
  adminProductsSetRequestParam(event, "page", "1");
  adminProductsSetRequestParam(event, "category", "");
  const topField = document.getElementById("admin-products-top");
  if (topField) topField.value = top;
  const pageField = document.getElementById("admin-products-page");
  if (pageField) pageField.value = "1";
  const catHidden = document.querySelector("#admin-products-filters input[name='category']");
  if (catHidden) catHidden.remove();
}

function adminProductsSyncTreeUrl(inclusion, site, reason) {
  const url = new URL(window.location.href);
  if (inclusion && inclusion !== "included") url.searchParams.set("inclusion", inclusion);
  else url.searchParams.delete("inclusion");
  if (site && site !== "visible") url.searchParams.set("site", site);
  else url.searchParams.delete("site");
  if (reason && reason !== "all") url.searchParams.set("reason", reason);
  else url.searchParams.delete("reason");
  url.searchParams.delete("nav_status");
  url.searchParams.delete("supplier_limit");
  history.replaceState({}, "", url.pathname + url.search);
}

function adminProductsApplyTree(event, inclusion, site, reason) {
  adminProductsSetRequestParam(event, "inclusion", inclusion);
  adminProductsSetRequestParam(event, "site", site);
  adminProductsSetRequestParam(event, "reason", reason);
  adminProductsSetRequestParam(event, "page", "1");
  const inclusionField = document.getElementById("admin-products-inclusion");
  if (inclusionField) inclusionField.value = inclusion;
  const siteField = document.getElementById("admin-products-site");
  if (siteField) siteField.value = site;
  const reasonField = document.getElementById("admin-products-reason");
  if (reasonField) reasonField.value = reason;
  const pageField = document.getElementById("admin-products-page");
  if (pageField) pageField.value = "1";
  adminProductsSyncTreeUrl(inclusion, site, reason);
}

function adminProductsBeforeInclusionChange(event, inclusion) {
  adminProductsApplyTree(event, inclusion, "all", "all");
}

function adminProductsBeforeSiteChange(event, site) {
  adminProductsApplyTree(event, "included", site, "all");
}

function adminProductsBeforeReasonChange(event, reason) {
  adminProductsApplyTree(event, "included", "not_visible", reason);
}

function adminProductsBeforePageChange(event, page) {
  const nextPage = String(page);
  adminProductsSetRequestParam(event, "page", nextPage);
  const pageField = document.getElementById("admin-products-page");
  if (pageField) pageField.value = nextPage;
}


function adminOrdersGetSelectedStatuses() {
  return Array.from(document.querySelectorAll(".admin-filter-pill[data-status]"))
    .filter((el) => el.dataset.status && el.classList.contains("is-active"))
    .map((el) => el.dataset.status);
}

function adminOrdersSetStatusFilter(statuses) {
  const field = document.getElementById("orders-status-filter");
  if (field) field.value = statuses.join(",");
  document.querySelectorAll(".admin-filter-pill").forEach((el) => {
    const code = el.dataset.status;
    if (!code) {
      el.classList.toggle("is-active", statuses.length === 0);
      return;
    }
    el.classList.toggle("is-active", statuses.includes(code));
  });
}


const adminOrdersDeleteSelection = new Set();

function adminOrdersOpenRow(event, row) {
  if (event.target.closest("[data-order-delete-checkbox], .orders-table__check")) return;
  if (event.target.closest(".orders-table__support-link")) return;
  const href = row?.dataset?.href;
  if (href) window.location.assign(href);
}

function adminOrdersRowKeydown(event, row) {
  if (event.key !== "Enter" && event.key !== " ") return;
  if (event.target.closest("[data-order-delete-checkbox]")) return;
  event.preventDefault();
  adminOrdersOpenRow(event, row);
}

function adminOrdersUpdateDeleteBar() {
  const btn = document.getElementById("admin-orders-delete-btn");
  const countEl = document.getElementById("admin-orders-delete-count");
  if (!btn) return;
  const count = adminOrdersDeleteSelection.size;
  btn.hidden = count === 0;
  if (countEl) countEl.textContent = String(count);
}

function adminOrdersSyncDeleteCheckboxes(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-order-delete-checkbox]").forEach((cb) => {
    const id = Number(cb.value);
    cb.checked = adminOrdersDeleteSelection.has(id);
  });
  adminOrdersSyncSelectAllState(scope);
  adminOrdersUpdateDeleteBar();
}

function adminOrdersSyncSelectAllState(root) {
  const scope = root || document;
  const master = scope.querySelector("[data-orders-select-all]");
  if (!master) return;
  const boxes = Array.from(scope.querySelectorAll("[data-order-delete-checkbox]"));
  if (!boxes.length) {
    master.checked = false;
    master.indeterminate = false;
    return;
  }
  const checkedCount = boxes.filter((cb) => cb.checked).length;
  master.checked = checkedCount === boxes.length;
  master.indeterminate = checkedCount > 0 && checkedCount < boxes.length;
}

function adminOrdersToggleDeleteCheckbox(cb) {
  const id = Number(cb.value);
  if (!Number.isFinite(id) || id <= 0) return;
  if (cb.checked) adminOrdersDeleteSelection.add(id);
  else adminOrdersDeleteSelection.delete(id);
  adminOrdersSyncSelectAllState(cb.closest(".orders-table-wrap"));
  adminOrdersUpdateDeleteBar();
}

function adminOrdersToggleDeleteSelectAll(master, root) {
  const scope = root || document;
  scope.querySelectorAll("[data-order-delete-checkbox]").forEach((cb) => {
    cb.checked = master.checked;
    const id = Number(cb.value);
    if (!Number.isFinite(id) || id <= 0) return;
    if (master.checked) adminOrdersDeleteSelection.add(id);
    else adminOrdersDeleteSelection.delete(id);
  });
  master.indeterminate = false;
  adminOrdersUpdateDeleteBar();
}

let adminOrdersFlashTimeout = null;

function adminOrdersShowFlash(message, isError = false) {
  const el = document.getElementById("admin-orders-flash");
  if (!el) return;
  if (adminOrdersFlashTimeout) {
    clearTimeout(adminOrdersFlashTimeout);
    adminOrdersFlashTimeout = null;
  }
  el.textContent = message;
  el.classList.toggle("is-error", !!isError);
  el.hidden = false;
  adminOrdersFlashTimeout = setTimeout(() => {
    el.hidden = true;
    adminOrdersFlashTimeout = null;
  }, 3000);
}

async function adminOrdersSubmitDelete(ids) {
  const formData = new FormData();
  ids.forEach((id) => formData.append("order_ids", String(id)));
  try {
    const resp = await fetch("/internal/admin/orders/delete-selected", {
      method: "POST",
      body: formData,
      credentials: "same-origin",
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Ошибка удаления");
    ids.forEach((id) => adminOrdersDeleteSelection.delete(id));
    adminOrdersShowFlash(data.message || "Готово");
    adminOrdersReloadTable();
  } catch (err) {
    adminOrdersShowFlash(err?.message || "Ошибка удаления", true);
  }
}

function adminOrdersDeleteSelected() {
  const ids = Array.from(adminOrdersDeleteSelection);
  if (!ids.length) return;
  const preview = ids.slice(0, 8).map((id) => `#${id}`).join(", ");
  const suffix = ids.length > 8 ? ` и ещё ${ids.length - 8}` : "";
  adminOpenConfirm({
    title: "Удалить заказы",
    message: `Безвозвратно удалить ${ids.length} заказ(ов): ${preview}${suffix}?`,
    confirmLabel: "Удалить",
    onConfirm: () => adminOrdersSubmitDelete(ids),
  });
}

function initAdminOrdersDeleteButton() {
  const btn = document.getElementById("admin-orders-delete-btn");
  if (!btn || btn.dataset.bound === "1") return;
  btn.dataset.bound = "1";
  btn.addEventListener("click", adminOrdersDeleteSelected);
}

function initAdminOrdersBulkDelete(root) {
  const tableHost = document.getElementById("admin-orders-table");
  if (!tableHost) return;
  if (tableHost.dataset.deleteUiBound !== "1") {
    tableHost.dataset.deleteUiBound = "1";
    tableHost.addEventListener("change", (event) => {
      const cb = event.target.closest("[data-order-delete-checkbox]");
      if (cb) {
        adminOrdersToggleDeleteCheckbox(cb);
        return;
      }
      const master = event.target.closest("[data-orders-select-all]");
      if (master) {
        adminOrdersToggleDeleteSelectAll(master, tableHost);
      }
    });
  }
  adminOrdersSyncDeleteCheckboxes(root || tableHost);
}


const adminSupportDeleteSelection = new Set();

function adminSupportOpenRow(event, row) {
  if (event.target.closest("[data-support-delete-checkbox], .orders-table__check")) return;
  if (event.target.closest(".orders-table__support-link")) return;
  const href = row?.dataset?.href;
  if (href) window.location.assign(href);
}

function adminSupportRowKeydown(event, row) {
  if (event.key !== "Enter" && event.key !== " ") return;
  if (event.target.closest("[data-support-delete-checkbox]")) return;
  event.preventDefault();
  adminSupportOpenRow(event, row);
}

function adminSupportUpdateDeleteBar() {
  const btn = document.getElementById("admin-support-delete-btn");
  const countEl = document.getElementById("admin-support-delete-count");
  if (!btn) return;
  const count = adminSupportDeleteSelection.size;
  btn.hidden = count === 0;
  if (countEl) countEl.textContent = String(count);
}

function adminSupportSyncDeleteCheckboxes(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-support-delete-checkbox]").forEach((cb) => {
    const id = Number(cb.value);
    cb.checked = adminSupportDeleteSelection.has(id);
  });
  adminSupportSyncSelectAllState(scope);
  adminSupportUpdateDeleteBar();
}

function adminSupportSyncSelectAllState(root) {
  const scope = root || document;
  const master = scope.querySelector("[data-support-select-all]");
  if (!master) return;
  const boxes = Array.from(scope.querySelectorAll("[data-support-delete-checkbox]"));
  if (!boxes.length) {
    master.checked = false;
    master.indeterminate = false;
    return;
  }
  const checkedCount = boxes.filter((cb) => cb.checked).length;
  master.checked = checkedCount === boxes.length;
  master.indeterminate = checkedCount > 0 && checkedCount < boxes.length;
}

function adminSupportToggleDeleteCheckbox(cb) {
  const id = Number(cb.value);
  if (!Number.isFinite(id) || id <= 0) return;
  if (cb.checked) adminSupportDeleteSelection.add(id);
  else adminSupportDeleteSelection.delete(id);
  adminSupportSyncSelectAllState(cb.closest(".orders-table-wrap"));
  adminSupportUpdateDeleteBar();
}

function adminSupportToggleDeleteSelectAll(master, root) {
  const scope = root || document;
  scope.querySelectorAll("[data-support-delete-checkbox]").forEach((cb) => {
    cb.checked = master.checked;
    const id = Number(cb.value);
    if (!Number.isFinite(id) || id <= 0) return;
    if (master.checked) adminSupportDeleteSelection.add(id);
    else adminSupportDeleteSelection.delete(id);
  });
  master.indeterminate = false;
  adminSupportUpdateDeleteBar();
}

let adminSupportFlashTimeout = null;

function adminSupportShowFlash(message, isError = false) {
  const el = document.getElementById("admin-support-flash");
  if (!el) return;
  if (adminSupportFlashTimeout) {
    clearTimeout(adminSupportFlashTimeout);
    adminSupportFlashTimeout = null;
  }
  el.textContent = message;
  el.classList.toggle("is-error", !!isError);
  el.hidden = false;
  adminSupportFlashTimeout = setTimeout(() => {
    el.hidden = true;
    adminSupportFlashTimeout = null;
  }, 3000);
}

function adminSupportReloadList(successMessage) {
  const url = new URL(window.location.href);
  url.searchParams.delete("id");
  url.searchParams.delete("error");
  if (successMessage) url.searchParams.set("success", successMessage);
  else url.searchParams.delete("success");
  window.location.assign(url.toString());
}

async function adminSupportSubmitDelete(ids) {
  const formData = new FormData();
  ids.forEach((id) => formData.append("ticket_ids", String(id)));
  try {
    const resp = await fetch("/internal/admin/support/delete-selected", {
      method: "POST",
      body: formData,
      credentials: "same-origin",
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Ошибка удаления");
    ids.forEach((id) => adminSupportDeleteSelection.delete(id));
    adminSupportReloadList(data.message || "Готово");
  } catch (err) {
    adminSupportShowFlash(err?.message || "Ошибка удаления", true);
  }
}

function adminSupportDeleteSelected() {
  const ids = Array.from(adminSupportDeleteSelection);
  if (!ids.length) return;
  const preview = ids.slice(0, 8).map((id) => `#${id}`).join(", ");
  const suffix = ids.length > 8 ? ` и ещё ${ids.length - 8}` : "";
  adminOpenConfirm({
    title: "Удалить обращения",
    message: `Безвозвратно удалить ${ids.length} обращений: ${preview}${suffix}?`,
    confirmLabel: "Удалить",
    onConfirm: () => adminSupportSubmitDelete(ids),
  });
}

function initAdminSupportDeleteButton() {
  const btn = document.getElementById("admin-support-delete-btn");
  if (!btn || btn.dataset.bound === "1") return;
  btn.dataset.bound = "1";
  btn.addEventListener("click", adminSupportDeleteSelected);
}

function initAdminSupportBulkDelete(root) {
  const tableHost = document.getElementById("admin-support-table");
  if (!tableHost) return;
  if (tableHost.dataset.deleteUiBound !== "1") {
    tableHost.dataset.deleteUiBound = "1";
    tableHost.addEventListener("change", (event) => {
      const cb = event.target.closest("[data-support-delete-checkbox]");
      if (cb) {
        adminSupportToggleDeleteCheckbox(cb);
        return;
      }
      const master = event.target.closest("[data-support-select-all]");
      if (master) {
        adminSupportToggleDeleteSelectAll(master, tableHost);
      }
    });
  }
  adminSupportSyncDeleteCheckboxes(root || tableHost);
}


function adminOrdersReloadTable() {
  const form = document.getElementById("admin-orders-filters");
  if (!form || typeof htmx === "undefined") return;
  htmx.ajax("GET", "/internal/admin/orders/table", {
    target: "#admin-orders-table",
    swap: "innerHTML",
    values: new FormData(form),
  });
}

function adminOrdersToggleStatusPill(btn, event) {
  event.preventDefault();
  const code = btn.dataset.status;
  let selected;
  if (!code) {
    selected = [];
  } else {
    selected = adminOrdersGetSelectedStatuses();
    const idx = selected.indexOf(code);
    if (idx >= 0) selected.splice(idx, 1);
    else selected.push(code);
  }
  adminOrdersSetStatusFilter(selected);
  const queueField = document.getElementById("orders-queue-filter");
  if (queueField) queueField.value = "";
  const pageField = document.getElementById("admin-orders-page");
  if (pageField) pageField.value = "1";
  adminOrdersSyncUrl();
  adminOrdersReloadTable();
}

function adminOrdersBeforePageChange(event, page) {
  const nextPage = String(page);
  if (event?.detail?.parameters) {
    event.detail.parameters.page = nextPage;
  }
  const pageField = document.getElementById("admin-orders-page");
  if (pageField) pageField.value = nextPage;
  adminOrdersSyncUrl();
}

function adminOrdersSyncUrl(formId = "admin-orders-filters") {
  const form = document.getElementById(formId);
  if (!form) return;
  const url = new URL(window.location.href);
  const params = new URLSearchParams(url.search);
  const orderId = params.get("id");
  url.search = "";
  const next = new URLSearchParams();
  if (orderId) next.set("id", orderId);
  const page = form.querySelector('[name="page"]')?.value || "1";
  next.set("page", page);
  const q = (form.querySelector('[name="q"]')?.value || "").trim();
  if (q) next.set("q", q);
  const status = (form.querySelector('[name="status"]')?.value || "").trim();
  if (status) next.set("status", status);
  const queue = (form.querySelector('[name="queue"]')?.value || "").trim();
  if (queue) next.set("queue", queue);
  const dateFrom = (form.querySelector('[name="date_from"]')?.value || "").trim();
  if (dateFrom) next.set("date_from", dateFrom);
  const dateTo = (form.querySelector('[name="date_to"]')?.value || "").trim();
  if (dateTo) next.set("date_to", dateTo);
  const paidFrom = (form.querySelector('[name="paid_from"]')?.value || "").trim();
  if (paidFrom) next.set("paid_from", paidFrom);
  const paidTo = (form.querySelector('[name="paid_to"]')?.value || "").trim();
  if (paidTo) next.set("paid_to", paidTo);
  const qs = next.toString();
  history.replaceState({}, "", `${url.pathname}${qs ? `?${qs}` : ""}${url.hash}`);
}

function adminFinanceSyncUrl(formId = "admin-finance-filters") {
  const form = document.getElementById(formId);
  if (!form) return;
  const url = new URL(window.location.href);
  url.search = "";
  const next = new URLSearchParams();
  const dateFrom = (form.querySelector('[name="date_from"]')?.value || "").trim();
  if (dateFrom) next.set("date_from", dateFrom);
  const dateTo = (form.querySelector('[name="date_to"]')?.value || "").trim();
  if (dateTo) next.set("date_to", dateTo);
  const group = (form.querySelector('[name="group"]')?.value || "day").trim();
  if (group) next.set("group", group);
  const qs = next.toString();
  history.replaceState({}, "", `${url.pathname}${qs ? `?${qs}` : ""}${url.hash}`);
}

const ADMIN_DATE_RANGE_MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];
const ADMIN_DATE_RANGE_WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

function adminDateRangeParseIso(iso) {
  if (!iso) return null;
  const parts = iso.split("-");
  if (parts.length !== 3) return null;
  return {
    year: Number(parts[0]),
    month: Number(parts[1]) - 1,
    day: Number(parts[2]),
  };
}

function adminDateRangeDaysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate();
}

function adminDateRangeMonthEndIso(year, month) {
  return adminDateRangeIsoFromParts(year, month, adminDateRangeDaysInMonth(year, month));
}

function adminDateRangeMonthKey(year, month) {
  return year * 12 + month;
}

function adminDateRangeIsMonthAligned(fromIso, toIso) {
  if (!fromIso || !toIso) return false;
  const from = adminDateRangeParseIso(fromIso);
  const to = adminDateRangeParseIso(toIso);
  if (!from || !to) return false;
  if (from.day !== 1) return false;
  return to.day === adminDateRangeDaysInMonth(to.year, to.month);
}

function adminDateRangeFormatMonthYear(year, month) {
  return `${ADMIN_DATE_RANGE_MONTHS[month]} ${year}`;
}

function adminDateRangeFormatDisplay(iso) {
  if (!iso) return "";
  const parts = iso.split("-");
  if (parts.length !== 3) return iso;
  return `${parts[2]}.${parts[1]}.${parts[0]}`;
}

function adminDateRangeCompare(a, b) {
  if (!a || !b) return 0;
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

function adminDateRangeIsoFromParts(year, month, day) {
  const y = String(year);
  const m = String(month + 1).padStart(2, "0");
  const d = String(day).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function adminDateRangeLabelText(fromIso, toIso) {
  if (!fromIso && !toIso) return "";
  const from = fromIso || toIso;
  const to = toIso || fromIso;
  if (adminDateRangeIsMonthAligned(from, to)) {
    const fromParts = adminDateRangeParseIso(from);
    const toParts = adminDateRangeParseIso(to);
    if (!fromParts || !toParts) return "";
    if (fromParts.year === toParts.year && fromParts.month === toParts.month) {
      return adminDateRangeFormatMonthYear(fromParts.year, fromParts.month);
    }
    return `${adminDateRangeFormatMonthYear(fromParts.year, fromParts.month)} — ${adminDateRangeFormatMonthYear(toParts.year, toParts.month)}`;
  }
  if (from === to) return adminDateRangeFormatDisplay(from);
  return `${adminDateRangeFormatDisplay(from)} — ${adminDateRangeFormatDisplay(to)}`;
}

function adminDateRangePositionPopover(trigger, popover) {
  popover.style.left = "0";
  popover.style.top = "calc(100% + 4px)";
  popover.style.right = "auto";
  const rect = popover.getBoundingClientRect();
  const margin = 8;
  let shiftX = 0;
  if (rect.right > window.innerWidth - margin) {
    shiftX = window.innerWidth - margin - rect.right;
  }
  if (rect.left + shiftX < margin) {
    shiftX = margin - rect.left;
  }
  if (shiftX) popover.style.left = `${shiftX}px`;
  const nextRect = popover.getBoundingClientRect();
  if (nextRect.bottom > window.innerHeight - margin) {
    const above = trigger.getBoundingClientRect().top - nextRect.height - 4;
    if (above >= margin) {
      popover.style.top = "auto";
      popover.style.bottom = "calc(100% + 4px)";
    }
  }
}

function initDateRangePicker(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-date-range-picker]").forEach((picker) => {
    if (picker.dataset.dateRangeBound === "1") return;

    const trigger = picker.querySelector("[data-date-range-trigger]");
    const popover = picker.querySelector("[data-date-range-popover]");
    const grid = picker.querySelector("[data-date-range-grid]");
    const weekdaysHost = picker.querySelector("[data-date-range-weekdays]");
    const monthSelect = picker.querySelector("[data-date-range-month]");
    const yearSelect = picker.querySelector("[data-date-range-year]");
    const applyBtn = picker.querySelector("[data-date-range-apply]");
    const resetBtn = picker.querySelector("[data-date-range-reset]");
    const labelEl = picker.querySelector("[data-date-range-label]");
    const fromInput = picker.querySelector("[data-date-range-from]");
    const toInput = picker.querySelector("[data-date-range-to]");
    const prevBtn = picker.querySelector("[data-date-range-prev]");
    const nextBtn = picker.querySelector("[data-date-range-next]");
    const modeBtns = picker.querySelectorAll("[data-date-range-mode]");
    const daysPanel = picker.querySelector("[data-date-range-days-panel]");
    const monthsPanel = picker.querySelector("[data-date-range-months-panel]");
    const monthGrid = picker.querySelector("[data-date-range-month-grid]");
    const formId = picker.dataset.formId;

    if (!trigger || !popover || !grid || !monthSelect || !yearSelect || !fromInput || !toInput) {
      return;
    }

    picker.dataset.dateRangeBound = "1";

    let appliedFrom = picker.dataset.appliedFrom || "";
    let appliedTo = picker.dataset.appliedTo || "";
    let draftFrom = appliedFrom;
    let draftTo = appliedTo;
    let pickerMode = "days";
    const today = new Date();
    let viewYear = today.getFullYear();
    let viewMonth = today.getMonth();

    if (appliedTo) {
      const p = appliedTo.split("-");
      viewYear = Number(p[0]);
      viewMonth = Number(p[1]) - 1;
    } else if (appliedFrom) {
      const p = appliedFrom.split("-");
      viewYear = Number(p[0]);
      viewMonth = Number(p[1]) - 1;
    }

    function syncAppliedDataset() {
      picker.dataset.appliedFrom = appliedFrom;
      picker.dataset.appliedTo = appliedTo;
    }

    function updateLabel() {
      if (labelEl) labelEl.textContent = adminDateRangeLabelText(appliedFrom, appliedTo);
    }

    function updateApplyState() {
      if (!applyBtn) return;
      applyBtn.disabled = !(draftFrom || draftTo);
    }

    function setPickerMode(mode) {
      pickerMode = mode === "months" ? "months" : "days";
      modeBtns.forEach((btn) => {
        const active = btn.dataset.dateRangeMode === pickerMode;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-selected", active ? "true" : "false");
      });
      if (daysPanel) daysPanel.hidden = pickerMode !== "days";
      if (monthsPanel) monthsPanel.hidden = pickerMode !== "months";
      if (monthSelect) monthSelect.hidden = pickerMode === "months";
      renderCalendar();
    }

    function fillYearMonthSelects() {
      const currentYear = new Date().getFullYear();
      yearSelect.innerHTML = "";
      for (let y = currentYear - 10; y <= currentYear + 10; y += 1) {
        const opt = document.createElement("option");
        opt.value = String(y);
        opt.textContent = String(y);
        if (y === viewYear) opt.selected = true;
        yearSelect.appendChild(opt);
      }
      monthSelect.innerHTML = "";
      ADMIN_DATE_RANGE_MONTHS.forEach((name, idx) => {
        const opt = document.createElement("option");
        opt.value = String(idx);
        opt.textContent = name;
        if (idx === viewMonth) opt.selected = true;
        monthSelect.appendChild(opt);
      });
    }

    function renderWeekdays() {
      if (!weekdaysHost) return;
      weekdaysHost.innerHTML = ADMIN_DATE_RANGE_WEEKDAYS.map(
        (day) => `<span class="admin-date-range__weekday">${day}</span>`,
      ).join("");
    }

    function dayClasses(iso) {
      const classes = ["admin-date-range__day"];
      const cmpFrom = draftFrom || draftTo;
      const cmpTo = draftTo || draftFrom;
      if (iso === cmpFrom) classes.push("is-start");
      if (iso === cmpTo) classes.push("is-end");
      if (cmpFrom && cmpTo && adminDateRangeCompare(iso, cmpFrom) > 0 && adminDateRangeCompare(iso, cmpTo) < 0) {
        classes.push("is-range");
      }
      const todayIso = adminDateRangeIsoFromParts(
        today.getFullYear(),
        today.getMonth(),
        today.getDate(),
      );
      if (iso === todayIso) classes.push("is-today");
      return classes.join(" ");
    }

    function renderGrid() {
      grid.innerHTML = "";
      const first = new Date(viewYear, viewMonth, 1);
      const startOffset = (first.getDay() + 6) % 7;
      const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
      for (let i = 0; i < startOffset; i += 1) {
        const pad = document.createElement("span");
        pad.className = "admin-date-range__day admin-date-range__day--empty";
        pad.setAttribute("aria-hidden", "true");
        grid.appendChild(pad);
      }
      for (let day = 1; day <= daysInMonth; day += 1) {
        const iso = adminDateRangeIsoFromParts(viewYear, viewMonth, day);
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = dayClasses(iso);
        btn.textContent = String(day);
        btn.dataset.dateIso = iso;
        btn.setAttribute("role", "gridcell");
        btn.setAttribute("aria-label", `${day} ${ADMIN_DATE_RANGE_MONTHS[viewMonth]} ${viewYear}`);
        btn.addEventListener("click", (event) => {
          event.stopPropagation();
          if (!draftFrom || (draftFrom && draftTo)) {
            draftFrom = iso;
            draftTo = "";
          } else if (adminDateRangeCompare(iso, draftFrom) < 0) {
            draftFrom = iso;
            draftTo = "";
          } else {
            draftTo = iso;
          }
          renderGrid();
          updateApplyState();
        });
        btn.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            btn.click();
          }
        });
        grid.appendChild(btn);
      }
    }

    function monthCellClasses(year, month) {
      const classes = ["admin-date-range__month"];
      const fromParts = adminDateRangeParseIso(draftFrom || draftTo);
      const toParts = adminDateRangeParseIso(draftTo || draftFrom);
      if (!fromParts) return classes.join(" ");
      const fromKey = adminDateRangeMonthKey(fromParts.year, fromParts.month);
      const toKey = toParts ? adminDateRangeMonthKey(toParts.year, toParts.month) : fromKey;
      const cellKey = adminDateRangeMonthKey(year, month);
      const rangeStart = Math.min(fromKey, toKey);
      const rangeEnd = Math.max(fromKey, toKey);
      if (cellKey === rangeStart) classes.push("is-start");
      if (cellKey === rangeEnd) classes.push("is-end");
      if (cellKey > rangeStart && cellKey < rangeEnd) classes.push("is-range");
      const today = new Date();
      if (year === today.getFullYear() && month === today.getMonth()) {
        classes.push("is-today");
      }
      return classes.join(" ");
    }

    function onMonthPick(year, month) {
      const monthStart = adminDateRangeIsoFromParts(year, month, 1);
      const monthEnd = adminDateRangeMonthEndIso(year, month);
      if (!draftFrom || (draftFrom && draftTo)) {
        draftFrom = monthStart;
        draftTo = "";
      } else {
        const fromParts = adminDateRangeParseIso(draftFrom);
        if (!fromParts) {
          draftFrom = monthStart;
          draftTo = "";
        } else {
          const fromKey = adminDateRangeMonthKey(fromParts.year, fromParts.month);
          const clickKey = adminDateRangeMonthKey(year, month);
          if (clickKey < fromKey) {
            draftFrom = monthStart;
            draftTo = "";
          } else {
            draftFrom = adminDateRangeIsoFromParts(fromParts.year, fromParts.month, 1);
            draftTo = monthEnd;
          }
        }
      }
      renderCalendar();
      updateApplyState();
    }

    function renderMonthGrid() {
      if (!monthGrid) return;
      monthGrid.innerHTML = "";
      ADMIN_DATE_RANGE_MONTHS.forEach((name, month) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = monthCellClasses(viewYear, month);
        btn.textContent = name;
        btn.setAttribute("role", "gridcell");
        btn.setAttribute("aria-label", `${name} ${viewYear}`);
        btn.addEventListener("click", (event) => {
          event.stopPropagation();
          onMonthPick(viewYear, month);
        });
        btn.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            btn.click();
          }
        });
        monthGrid.appendChild(btn);
      });
    }

    function renderCalendar() {
      fillYearMonthSelects();
      if (pickerMode === "months") {
        renderMonthGrid();
      } else {
        renderWeekdays();
        renderGrid();
      }
      updateApplyState();
    }

    function closePopover(revertDraft = true) {
      popover.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      if (revertDraft) {
        draftFrom = appliedFrom;
        draftTo = appliedTo;
        renderCalendar();
      }
    }

    function openPopover() {
      draftFrom = appliedFrom;
      draftTo = appliedTo;
      if (appliedTo) {
        const p = appliedTo.split("-");
        viewYear = Number(p[0]);
        viewMonth = Number(p[1]) - 1;
      } else if (appliedFrom) {
        const p = appliedFrom.split("-");
        viewYear = Number(p[0]);
        viewMonth = Number(p[1]) - 1;
      }
      setPickerMode(adminDateRangeIsMonthAligned(appliedFrom, appliedTo) ? "months" : "days");
      popover.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      adminDateRangePositionPopover(trigger, popover);
    }

    function reloadWithAppliedDateRange() {
      const form = document.getElementById(formId);
      if (!form) return;
      if (formId === "admin-finance-filters") {
        adminFinanceSyncUrl(formId);
        window.location.assign(window.location.href);
        return;
      }
      const pageField = form.querySelector('[name="page"]');
      if (pageField) pageField.value = "1";
      adminOrdersSyncUrl(formId);
      window.location.assign(window.location.href);
    }

    function applySelection() {
      let from = draftFrom || draftTo || "";
      let to = draftTo || draftFrom || "";
      if (pickerMode === "months" && from && !draftTo) {
        const parts = adminDateRangeParseIso(from);
        if (parts) {
          from = adminDateRangeIsoFromParts(parts.year, parts.month, 1);
          to = adminDateRangeMonthEndIso(parts.year, parts.month);
        }
      }
      appliedFrom = from;
      appliedTo = to;
      fromInput.value = from;
      toInput.value = to;
      syncAppliedDataset();
      updateLabel();
      closePopover(false);
      reloadWithAppliedDateRange();
    }

    function resetSelection() {
      appliedFrom = "";
      appliedTo = "";
      draftFrom = "";
      draftTo = "";
      fromInput.value = "";
      toInput.value = "";
      syncAppliedDataset();
      updateLabel();
      closePopover(false);
      reloadWithAppliedDateRange();
    }

    trigger.addEventListener("click", () => {
      if (popover.hidden) openPopover();
      else closePopover(true);
    });
    trigger.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        trigger.click();
      }
    });

    prevBtn?.addEventListener("click", () => {
      if (pickerMode === "months") {
        viewYear -= 1;
      } else {
        viewMonth -= 1;
        if (viewMonth < 0) {
          viewMonth = 11;
          viewYear -= 1;
        }
      }
      renderCalendar();
    });
    nextBtn?.addEventListener("click", () => {
      if (pickerMode === "months") {
        viewYear += 1;
      } else {
        viewMonth += 1;
        if (viewMonth > 11) {
          viewMonth = 0;
          viewYear += 1;
        }
      }
      renderCalendar();
    });
    monthSelect.addEventListener("change", () => {
      viewMonth = Number(monthSelect.value);
      renderCalendar();
    });
    yearSelect.addEventListener("change", () => {
      viewYear = Number(yearSelect.value);
      renderCalendar();
    });

    modeBtns.forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        setPickerMode(btn.dataset.dateRangeMode || "days");
      });
    });

    applyBtn?.addEventListener("click", applySelection);
    resetBtn?.addEventListener("click", resetSelection);

    document.addEventListener("click", (event) => {
      if (popover.hidden) return;
      const path = typeof event.composedPath === "function" ? event.composedPath() : [];
      if (path.includes(picker)) return;
      if (event.target instanceof Node && picker.contains(event.target)) return;
      closePopover(true);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !popover.hidden) {
        closePopover(true);
      }
    });

    updateLabel();
  });
}

let adminConfirmCallback = null;

function adminCloseConfirm() {
  const modal = document.getElementById("admin-confirm-modal");
  if (modal) modal.hidden = true;
  adminConfirmCallback = null;
}

function adminOpenConfirm({ title, message, confirmLabel, onConfirm }) {
  const modal = document.getElementById("admin-confirm-modal");
  if (!modal) {
    if (window.confirm(`${title}\n\n${message}`)) onConfirm?.();
    return;
  }
  modal.querySelector(".admin-confirm__title").textContent = title;
  modal.querySelector(".admin-confirm__text").textContent = message;
  modal.querySelector("[data-admin-confirm-ok]").textContent = confirmLabel || "Подтвердить";
  adminConfirmCallback = onConfirm;
  modal.hidden = false;
}

function adminSubmitBulkAction(form, action) {
  if (!form) return;
  let input = form.querySelector('input[type="hidden"][name="action"][data-dynamic-action="1"]');
  if (!input) {
    input = document.createElement("input");
    input.type = "hidden";
    input.name = "action";
    input.dataset.dynamicAction = "1";
    form.appendChild(input);
  }
  input.value = action;
  form.requestSubmit();
}

function initAdminConfirmModal() {
  const modal = document.getElementById("admin-confirm-modal");
  if (!modal || modal.dataset.bound === "1") return;
  modal.dataset.bound = "1";
  modal.querySelectorAll("[data-admin-confirm-cancel]").forEach((el) => {
    el.addEventListener("click", adminCloseConfirm);
  });
  modal.querySelector("[data-admin-confirm-ok]").addEventListener("click", () => {
    const cb = adminConfirmCallback;
    adminCloseConfirm();
    cb?.();
  });
}

function productsGroupBulkLabel() {
  const top = document.getElementById("admin-products-group-top-select");
  const cat = document.getElementById("admin-products-group-category-select");
  const topLabel = top?.options[top.selectedIndex]?.text?.trim() || "каталог";
  const catVal = cat?.value?.trim();
  if (catVal) {
    const catLabel = cat.options[cat.selectedIndex]?.text?.trim();
    if (catLabel) return `${topLabel} · ${catLabel}`;
  }
  return topLabel;
}

function initProductsGroupBulkConfirm(root) {
  const scope = root || document;
  const activateBtn = scope.querySelector("#admin-products-group-activate-btn");
  const deactivateBtn = scope.querySelector("#admin-products-group-deactivate-btn");
  if (activateBtn && activateBtn.dataset.confirmBound !== "1") {
    activateBtn.dataset.confirmBound = "1";
    activateBtn.addEventListener("click", () => {
      const form = activateBtn.closest("form");
      const label = productsGroupBulkLabel();
      adminOpenConfirm({
        title: "Выставить группу на витрину",
        message: `Выставить на витрину товары: «${label}»?`,
        confirmLabel: "На витрину",
        onConfirm: () => adminSubmitBulkAction(form, "activate_group"),
      });
    });
  }
  if (!deactivateBtn || deactivateBtn.dataset.confirmBound === "1") return;
  deactivateBtn.dataset.confirmBound = "1";
  deactivateBtn.addEventListener("click", () => {
    const form = deactivateBtn.closest("form");
    const label = productsGroupBulkLabel();
    adminOpenConfirm({
      title: "Снять группу с витрины",
      message: `Снять с витрины товары: «${label}»?`,
      confirmLabel: "Снять",
      onConfirm: () => adminSubmitBulkAction(form, "deactivate_group"),
    });
  });
}

function adminProductsBeforeSortChange(event) {
  const sort = event.detail.elt?.value || "";
  adminProductsSetRequestParam(event, "sort", sort);
  adminProductsSetRequestParam(event, "sort_price", "");
  adminProductsSetRequestParam(event, "page", "1");
  const sortField = document.getElementById("admin-products-sort");
  if (sortField) sortField.value = sort;
  const legacySortField = document.getElementById("admin-products-sort-price");
  if (legacySortField) legacySortField.value = "";
  const pageField = document.getElementById("admin-products-page");
  if (pageField) pageField.value = "1";
}

function adminProductsBeforeCategoryChange(event) {
  const category = event.detail.elt?.value || "";
  adminProductsSetRequestParam(event, "category", category);
  adminProductsSetRequestParam(event, "page", "1");
  const pageField = document.getElementById("admin-products-page");
  if (pageField) pageField.value = "1";
  let catHidden = document.querySelector("#admin-products-filters input[name='category']");
  if (category) {
    if (!catHidden) {
      catHidden = document.createElement("input");
      catHidden.type = "hidden";
      catHidden.name = "category";
      document.getElementById("admin-products-filters")?.appendChild(catHidden);
    }
    catHidden.value = category;
  } else if (catHidden) {
    catHidden.remove();
  }
}

function adminProductsBeforeResetFiltersRequest(event) {
  adminProductsSetRequestParam(event, "category", "");
  adminProductsSetRequestParam(event, "sort", "");
  adminProductsSetRequestParam(event, "sort_price", "");
  adminProductsSetRequestParam(event, "page", "1");
  const catSelect = document.querySelector(".products-toolbar__select[name='category']");
  if (catSelect) catSelect.value = "";
  const sortSelect = document.getElementById("admin-products-sort-select");
  if (sortSelect) sortSelect.value = "";
  const sortField = document.getElementById("admin-products-sort");
  if (sortField) sortField.value = "";
  const legacySortField = document.getElementById("admin-products-sort-price");
  if (legacySortField) legacySortField.value = "";
  const pageField = document.getElementById("admin-products-page");
  if (pageField) pageField.value = "1";
  const catHidden = document.querySelector("#admin-products-filters input[name='category']");
  if (catHidden) catHidden.remove();
}

function initProductsSearch(root) {
  const scope = root || document;
  const input = scope.querySelector("#admin-products-search-input");
  const clearBtn = scope.querySelector("#admin-products-search-clear");
  if (!input || !clearBtn || clearBtn.dataset.searchClearBound === "1") return;
  clearBtn.dataset.searchClearBound = "1";
  const sync = () => {
    clearBtn.hidden = !input.value.trim();
  };
  sync();
  input.addEventListener("input", sync);
}

function adminProductsBeforeBulkTopChange(event) {
  const top = event.detail.elt?.value || "All";
  adminProductsSetRequestParam(event, "top", top);
  adminProductsSetRequestParam(event, "category", "");
  const topField = document.getElementById("admin-products-bulk-top");
  if (topField) topField.value = top;
  const catField = document.getElementById("admin-products-bulk-category");
  if (catField) catField.value = "";
}

function adminProductsBeforeBulkCategoryChange(event) {
  const category = event.detail.elt?.value || "";
  const topField = document.getElementById("admin-products-bulk-top");
  const top = topField?.value || "All";
  adminProductsSetRequestParam(event, "top", top);
  adminProductsSetRequestParam(event, "category", category);
  const catField = document.getElementById("admin-products-bulk-category");
  if (catField) catField.value = category;
}

function adminProductsBrandsActiveVisibility() {
  const active = document.querySelector(
    ".products-brands-summary .admin-filter-pill.is-active[data-brand-visibility]"
  );
  return active?.dataset.brandVisibility || "all";
}

function adminProductsBrandsPillActivate(btn) {
  btn.closest(".products-brands-summary")
    ?.querySelectorAll(".admin-filter-pill[data-brand-visibility]")
    .forEach((pill) => pill.classList.remove("is-active"));
  btn.classList.add("is-active");
}

function adminProductsSyncBrandsFilters(q, visibility, page) {
  const qField = document.getElementById("admin-products-brands-q");
  const visField = document.getElementById("admin-products-brands-visibility");
  const pageField = document.getElementById("admin-products-brands-page");
  if (qField) qField.value = q;
  if (visField) visField.value = visibility;
  if (pageField) pageField.value = String(page);
  adminProductsSyncBrandsUrl(q, visibility, page);
}


let adminProductsFlashTimeout = null;

function adminProductsShowFlash(message, isError = false) {
  const el = document.getElementById("admin-products-flash");
  if (!el) return;
  if (adminProductsFlashTimeout) {
    clearTimeout(adminProductsFlashTimeout);
    adminProductsFlashTimeout = null;
  }
  el.textContent = message;
  el.classList.toggle("is-error", !!isError);
  el.hidden = false;
  adminProductsFlashTimeout = setTimeout(() => {
    el.hidden = true;
    adminProductsFlashTimeout = null;
  }, 3000);
}

function adminProductsReadFlashTrigger(event) {
  const xhr = event?.detail?.xhr;
  const raw = xhr?.getResponseHeader("HX-Trigger");
  if (!raw) return;
  try {
    const payload = JSON.parse(raw);
    const flash = payload?.adminProductsFlash;
    if (!flash?.message) return;
    adminProductsShowFlash(flash.message, !!flash.error);
  } catch (_err) {
    // ignore malformed HX-Trigger
  }
}

function adminProductsAfterBrandToggle(event) {
  adminProductsReadFlashTrigger(event);
  const input = document.getElementById("admin-products-brands-search-input");
  const q = input?.value.trim() || "";
  const pageField = document.getElementById("admin-products-brands-page");
  const page = parseInt(pageField?.value || "1", 10) || 1;
  adminProductsSyncBrandsFilters(q, "all", page);
  document
    .querySelectorAll(".products-brands-summary .admin-filter-pill[data-brand-visibility]")
    .forEach((pill) => {
      pill.classList.toggle("is-active", pill.dataset.brandVisibility === "all");
    });
}

function adminProductsBeforeBrandsVisibilityRequest(event, visibility) {
  const input = document.getElementById("admin-products-brands-search-input");
  const q = input?.value.trim() || "";
  adminProductsSetRequestParam(event, "q", q);
  adminProductsSetRequestParam(event, "visibility", visibility);
  adminProductsSetRequestParam(event, "page", "1");
  adminProductsSyncBrandsFilters(q, visibility, 1);
}

function adminProductsBeforeBrandsSearchRequest(event) {
  const input = document.getElementById("admin-products-brands-search-input");
  const q = input?.value.trim() || "";
  const visibility = adminProductsBrandsActiveVisibility();
  adminProductsSetRequestParam(event, "q", q);
  adminProductsSetRequestParam(event, "visibility", visibility);
  adminProductsSetRequestParam(event, "page", "1");
  adminProductsSyncBrandsFilters(q, visibility, 1);
}

function adminProductsBeforeClearBrandsSearchRequest(event) {
  const input = document.getElementById("admin-products-brands-search-input");
  if (input) input.value = "";
  adminProductsSetRequestParam(event, "q", "");
  const clearBtn = document.getElementById("admin-products-brands-search-clear");
  if (clearBtn) clearBtn.hidden = true;
  const visibility = adminProductsBrandsActiveVisibility();
  adminProductsSetRequestParam(event, "visibility", visibility);
  adminProductsSetRequestParam(event, "page", "1");
  adminProductsSyncBrandsFilters("", visibility, 1);
}

function adminProductsBeforeBrandsPageChange(event, page) {
  const input = document.getElementById("admin-products-brands-search-input");
  const q = input?.value.trim() || "";
  const visibility = adminProductsBrandsActiveVisibility();
  const nextPage = String(page);
  adminProductsSetRequestParam(event, "q", q);
  adminProductsSetRequestParam(event, "visibility", visibility);
  adminProductsSetRequestParam(event, "page", nextPage);
  adminProductsSyncBrandsFilters(q, visibility, page);
}

function adminProductsSyncBrandsUrl(q, visibility, page) {
  const url = new URL(window.location.href);
  url.searchParams.set("tab", "brands");
  if (q) url.searchParams.set("q", q);
  else url.searchParams.delete("q");
  if (visibility && visibility !== "all") url.searchParams.set("visibility", visibility);
  else url.searchParams.delete("visibility");
  if (page && page > 1) url.searchParams.set("page", String(page));
  else url.searchParams.delete("page");
  history.replaceState(null, "", url);
}

function initProductsBrandsSearch(root) {
  const scope = root || document;
  const input = scope.querySelector("#admin-products-brands-search-input");
  const clearBtn = scope.querySelector("#admin-products-brands-search-clear");
  if (!input || !clearBtn || clearBtn.dataset.searchClearBound === "1") return;
  clearBtn.dataset.searchClearBound = "1";
  const sync = () => {
    clearBtn.hidden = !input.value.trim();
  };
  sync();
  input.addEventListener("input", sync);
}

function adminProductsCloseDetail() {
  const host = document.getElementById("admin-product-detail");
  const tpl = document.getElementById("products-detail-empty-template");
  if (host && tpl) host.innerHTML = tpl.innerHTML;
  document.querySelector(".products-page--catalog")?.classList.remove("products-page--detail-open");
  document.querySelectorAll(".admin-product-row, .admin-product-row-wrap").forEach((el) => {
    el.classList.remove("is-active", "admin-order-row-active");
  });
  const url = new URL(window.location.href);
  url.searchParams.delete("id");
  history.replaceState(null, "", url);
}

function initProductsDetailClose(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-products-detail-close]").forEach((btn) => {
    if (btn.dataset.detailCloseBound === "1") return;
    btn.dataset.detailCloseBound = "1";
    btn.addEventListener("click", adminProductsCloseDetail);
  });
}

function initProductsDetailToggle(root) {
  const scope = root || document;
  scope.querySelectorAll(".products-toggle__input").forEach((input) => {
    if (input.dataset.toggleBound === "1") return;
    input.dataset.toggleBound = "1";
    const label = input.closest(".products-toggle")?.querySelector("[data-toggle-label]");
    input.addEventListener("change", () => {
      if (label) label.textContent = input.checked ? "Да" : "Нет";
    });
  });
}

let dashboardRefreshPending = 0;

function formatDashboardUpdated() {
  const t = new Date().toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `Обзор магазина · обновлено в ${t}`;
}

function touchDashboardUpdated() {
  const el = document.getElementById("dashboard-updated");
  if (el) el.textContent = formatDashboardUpdated();
}

function beginDashboardManualRefresh() {
  dashboardRefreshPending = 4;
  const el = document.getElementById("dashboard-updated");
  if (el) el.textContent = "Обзор магазина · обновление…";
}

function onDashboardPartialDone() {
  if (dashboardRefreshPending <= 0) return;
  dashboardRefreshPending -= 1;
  if (dashboardRefreshPending === 0) touchDashboardUpdated();
}

function isDashboardRefreshPath(path) {
  return String(path || "").startsWith("/internal/admin/dashboard/");
}

function initDashboardRefresh(root) {
  const scope = root || document;
  const btn = scope.querySelector("#dashboard-refresh");
  if (!btn || btn.dataset.refreshBound === "1") return;
  btn.dataset.refreshBound = "1";
  btn.addEventListener("click", beginDashboardManualRefresh);
}

if (!document.body.dataset.dashboardRefreshBound) {
  document.body.dataset.dashboardRefreshBound = "1";
  document.body.addEventListener("htmx:afterOnLoad", (e) => {
    const path = e.detail?.pathInfo?.requestPath;
    if (!isDashboardRefreshPath(path)) return;
    onDashboardPartialDone();
  });
  document.body.addEventListener("htmx:responseError", (e) => {
    const path = e.detail?.pathInfo?.requestPath;
    if (!isDashboardRefreshPath(path)) return;
    onDashboardPartialDone();
  });
}

function initCopyButtons(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-copy-target]").forEach((btn) => {
    if (btn.dataset.copyBound === "1") return;
    btn.dataset.copyBound = "1";
    btn.addEventListener("click", async () => {
      const targetId = btn.getAttribute("data-copy-target");
      const el = targetId ? document.getElementById(targetId) : null;
      const text = (el?.textContent || "").trim();
      if (!text || text === "—") return;
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        return;
      }
      const label = btn.querySelector("[data-copy-label]");
      if (label) {
        const prev = label.textContent;
        label.textContent = "Скопировано";
        window.setTimeout(() => {
          label.textContent = prev;
        }, 1600);
        return;
      }
      const prevTitle = btn.getAttribute("title") || "";
      const prevAria = btn.getAttribute("aria-label") || "";
      btn.classList.add("is-copied");
      btn.setAttribute("title", "Скопировано");
      btn.setAttribute("aria-label", "Скопировано");
      window.setTimeout(() => {
        btn.classList.remove("is-copied");
        btn.setAttribute("title", prevTitle);
        btn.setAttribute("aria-label", prevAria);
      }, 1600);
    });
  });
}

function adminCustomersBeforePageChange(event, page) {
  const nextPage = String(page);
  if (event?.detail?.parameters) {
    event.detail.parameters.page = nextPage;
  }
  const form = document.getElementById("admin-customers-filters");
  const pageField = form?.querySelector('input[name="page"]');
  if (pageField) pageField.value = nextPage;
}

const adminCustomersDeleteSelection = new Set();

function adminCustomersOpenRow(event, row) {
  if (event.target.closest("[data-customer-delete-checkbox], .customers-table__check")) return;
  const href = row?.dataset?.href;
  if (href) window.location.assign(href);
}

function adminCustomersRowKeydown(event, row) {
  if (event.key !== "Enter" && event.key !== " ") return;
  if (event.target.closest("[data-customer-delete-checkbox]")) return;
  event.preventDefault();
  adminCustomersOpenRow(event, row);
}

function adminCustomersUpdateDeleteBar() {
  const btn = document.getElementById("admin-customers-delete-btn");
  const countEl = document.getElementById("admin-customers-delete-count");
  if (!btn) return;
  const count = adminCustomersDeleteSelection.size;
  btn.hidden = count === 0;
  if (countEl) countEl.textContent = String(count);
}

function adminCustomersSyncDeleteCheckboxes(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-customer-delete-checkbox]").forEach((cb) => {
    const id = Number(cb.value);
    cb.checked = adminCustomersDeleteSelection.has(id);
  });
  adminCustomersSyncSelectAllState(scope);
  adminCustomersUpdateDeleteBar();
}

function adminCustomersSyncSelectAllState(root) {
  const scope = root || document;
  const master = scope.querySelector("[data-customers-select-all]");
  if (!master) return;
  const boxes = Array.from(scope.querySelectorAll("[data-customer-delete-checkbox]"));
  if (!boxes.length) {
    master.checked = false;
    master.indeterminate = false;
    return;
  }
  const checkedCount = boxes.filter((cb) => cb.checked).length;
  master.checked = checkedCount === boxes.length;
  master.indeterminate = checkedCount > 0 && checkedCount < boxes.length;
}

function adminCustomersToggleDeleteCheckbox(cb) {
  const id = Number(cb.value);
  if (!Number.isFinite(id) || id <= 0) return;
  if (cb.checked) adminCustomersDeleteSelection.add(id);
  else adminCustomersDeleteSelection.delete(id);
  adminCustomersSyncSelectAllState(cb.closest(".customers-table-wrap"));
  adminCustomersUpdateDeleteBar();
}

function adminCustomersToggleDeleteSelectAll(master, root) {
  const scope = root || document;
  scope.querySelectorAll("[data-customer-delete-checkbox]").forEach((cb) => {
    cb.checked = master.checked;
    const id = Number(cb.value);
    if (!Number.isFinite(id) || id <= 0) return;
    if (master.checked) adminCustomersDeleteSelection.add(id);
    else adminCustomersDeleteSelection.delete(id);
  });
  master.indeterminate = false;
  adminCustomersUpdateDeleteBar();
}

let adminCustomersFlashTimeout = null;

function adminCustomersShowFlash(message, isError = false) {
  const el = document.getElementById("admin-customers-flash");
  if (!el) return;
  if (adminCustomersFlashTimeout) {
    clearTimeout(adminCustomersFlashTimeout);
    adminCustomersFlashTimeout = null;
  }
  el.textContent = message;
  el.classList.toggle("is-error", !!isError);
  el.hidden = false;
  adminCustomersFlashTimeout = setTimeout(() => {
    el.hidden = true;
    adminCustomersFlashTimeout = null;
  }, 3000);
}

function adminCustomersReloadTable() {
  const form = document.getElementById("admin-customers-filters");
  if (!form || typeof htmx === "undefined") return;
  htmx.ajax("GET", "/internal/admin/customers/table", {
    target: "#admin-customers-table",
    swap: "innerHTML",
    values: new FormData(form),
  });
}

async function adminCustomersSubmitDelete(ids) {
  const formData = new FormData();
  ids.forEach((id) => formData.append("user_ids", String(id)));
  try {
    const resp = await fetch("/internal/admin/customers/delete-selected", {
      method: "POST",
      body: formData,
      credentials: "same-origin",
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Ошибка удаления");
    ids.forEach((id) => adminCustomersDeleteSelection.delete(id));
    adminCustomersShowFlash(data.message || "Готово");
    adminCustomersReloadTable();
  } catch (err) {
    adminCustomersShowFlash(err?.message || "Ошибка удаления", true);
  }
}

function adminCustomersDeleteSelected() {
  const ids = Array.from(adminCustomersDeleteSelection);
  if (!ids.length) return;
  const preview = ids.slice(0, 8).map((id) => `#${id}`).join(", ");
  const suffix = ids.length > 8 ? ` и ещё ${ids.length - 8}` : "";
  adminOpenConfirm({
    title: "Удалить клиентов",
    message: `Безвозвратно удалить ${ids.length} клиент(ов): ${preview}${suffix}? Будут удалены все заказы, обращения в поддержку и связанные данные.`,
    confirmLabel: "Удалить",
    onConfirm: () => adminCustomersSubmitDelete(ids),
  });
}

function initAdminCustomersDeleteButton() {
  const btn = document.getElementById("admin-customers-delete-btn");
  if (!btn || btn.dataset.bound === "1") return;
  btn.dataset.bound = "1";
  btn.addEventListener("click", adminCustomersDeleteSelected);
}

function initAdminCustomersBulkDelete(root) {
  const tableHost = document.getElementById("admin-customers-table");
  if (!tableHost) return;
  if (tableHost.dataset.deleteUiBound !== "1") {
    tableHost.dataset.deleteUiBound = "1";
    tableHost.addEventListener("change", (event) => {
      const cb = event.target.closest("[data-customer-delete-checkbox]");
      if (cb) {
        adminCustomersToggleDeleteCheckbox(cb);
        return;
      }
      const master = event.target.closest("[data-customers-select-all]");
      if (master) {
        adminCustomersToggleDeleteSelectAll(master, tableHost);
      }
    });
  }
  adminCustomersSyncDeleteCheckboxes(root || tableHost);
}

function initAdminProductGalleryForm(form) {
  if (!form || form.dataset.galleryBound === "1") return;
  const fileInput = form.querySelector(".js-admin-product-image-files, #admin-product-image-files");
  const preview = form.querySelector(".js-admin-product-gallery-preview, #admin-product-gallery-preview");
  const hiddenHost = form.querySelector("#admin-product-gallery-hidden");
  const urlInput = form.querySelector(".js-admin-product-image-url, #admin-product-image-url");
  const urlList = form.querySelector(".js-admin-gallery-url-list");
  if (!preview || (!fileInput && !urlList && !urlInput && !hiddenHost)) return;
  form.dataset.galleryBound = "1";

  const uploadedUrls = [];

  function galleryUrlInputs() {
    return Array.from(form.querySelectorAll(".js-admin-gallery-url-input, #admin-product-gallery-hidden input[name='gallery_urls']"));
  }

  function collectGalleryUrls() {
    const urls = galleryUrlInputs()
      .map((el) => (el.value || "").trim())
      .filter(Boolean);
    return [...new Set(urls)];
  }

  function appendGalleryRow(url = "") {
    if (!urlList) return;
    const row = document.createElement("div");
    row.className = "admin-gallery-url-row";
    row.innerHTML = '<input name="gallery_urls" class="input sp-input js-admin-gallery-url-input" value="" /><button type="button" class="btn btn--ghost btn--icon js-admin-gallery-url-remove" title="Удалить" aria-label="Удалить">×</button>';
    const input = row.querySelector(".js-admin-gallery-url-input");
    if (input) input.value = url;
    urlList.appendChild(row);
    bindGalleryRow(row);
    if (input) input.focus();
    renderPreview();
  }

  function bindGalleryRow(row) {
    const input = row.querySelector(".js-admin-gallery-url-input");
    const removeBtn = row.querySelector(".js-admin-gallery-url-remove");
    if (input) input.addEventListener("input", renderPreview);
    if (removeBtn) {
      removeBtn.addEventListener("click", () => {
        row.remove();
        renderPreview();
      });
    }
  }

  function renderPreview() {
    const coverUrl = (urlInput?.value || "").trim();
    const galleryUrls = collectGalleryUrls();
    const items = [];
    if (coverUrl) items.push(coverUrl);
    galleryUrls.forEach((url) => {
      if (!items.includes(url)) items.push(url);
    });
    uploadedUrls.forEach((url) => {
      if (!items.includes(url)) items.push(url);
    });

    if (hiddenHost) {
      hiddenHost.innerHTML = "";
      items.forEach((url) => {
        const hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "gallery_urls";
        hidden.value = url;
        hiddenHost.appendChild(hidden);
      });
    }

    preview.innerHTML = "";
    items.forEach((url) => {
      const img = document.createElement("img");
      img.src = url;
      img.alt = "";
      img.className = "products-gallery-preview__img";
      preview.appendChild(img);
    });
    preview.hidden = items.length === 0;
  }

  urlList?.querySelectorAll(".admin-gallery-url-row").forEach((row) => bindGalleryRow(row));
  const addBtn = form.querySelector(".js-admin-gallery-url-add");
  if (addBtn) {
    addBtn.addEventListener("click", () => appendGalleryRow(""));
  }
  if (urlInput) urlInput.addEventListener("input", renderPreview);

  if (fileInput) {
    fileInput.addEventListener("change", async () => {
      const files = Array.from(fileInput.files || []);
      if (!files.length) return;
      for (const file of files) {
        const body = new FormData();
        body.append("file", file);
        try {
          const res = await fetch("/internal/admin/products/upload-image", {
            method: "POST",
            body,
            credentials: "include",
          });
          if (!res.ok) continue;
          const data = await res.json();
          const url = data?.url ? String(data.url) : "";
          if (!url) continue;
          if (urlList) {
            appendGalleryRow(url);
          } else {
            uploadedUrls.push(url);
          }
        } catch {
          continue;
        }
      }
      fileInput.value = "";
      renderPreview();
    });
  }

  renderPreview();
}

function initProductCreateGallery(root) {
  const scope = root || document;
  scope.querySelectorAll("#admin-product-create-form, .admin-product-form").forEach((form) => {
    initAdminProductGalleryForm(form);
  });
}

function initProductsDetailDelete(root) {
  const scope = root || document;
  scope.querySelectorAll(".js-admin-product-delete").forEach((btn) => {
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", async () => {
      const productId = btn.dataset.productId;
      if (!productId) return;
      if (!confirm(`Удалить товар #${productId} безвозвратно?`)) return;

      const params = new URLSearchParams();
      params.set("view", btn.dataset.returnView || "in_stock");
      params.set("top", btn.dataset.returnTop || "All");
      params.set("page", btn.dataset.returnPage || "1");
      if (btn.dataset.returnCategory) params.set("category", btn.dataset.returnCategory);
      if (btn.dataset.returnBrand) params.set("brand", btn.dataset.returnBrand);
      if (btn.dataset.returnQ) params.set("q", btn.dataset.returnQ);
      if (btn.dataset.returnSortPrice) params.set("sort_price", btn.dataset.returnSortPrice);

      try {
        const res = await fetch(`/product/${productId}/hard`, {
          method: "DELETE",
          credentials: "include",
        });
        if (res.ok) {
          params.set("success", `Товар #${productId} удалён`);
          window.location.assign(`/internal/admin/products?${params.toString()}`);
          return;
        }
        let message = "Не удалось удалить товар";
        try {
          const data = await res.json();
          if (typeof data.detail === "string") message = data.detail;
        } catch {
          /* ignore */
        }
        params.set("error", message);
        params.set("id", productId);
        window.location.assign(`/internal/admin/products?${params.toString()}`);
      } catch {
        params.set("error", "Не удалось удалить товар");
        params.set("id", productId);
        window.location.assign(`/internal/admin/products?${params.toString()}`);
      }
    });
  });
}

function initOrderQtySteppers(root) {
  const scope = root || document;
  scope.querySelectorAll(".orders-qty-stepper").forEach((wrap) => {
    if (wrap.dataset.qtyStepperBound === "1") return;
    wrap.dataset.qtyStepperBound = "1";
    const input = wrap.querySelector('input[type="number"]');
    if (!input || input.disabled) return;
    const bounds = () => {
      const min = input.min === "" ? 1 : Number(input.min);
      const max = input.max === "" ? Number.POSITIVE_INFINITY : Number(input.max);
      return { min, max };
    };
    const syncButtons = () => {
      const { min, max } = bounds();
      const val = Number(input.value || min);
      const minus = wrap.querySelector("[data-qty-minus]");
      const plus = wrap.querySelector("[data-qty-plus]");
      if (minus) minus.disabled = val <= min;
      if (plus) plus.disabled = val >= max;
    };
    wrap.querySelector("[data-qty-minus]")?.addEventListener("click", () => {
      const { min } = bounds();
      const next = Math.max(min, Number(input.value || min) - 1);
      input.value = String(next);
      syncButtons();
    });
    wrap.querySelector("[data-qty-plus]")?.addEventListener("click", () => {
      const { min, max } = bounds();
      const next = Math.min(max, Math.max(min, Number(input.value || min) + 1));
      input.value = String(next);
      syncButtons();
    });
    input.addEventListener("input", syncButtons);
    syncButtons();
  });
}

function resetOrderAddItemBlock(block) {
  if (!block) return;
  const searchInput = block.querySelector("[data-order-add-search]");
  const picker = block.querySelector(".orders-product-picker");
  const selectedHint = block.querySelector("[data-order-add-selected]");
  const productField = block.querySelector('input[name="add_product_id"]');
  const variantSelect = block.querySelector('select[name="add_variant_id"]');
  const priceInput = block.querySelector('input[name="add_unit_price"]');
  const qtyInput = block.querySelector('input[name="add_quantity"]');
  if (searchInput) searchInput.value = "";
  if (productField) productField.value = "";
  if (variantSelect) {
    variantSelect.innerHTML = '<option value="">Сначала выберите товар</option>';
    variantSelect.disabled = true;
  }
  if (priceInput) {
    priceInput.value = "";
    priceInput.placeholder = "авто из sale_price";
  }
  if (qtyInput) qtyInput.value = "1";
  if (selectedHint) {
    selectedHint.hidden = true;
    selectedHint.textContent = "";
  }
  if (picker) {
    picker.hidden = true;
    picker.innerHTML = "";
  }
}

function closeOrderAddItemSection(block) {
  if (!block) return;
  const form = block.closest(".orders-composition-form");
  const toggleBtn = form?.querySelector(
    `[data-order-add-item-toggle="${block.id}"]`,
  ) || document.querySelector(`[data-order-add-item-toggle="${block.id}"]`);
  block.setAttribute("hidden", "");
  toggleBtn?.classList.remove("is-active");
  resetOrderAddItemBlock(block);
}

function syncOrderItemRemoveRow(checkbox) {
  const row = checkbox.closest("[data-order-item-row]");
  if (!row) return;
  row.classList.toggle("is-marked-for-removal", checkbox.checked);
  row.querySelectorAll("input:not([type='checkbox']), button[data-qty-minus], button[data-qty-plus]").forEach((el) => {
    if (el instanceof HTMLInputElement || el instanceof HTMLButtonElement) {
      el.disabled = checkbox.checked;
    }
  });
}

function initOrderCompositionRemove(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-order-item-remove]").forEach((checkbox) => {
    if (!(checkbox instanceof HTMLInputElement)) return;
    if (checkbox.dataset.orderItemRemoveBound === "1") return;
    checkbox.dataset.orderItemRemoveBound = "1";
    syncOrderItemRemoveRow(checkbox);
    checkbox.addEventListener("change", () => syncOrderItemRemoveRow(checkbox));
  });
}

function initOrderAddItemPicker(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-order-add-item]").forEach((block) => {
    if (block.dataset.orderAddBound === "1") return;
    block.dataset.orderAddBound = "1";
    const orderId = block.dataset.orderId;
    const searchInput = block.querySelector("[data-order-add-search]");
    const picker = block.querySelector(".orders-product-picker");
    const selectedHint = block.querySelector("[data-order-add-selected]");
    const productField = block.querySelector('input[name="add_product_id"]');
    const variantSelect = block.querySelector('select[name="add_variant_id"]');
    const priceInput = block.querySelector('input[name="add_unit_price"]');
    if (!searchInput || !picker || !productField || !variantSelect) return;

    let debounceTimer = null;
    let lastQuery = "";

    function hidePicker() {
      picker.hidden = true;
      picker.innerHTML = "";
    }

    function formatPrice(value) {
      if (value == null || value === "") return "";
      const num = Number(value);
      if (Number.isNaN(num)) return String(value);
      return `${num.toLocaleString("ru-RU")} ₽`;
    }

    function setSelectedProduct(product) {
      productField.value = String(product.id);
      if (selectedHint) {
        selectedHint.hidden = false;
        selectedHint.textContent = `#${product.id} · ${product.title}`;
      }
      variantSelect.innerHTML = "";
      const variants = Array.isArray(product.variants) ? product.variants : [];
      if (!variants.length) {
        variantSelect.disabled = true;
        variantSelect.innerHTML = '<option value="">Без варианта</option>';
        if (priceInput && product.sale_price != null) {
          priceInput.placeholder = formatPrice(product.sale_price) || "авто из sale_price";
        }
        return;
      }
      variantSelect.disabled = false;
      variantSelect.appendChild(new Option("Выберите вариант", ""));
      variants.forEach((variant) => {
        const labelParts = [`#${variant.id}`];
        if (variant.label) labelParts.push(variant.label);
        if (variant.sku) labelParts.push(variant.sku);
        if (variant.sale_price != null) labelParts.push(formatPrice(variant.sale_price));
        variantSelect.appendChild(new Option(labelParts.join(" · "), String(variant.id)));
      });
      if (variants.length === 1) {
        variantSelect.value = String(variants[0].id);
        variantSelect.dispatchEvent(new Event("change"));
      }
    }

    function renderResults(items) {
      picker.innerHTML = "";
      if (!items.length) {
        picker.innerHTML = '<div class="orders-product-picker__empty">Ничего не найдено</div>';
        picker.hidden = false;
        return;
      }
      items.forEach((product) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "orders-product-picker__item";
        const title = document.createElement("span");
        title.className = "orders-product-picker__title";
        title.textContent = product.title;
        const meta = document.createElement("span");
        meta.className = "orders-product-picker__meta";
        const metaParts = [`#${product.id}`];
        if (product.sale_price != null) metaParts.push(formatPrice(product.sale_price));
        if (product.variants?.length) metaParts.push(`${product.variants.length} вар.`);
        meta.textContent = metaParts.join(" · ");
        btn.append(title, meta);
        btn.addEventListener("click", () => {
          searchInput.value = product.title;
          setSelectedProduct(product);
          hidePicker();
        });
        picker.appendChild(btn);
      });
      picker.hidden = false;
    }

    async function runSearch(query) {
      const q = query.trim();
      if (q.length < 1) {
        hidePicker();
        return;
      }
      lastQuery = q;
      try {
        const res = await fetch(
          `/internal/admin/orders/product-search?${new URLSearchParams({ q })}`,
          { credentials: "include" },
        );
        if (!res.ok) {
          hidePicker();
          return;
        }
        const data = await res.json();
        if (searchInput.value.trim() !== lastQuery) return;
        renderResults(Array.isArray(data.items) ? data.items : []);
      } catch {
        hidePicker();
      }
    }

    searchInput.addEventListener("input", () => {
      productField.value = "";
      variantSelect.innerHTML = '<option value="">Сначала выберите товар</option>';
      variantSelect.disabled = true;
      if (selectedHint) selectedHint.hidden = true;
      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(() => runSearch(searchInput.value), 250);
    });
    searchInput.addEventListener("focus", () => {
      if (searchInput.value.trim()) runSearch(searchInput.value);
    });
    document.addEventListener("click", (event) => {
      if (!block.contains(event.target)) hidePicker();
    });

    variantSelect.addEventListener("change", () => {
      if (!priceInput) return;
      const selectedId = variantSelect.value;
      if (!selectedId) {
        priceInput.placeholder = "авто из sale_price";
        return;
      }
      const option = variantSelect.options[variantSelect.selectedIndex];
      const match = option?.textContent?.match(/([\d\s]+)\s*₽/);
      if (match) priceInput.placeholder = `${match[1].trim()} ₽`;
    });

    block.querySelector("[data-order-add-item-dismiss]")?.addEventListener("click", () => {
      closeOrderAddItemSection(block);
    });
  });
}

function initOrderItemsFormScroll(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-order-add-item-toggle]").forEach((btn) => {
    if (btn.dataset.orderAddItemToggleBound === "1") return;
    btn.dataset.orderAddItemToggleBound = "1";
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-order-add-item-toggle");
      const form = btn.closest(".orders-composition-form");
      const target = targetId
        ? (form?.querySelector(`#${CSS.escape(targetId)}`) || document.getElementById(targetId))
        : null;
      if (!target) return;
      const willOpen = target.hasAttribute("hidden");
      if (willOpen) {
        target.removeAttribute("hidden");
        btn.classList.add("is-active");
        target.scrollIntoView({ behavior: "smooth", block: "nearest" });
        const focusEl = target.querySelector("input, select, textarea");
        if (focusEl instanceof HTMLElement) focusEl.focus();
        return;
      }
      closeOrderAddItemSection(target);
    });
  });
  scope.querySelectorAll('form[action*="/orders/"][action$="/items"]').forEach((form) => {
    if (form.dataset.orderItemsScrollBound === "1") return;
    form.dataset.orderItemsScrollBound = "1";
    form.addEventListener("submit", () => {
      sessionStorage.setItem("admin-order-items-scroll", String(window.scrollY));
    });
  });
}

function restoreOrderItemsScroll() {
  const raw = sessionStorage.getItem("admin-order-items-scroll");
  if (raw === null) return false;
  sessionStorage.removeItem("admin-order-items-scroll");
  const y = Number.parseInt(raw, 10);
  if (!Number.isFinite(y)) return false;
  if ("scrollRestoration" in history) {
    history.scrollRestoration = "manual";
  }
  const scrollToSaved = () => window.scrollTo({ top: y, left: 0, behavior: "auto" });
  scrollToSaved();
  requestAnimationFrame(scrollToSaved);
  window.addEventListener("load", scrollToSaved, { once: true });
  return true;
}

function initOrderDetailScroll() {
  if (restoreOrderItemsScroll()) return;
  const hash = window.location.hash;
  if (!hash) return;
  const target = document.querySelector(hash);
  if (!target) return;
  if (target instanceof HTMLDetailsElement && !target.open) {
    target.open = true;
  }
  const scrollToTarget = () => target.scrollIntoView({ block: "start", behavior: "auto" });
  scrollToTarget();
  requestAnimationFrame(scrollToTarget);
  window.addEventListener("load", scrollToTarget, { once: true });
}

function initOrderStatusPreview(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-order-status-form]").forEach((form) => {
    if (form.dataset.orderStatusPreviewBound === "1") return;
    form.dataset.orderStatusPreviewBound = "1";
    const orderId = form.dataset.orderId;
    const select = form.querySelector("[data-order-status-select]");
    const notifyTextarea = form.querySelector("[data-order-status-custom-text]");
    const tabs = Array.from(form.querySelectorAll("[data-order-status-tab]"));
    const fixedStatus = form.dataset.orderStatusFixed;
    if (!orderId || !notifyTextarea) return;

    async function loadPreview(statusValue) {
      if (!statusValue) return;
      try {
        const res = await fetch(
          `/internal/admin/orders/${orderId}/status-message-preview?status=${encodeURIComponent(statusValue)}`,
          { credentials: "same-origin" },
        );
        if (!res.ok) return;
        const data = await res.json();
        if (data && typeof data.message === "string") {
          notifyTextarea.value = data.message;
          tabs.forEach((tab) => tab.classList.toggle("is-active", tab.dataset.orderStatusTab === statusValue));
        }
      } catch {
        // ignore
      }
    }

    if (fixedStatus) {
      void loadPreview(fixedStatus);
      return;
    }

    if (!select) return;

    select.addEventListener("change", () => {
      void loadPreview(select.value);
    });

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        const statusValue = tab.dataset.orderStatusTab;
        if (!statusValue) return;
        select.value = statusValue;
        void loadPreview(statusValue);
      });
    });

    if (select.value) {
      void loadPreview(select.value);
    }
  });
}


function initSupportThread(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-support-message-toggle]").forEach((btn) => {
    if (btn.dataset.supportMessageToggleBound === "1") return;
    btn.dataset.supportMessageToggleBound = "1";
    btn.addEventListener("click", () => {
      const body = btn.previousElementSibling;
      if (!body || !body.hasAttribute("data-support-message-body")) return;
      const collapsed = body.classList.toggle("is-collapsed");
      btn.textContent = collapsed ? "Развернуть" : "Свернуть";
      btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    });
  });
  const lightbox = scope.querySelector("[data-support-lightbox]");
  const lightboxImg = scope.querySelector("[data-support-lightbox-img]");
  const closeBtn = scope.querySelector("[data-support-lightbox-close]");
  const closeLightbox = () => {
    if (!lightbox || !lightboxImg) return;
    lightbox.hidden = true;
    lightboxImg.removeAttribute("src");
  };
  if (lightbox && lightbox.dataset.supportLightboxBound !== "1") {
    lightbox.dataset.supportLightboxBound = "1";
    closeBtn?.addEventListener("click", closeLightbox);
    lightbox.addEventListener("click", (event) => {
      if (event.target === lightbox) closeLightbox();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !lightbox.hidden) closeLightbox();
    });
  }
  scope.querySelectorAll("[data-support-photo-link]").forEach((link) => {
    if (link.dataset.supportPhotoBound === "1") return;
    link.dataset.supportPhotoBound = "1";
    link.addEventListener("click", (event) => {
      if (!lightbox || !lightboxImg) return;
      event.preventDefault();
      lightboxImg.src = link.getAttribute("href") || "";
      lightbox.hidden = false;
      closeBtn?.focus();
    });
  });
}

function initSupportReplyTemplates(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-support-reply-form]").forEach((form) => {
    if (form.dataset.supportReplyTemplateBound === "1") return;
    form.dataset.supportReplyTemplateBound = "1";
    const select = form.querySelector("[data-support-reply-template-select]");
    const textarea = form.querySelector("[data-support-reply-text]");
    const dataEl = form.querySelector("[data-support-reply-templates-json]");
    if (!textarea || !dataEl) return;
    let templates = {};
    try {
      templates = JSON.parse(dataEl.textContent || "{}");
    } catch {
      return;
    }
    if (!select) return;
    select.addEventListener("change", () => {
      const body = templates[select.value];
      if (typeof body === "string") {
        textarea.value = body;
      }
    });
  });
}

function initReadonlyFieldSelect(root) {
  const scope = root || document;
  scope.querySelectorAll(".orders-copy-field__value").forEach((el) => {
    if (el.dataset.readonlyFieldBound === "1") return;
    el.dataset.readonlyFieldBound = "1";
    el.addEventListener("click", () => {
      const range = document.createRange();
      range.selectNodeContents(el);
      const selection = window.getSelection();
      if (!selection) return;
      selection.removeAllRanges();
      selection.addRange(range);
    });
  });
}

function initOrderActionRail(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-order-action-rail]").forEach((rail) => {
    if (rail.dataset.orderActionRailBound === "1") return;
    rail.dataset.orderActionRailBound = "1";
    const summary = rail.parentElement?.querySelector("[data-order-summary]");
    const syncSummary = (step) => {
      summary?.querySelectorAll("[data-summary-steps]").forEach((section) => {
        const steps = (section.dataset.summarySteps || "").split(/\s+/);
        section.classList.toggle("is-linked", Boolean(step) && steps.includes(step));
      });
    };
    rail.querySelectorAll("details[data-step]").forEach((detail) => {
      detail.addEventListener("toggle", () => {
        if (!detail.open) {
          if (!rail.querySelector("details[data-step][open]")) syncSummary("");
          return;
        }
        rail.querySelectorAll("details[data-step][open]").forEach((other) => {
          if (other !== detail) other.open = false;
        });
        syncSummary(detail.dataset.step || "");
      });
    });
    const opened = rail.querySelector("details[data-step][open]");
    syncSummary(opened?.dataset.step || "");
  });
}

function bootAdminUi(root) {
  initTabs(root);
  initSeg(root);
  initListSelect(root);
  initProductsSearch(root);
  initProductsBrandsSearch(root);
  initProductsGroupBulkConfirm(root);
  initProductsDetailClose(root);
  initProductsDetailToggle(root);
  initProductsDetailDelete(root);
  initDashboardRefresh(root);
  initAdminCustomersBulkDelete(root);
  initCopyButtons(root);
  initProductCreateGallery(root);
  initOrderQtySteppers(root);
  initOrderCompositionRemove(root);
  initOrderAddItemPicker(root);
  initOrderStatusPreview(root);
  initReadonlyFieldSelect(root);
  initOrderActionRail(root);
  initSupportThread(root);
  initSupportReplyTemplates(root);
  initOrderItemsFormScroll(root);
  initDateRangePicker(root);
  initAdminOrdersBulkDelete(root);
  initAdminSupportBulkDelete(root);
}

document.addEventListener("DOMContentLoaded", () => {
  initAdminConfirmModal();
  initAdminOrdersDeleteButton();
  initAdminSupportDeleteButton();
  initAdminCustomersDeleteButton();
  bootAdminUi();
  initOrderDetailScroll();
});

document.body.addEventListener("htmx:afterSwap", (e) => {
  const target = e.detail?.target;
  if (!target) return;
  bootAdminUi(target);
  if (target.id === "admin-orders-table") {
    adminOrdersSyncUrl();
    initAdminOrdersBulkDelete(target);
  }
  if (target.id === "admin-customers-table") {
    initAdminCustomersBulkDelete(target);
  }
  if (target.id === "admin-product-detail") {
    const page = document.querySelector(".products-page--catalog");
    const hasDetail = !!target.querySelector(".products-detail");
    if (page) page.classList.toggle("products-page--detail-open", hasDetail);
    initTabs(target);
    initProductsDetailClose(target);
    initProductsDetailToggle(target);
    initProductsDetailDelete(target);
    initProductCreateGallery(target);
  }
});
