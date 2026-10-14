/* CTR editor. The page holds the typed figures; every worked-out figure (hours, costs, checks) comes from the server's
   /preview, so there is one set of sums and this file does none of its own. */
(function () {
  "use strict";
  var root = document.getElementById("ctr");
  if (!root) return;
  var data = JSON.parse(document.getElementById("ctr-data").textContent);
  var canEdit = root.dataset.canEdit === "1";
  var $ = function (sel) { return root.querySelector(sel); };
  var linesBody = $("#lines tbody"), resBody = $("#resources tbody"), addBody = $("#additions tbody");
  var msg = $("#msg"), status = $("#status");
  var dirty = false, timer = null, seq = 0, msgKind = "";
  var lastOptions = data.computed.options;          // where hours can come from, as last worked out; new rows start with these

  function el(tag, attrs, kids) {
    var e = document.createElement(tag), k;
    for (k in (attrs || {})) {
      if (attrs[k] == null || attrs[k] === false) continue;
      if (k === "class") e.className = attrs[k];
      else if (k === "text") e.textContent = attrs[k];
      else e.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    }
    (kids || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }
  function text(v) { return v == null ? "" : String(v); }
  function gbp(v) { return "£" + Number(v || 0).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

  /* ---- one field in a row ------------------------------------------------------------------ */
  function field(key, label, value, opts) {
    opts = opts || {};
    var input = opts.area ? el("textarea", { rows: 1 }) : el("input", { type: "text" });
    input.setAttribute("data-k", key);
    input.setAttribute("aria-label", label);
    if (opts.num) { input.className = "n"; input.setAttribute("inputmode", "decimal"); }
    if (opts.placeholder != null) input.setAttribute("placeholder", opts.placeholder);
    if (opts.list) input.setAttribute("list", opts.list);
    if (!canEdit) input.readOnly = true;
    input.value = text(value);
    return input;
  }
  function select(key, label, choices, value) {
    var s = el("select", { "data-k": key, "aria-label": label }, choices.map(function (c) {
      return el("option", { value: c[0], text: c[1] });
    }));
    s.value = value;
    if (!canEdit) s.disabled = true;
    return s;
  }
  function cell(child, cls) { return el("td", { class: cls }, child ? [].concat(child) : []); }
  function actions(tr, body, canMove) {
    if (!canEdit) return cell(null);
    var kids = [];
    function btn(label, aria, fn) {
      var b = el("button", { type: "button", class: "btn small", "aria-label": aria, text: label });
      b.addEventListener("click", fn);
      return b;
    }
    if (canMove) {
      kids.push(btn("▲", "Move up", function () { if (tr.previousElementSibling) body.insertBefore(tr, tr.previousElementSibling); changed(); }));
      kids.push(btn("▼", "Move down", function () { if (tr.nextElementSibling) body.insertBefore(tr.nextElementSibling, tr); changed(); }));
    }
    kids.push(btn("✕", "Remove this row", function () { tr.remove(); changed(); }));
    return cell(kids, "acts");
  }

  /* ---- rows --------------------------------------------------------------------------------- */
  function addLine(d) {
    var allowance = d.kind === "allowance";
    var tr = el("tr", { class: allowance ? "allowance" : (d.from_snapshot ? "imported" : "") });
    tr._meta = { kind: allowance ? "allowance" : "line", from_snapshot: d.from_snapshot ? 1 : 0 };
    var qty = field("qty", allowance ? "Allowance percent" : "Quantity", d.qty, { num: true });
    var norm1 = field("eng_norm", "First column norm", d.eng_norm, { num: true }), norm2 = field("des_norm", "Second column norm", d.des_norm, { num: true });
    var factor = field("factor", "Factor", d.factor, { num: true, placeholder: "1" });
    if (allowance) { [norm1, norm2, factor].forEach(function (i) { i.disabled = true; i.value = ""; }); }
    var flag = select("flag", "Activity or deliverable", (data.flags || ["", "A", "D"]).map(function (f) { return [f, f]; }), d.flag || "");
    tr.appendChild(cell(field("description", "Description", d.description, { area: true })));
    tr.appendChild(cell(flag));
    tr.appendChild(cell(field("wbs", "WBS", d.wbs)));
    tr.appendChild(cell(field("grp", "Group", d.grp, { list: "groups" })));
    tr.appendChild(cell(allowance ? [qty, el("span", { class: "unit", text: "% of all", title: "A percentage of every other line's hours, added to the first column" })] : qty));
    tr.appendChild(cell(norm1)); tr.appendChild(cell(norm2)); tr.appendChild(cell(factor));
    tr.appendChild(cell(field("eng_override", "First column hours", d.eng_override, { num: true, placeholder: "0" })));
    tr.appendChild(cell(field("des_override", "Second column hours", d.des_override, { num: true, placeholder: "0" })));
    tr.appendChild(actions(tr, linesBody, true));
    linesBody.appendChild(tr);
    return tr;
  }

  function addResource(d) {
    var tr = el("tr");
    var src = select("source", "Takes hours from", [[d.source || "pool1", d.source || "pool1"]], d.source || "pool1");
    setOptions(src, lastOptions);
    var hours = el("td", { class: "calc" }), cost = el("td", { class: "calc" });
    hours.setAttribute("data-out", "hours"); cost.setAttribute("data-out", "cost");
    tr.appendChild(cell(field("name", "Resource name", d.name)));
    tr.appendChild(cell(src));
    tr.appendChild(cell(field("split_pct", "Split percent", d.split_pct == null ? 100 : d.split_pct, { num: true })));
    tr.appendChild(cell(field("fixed_hours", "Typed hours", d.fixed_hours, { num: true })));
    tr.appendChild(cell(field("rate", "Cost per hour", d.rate, { num: true })));
    tr.appendChild(hours); tr.appendChild(cost);
    tr.appendChild(actions(tr, resBody, true));
    resBody.appendChild(tr);
    syncFixed(tr);
    return tr;
  }
  function syncFixed(tr) {
    var fixed = tr.querySelector('[data-k="fixed_hours"]'), isFixed = tr.querySelector('[data-k="source"]').value === "fixed";
    fixed.disabled = !isFixed;
    if (!isFixed) fixed.value = "";
    tr.querySelector('[data-k="split_pct"]').disabled = isFixed;
  }

  function addAddition(d) {
    var tr = el("tr"), cost = el("td", { class: "calc" });
    cost.setAttribute("data-out", "cost");
    tr.appendChild(cell(field("name", "Addition", d.name)));
    tr.appendChild(cell(field("unit_cost", "Cost per unit", d.unit_cost, { num: true })));
    tr.appendChild(cell(field("units", "Units", d.units, { num: true })));
    tr.appendChild(cost);
    tr.appendChild(actions(tr, addBody, false));
    addBody.appendChild(tr);
    return tr;
  }

  function build(state) {
    [linesBody, resBody, addBody].forEach(function (b) { b.textContent = ""; });
    state.lines.forEach(addLine); state.resources.forEach(addResource); state.additions.forEach(addAddition);
  }

  /* ---- reading the page --------------------------------------------------------------------- */
  function rowValues(tr) {
    var o = {}, meta = tr._meta || {};
    Object.keys(meta).forEach(function (k) { o[k] = meta[k]; });
    tr.querySelectorAll("[data-k]").forEach(function (i) { o[i.getAttribute("data-k")] = i.value; });
    return o;
  }
  function collect() {
    var out = {};
    root.querySelectorAll("[data-field]").forEach(function (f) { out[f.getAttribute("data-field")] = f.value; });
    out.lines = Array.prototype.map.call(linesBody.children, rowValues);
    out.resources = Array.prototype.map.call(resBody.children, rowValues);
    out.additions = Array.prototype.map.call(addBody.children, rowValues);
    return out;
  }

  /* ---- showing the server's figures --------------------------------------------------------- */
  function setOptions(select, options) {
    var sig = JSON.stringify(options), current = select.value;
    if (select._sig === sig && select._current === current) return;
    select.textContent = "";
    var seen = false;
    options.forEach(function (o) {
      select.appendChild(el("option", { value: o.value, text: o.label + (o.hours == null ? "" : " (" + o.hours + " h)") }));
      if (o.value === current) seen = true;
    });
    if (!seen) select.appendChild(el("option", { value: current, text: "(not found) " + current.replace(/^group:/, "") }));
    select.value = current;
    select._sig = sig; select._current = current;
  }

  function apply(c) {
    lastOptions = c.options;
    document.querySelectorAll("[data-pool]").forEach(function (s) { s.textContent = c.labels[Number(s.getAttribute("data-pool")) - 1]; });
    Array.prototype.forEach.call(linesBody.children, function (tr, i) {
      var r = c.lines[i] || { eng: 0, des: 0 };
      tr.querySelector('[data-k="eng_override"]').setAttribute("placeholder", String(r.eng));
      tr.querySelector('[data-k="des_override"]').setAttribute("placeholder", String(r.des));
    });
    var groups = $("#groups");
    groups.textContent = "";
    Object.keys(c.groups).forEach(function (g) { groups.appendChild(el("option", { value: g })); });
    Array.prototype.forEach.call(resBody.children, function (tr, i) {
      var r = c.resources[i] || { hours: 0, cost: 0, source_hours: null };
      setOptions(tr.querySelector('[data-k="source"]'), c.options);
      syncFixed(tr);
      var h = tr.querySelector('[data-out="hours"]');
      h.textContent = String(r.hours);
      if (r.source_hours != null) h.appendChild(el("span", { class: "unit", text: " of " + r.source_hours }));
      tr.querySelector('[data-out="cost"]').textContent = gbp(r.cost);
    });
    Array.prototype.forEach.call(addBody.children, function (tr, i) {
      tr.querySelector('[data-out="cost"]').textContent = gbp((c.additions[i] || { cost: 0 }).cost);
    });
    var t = c.totals;
    $("#t-res-hours").textContent = String(t.hours); $("#t-res-cost").textContent = gbp(t.resources_cost);
    $("#t-add-cost").textContent = gbp(t.additions_cost);
    $("#s-hours").textContent = String(t.hours); $("#s-cost").textContent = gbp(t.cost);
    var list = $("#warnings");
    list.textContent = "";
    c.warnings.forEach(function (w) { list.appendChild(el("li", { text: w })); });
    $("#no-warnings").hidden = c.warnings.length > 0;
  }

  function show(kind, message) {
    msgKind = message ? kind : "";
    msg.textContent = message || "";
    msg.hidden = !message;
  }
  function setStatus(s) { status.textContent = s; }

  /* ---- talking to the server ---------------------------------------------------------------- */
  function post(url) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collect()) })
      .then(function (r) { return r.json().catch(function () { return { error: "The server sent something unexpected" }; }); });
  }
  function preview() {
    var mine = ++seq;
    post(root.dataset.previewUrl).then(function (r) {
      if (mine !== seq) return;                       // a newer answer is on its way
      if (r.error) { show("preview", r.error); return; }
      if (msgKind === "preview") show("", "");
      apply(r.computed);
    }).catch(function () { if (mine === seq) show("preview", "Could not reach the server"); });
  }
  function changed() {
    dirty = true;
    setStatus("Unsaved changes");
    clearTimeout(timer);
    timer = setTimeout(preview, 350);
  }
  function save() {
    clearTimeout(timer);
    seq++;                                            // drop any preview still on its way
    setStatus("Saving…");
    return post(root.dataset.saveUrl).then(function (r) {
      if (r.error) { show("save", r.error); setStatus("Not saved"); return false; }
      show("", "");
      var same = r.lines.length === linesBody.children.length && r.resources.length === resBody.children.length &&
                 r.additions.length === addBody.children.length;
      if (!same) build(r);                            // blank rows were dropped, so show what was kept
      apply(r.computed);
      dirty = false;
      setStatus("Saved " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
      return true;
    }).catch(function () { show("save", "Could not reach the server"); setStatus("Not saved"); return false; });
  }

  /* ---- wiring ------------------------------------------------------------------------------- */
  build(data);
  apply(data.computed);
  root.addEventListener("input", function (e) { if (e.target.closest("[data-k], [data-field]")) changed(); });
  root.addEventListener("change", function (e) {
    var t = e.target;
    if (t.matches('[data-k="source"]')) { t._current = t.value; syncFixed(t.closest("tr")); }
    if (t.closest("[data-k], [data-field]")) changed();
  });
  if (canEdit) {
    $("#add-line").addEventListener("click", function () { addLine({}).querySelector("textarea").focus(); changed(); });
    $("#add-allowance").addEventListener("click", function () {
      addLine({ kind: "allowance", description: "Progress, Plan Review, Meetings, IDC, Client Liaison, etc", flag: "A", qty: 15 });
      changed();
    });
    $("#add-resource").addEventListener("click", function () { addResource({}).querySelector("input").focus(); changed(); });
    $("#add-addition").addEventListener("click", function () { addAddition({}).querySelector("input").focus(); changed(); });
    $("#save").addEventListener("click", save);
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
    });
    var form = document.getElementById("import-form");
    if (form) form.addEventListener("submit", function (e) {
      if (!dirty) return;                             // importing reloads the page, so keep what has been typed first
      e.preventDefault();
      save().then(function (ok) { if (ok) form.submit(); });
    });
  }
  $("#download").addEventListener("click", function (e) {
    if (!dirty || !canEdit) return;                   // the file is made from what is saved, so save first
    e.preventDefault();
    var href = this.href;
    save().then(function (ok) { if (ok) window.location.href = href; });
  });
  window.addEventListener("beforeunload", function (e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
})();
