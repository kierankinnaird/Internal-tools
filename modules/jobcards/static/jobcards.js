(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("jc-data").textContent);
  var jc = D.jc, dirty = false, saving = false;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var tasksBody = $("#tasks"), drawBody = $("#drawings");
  var activeRow = null;

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }
  function short(t, n) { t = t || ""; return t.length > n ? t.slice(0, n - 1) + "…" : t; }
  function num(v) { if (v === "" || v == null) return null; var n = parseFloat(v); return isNaN(n) ? null : n; }
  function fmt(n) { return n.toFixed(0); }       // hours are always whole numbers, see hoursOf
  // Hours for one task: quantity x norm x factor, rounded up to the next whole hour. Rounding to 6 places first keeps
  // floating point noise (11.000000000000002) from adding an extra hour. Mirrors calc.line_hours on the server.
  function hoursOf(q, n, f) {
    if (q == null || n == null) return 0;
    return Math.ceil(Math.round(q * n * (f == null ? 1 : f) * 1e6) / 1e6);
  }
  function markDirty() { dirty = true; setStatus("Unsaved changes"); }
  function setStatus(t) { $("#status").textContent = t; }

  // ---- header fields and flags
  document.querySelectorAll("[data-f]").forEach(function (i) {
    i.value = jc[i.dataset.f] || "";
    i.addEventListener("input", markDirty);
    if (!D.canEdit) i.disabled = true;
  });
  document.querySelectorAll("[data-flag]").forEach(function (i) {
    i.checked = jc.flags.indexOf(i.dataset.flag) >= 0;
    i.addEventListener("change", markDirty);
    if (!D.canEdit) i.disabled = true;
  });

  // ---- drawings
  function addDrawing(d) {
    d = d || { number: "", title: "" };
    var tr = el("tr", {}, [
      el("td", {}, [el("input", { "aria-label": "Drawing number", "data-k": "number" })]),
      el("td", {}, [el("input", { "aria-label": "Drawing title", "data-k": "title" })]),
      el("td", {}, [el("button", { type: "button", "class": "btn small", text: "Remove" })])
    ]);
    $("[data-k=number]", tr).value = d.number; $("[data-k=title]", tr).value = d.title;
    tr.addEventListener("input", markDirty);
    $("button", tr).addEventListener("click", function () { tr.remove(); markDirty(); });
    drawBody.appendChild(tr);
  }

  // ---- tasks (two table rows each: the line, then its norm basis / factor reason).
  // A row is either a "task", which carries hours, or a "note": a heading with formatted text and no hours of its own.
  // The tasks listed under a note are its subtasks, and they carry the hours.
  function addTask(t, focus) {
    t = t || { source: "manual", factor: 1 };
    var state = { id: t.id || null, role: t.role || "", kind: (t.kind === "note" && !t.role) ? "note" : "task",
                  source: t.source || "manual", key: t.norm_key || "", uom: t.norm_uom || "",
                  ndesc: t.norm_desc || "", stamp: t.factor_set_by ? (t.factor_set_by + ", " + (t.factor_set_at || "").slice(0, 10)) : "" };
    var desc = el("textarea", { rows: "2", "aria-label": "Task description", "data-k": "description" });
    var qty = el("input", { "class": "n", inputmode: "decimal", "aria-label": "Quantity", "data-k": "qty" });
    var norm = el("input", { "class": "n", inputmode: "decimal", "aria-label": "Norm hours per unit", "data-k": "norm" });
    var find = el("button", { type: "button", "class": "btn small", text: "Find norm" });
    var tag = el("span", { "class": "tag man", text: "Manual" });
    var factor = el("input", { "class": "n", inputmode: "decimal", "aria-label": "Factor", "data-k": "factor" });
    var hours = el("td", { "class": "num hours", text: "0.00" });
    var rm = el("button", { type: "button", "class": "btn small", text: "Remove" });
    var kindBtn = el("button", { type: "button", "class": "btn small" });
    // A standard task can be edited but not removed, moved or turned into a note, so it shows a tag instead of buttons.
    var stdTag = el("span", { "class": "tag", text: "Standard", title: "Stays " + (state.role === "first" ? "first" : "last") + " on every jobcard. It can be edited but not removed." });

    // The note editor: formatted text standing in for the description. The server cleans it again on save.
    var noteBox = el("div", { "class": "notebox", contenteditable: D.canEdit ? "true" : "false", role: "textbox",
                              "aria-multiline": "true", "aria-label": "Note: a heading for the tasks under it" });
    noteBox.innerHTML = state.kind === "note" ? (t.note || "") : "";
    var tools = el("div", { "class": "notebar", role: "toolbar", "aria-label": "Note formatting" });
    [["B", "bold", "Bold"], ["I", "italic", "Italic"], ["U", "underline", "Underline"], ["• List", "insertUnorderedList", "Bulleted list"]]
      .forEach(function (b) {
        var btn = el("button", { type: "button", "class": "btn small fmt-" + b[1], title: b[2], "aria-label": b[2], text: b[0] });
        btn.addEventListener("mousedown", function (e) { e.preventDefault(); });      // keep the selection in the note
        btn.addEventListener("click", function () { noteBox.focus(); document.execCommand(b[1], false, null); markDirty(); });
        tools.appendChild(btn);
      });
    if (!D.canEdit) tools.style.display = "none";
    var noteWrap = el("div", { "class": "notewrap" }, [tools, noteBox]);
    function hasNote() { return noteBox.textContent.trim() !== "" || !!noteBox.querySelector("li"); }
    noteBox.addEventListener("input", markDirty);
    noteBox.addEventListener("paste", function (e) {         // paste as plain text: formatting comes from the buttons
      e.preventDefault();
      document.execCommand("insertText", false, (e.clipboardData || window.clipboardData).getData("text"));
    });

    var qtyCell = el("td", {}, [qty]), factorCell = el("td", {}, [factor]);
    var normCell = el("td", {}, [norm, el("div", { style: "margin-top:4px;display:flex;gap:6px;align-items:center" }, [tag].concat(D.hasNorms ? [find] : []))]);
    var main = el("tr", { "class": "main" }, [
      el("td", { "class": "idx" }), el("td", {}, [desc, noteWrap]), qtyCell, normCell, factorCell, hours,
      el("td", { "class": "acts" }, state.role ? [stdTag] : [kindBtn, rm])]);
    var basis = el("input", { "aria-label": "Basis for manual norm", placeholder: "Basis for this norm (source, calculation, quote…)" });
    var libinfo = el("div", { "class": "note" });
    var sugg = el("div", { "class": "sugg", style: "display:none" });
    var reason = el("input", { "aria-label": "Reason for factor", placeholder: "Reason for factor (required when not 1)" });
    var stampEl = el("div", { "class": "stampline" });
    var warn = el("div", { "class": "tag warn", style: "display:none" });
    var sub = el("tr", { "class": "sub" }, [el("td"), el("td", {}, [sugg, basis, libinfo]), el("td"),
      el("td", { colspan: "3" }, [reason, stampEl, warn]), el("td")]);

    desc.value = t.description || "";
    qty.value = t.qty == null ? "" : t.qty;
    norm.value = t.norm_hours == null ? "" : t.norm_hours;
    factor.value = t.factor == null ? 1 : t.factor;
    basis.value = t.basis || ""; reason.value = t.factor_reason || "";
    if (!D.canFactor) { factor.disabled = true; reason.disabled = true; }
    if (!D.canEdit) [desc, qty, norm, find, basis, rm, kindBtn].forEach(function (x) { x.disabled = true; });

    var row = { sugg: sugg, main: main, sub: sub, noteBox: noteBox, hasNote: hasNote, state: state, desc: desc,
                qty: qty, norm: norm, factor: factor, basis: basis, reason: reason };

    // Show the row as a note (formatted text, no hours) or as a task (description and hours).
    function applyKind() {
      var isNote = state.kind === "note";
      desc.style.display = isNote ? "none" : "";
      noteWrap.style.display = isNote ? "" : "none";
      [qtyCell, normCell, factorCell].forEach(function (c) { c.style.visibility = isNote ? "hidden" : ""; });
      sub.style.display = isNote ? "none" : "";
      main.className = "main" + (state.role ? " standard" : "") + (isNote ? " notekind" : "");
      kindBtn.textContent = isNote ? "Make task" : "Note";
      kindBtn.title = isNote ? "Turn this note back into a task that carries hours"
                            : "Make this a note: a heading with no hours of its own. The tasks under it carry the hours";
    }

    function refresh() {
      if (state.kind === "note") { hours.textContent = ""; warn.style.display = "none"; totals(); return; }
      var lib = state.source === "library";
      tag.textContent = lib ? "Library" : "Manual"; tag.className = "tag " + (lib ? "lib" : "man");
      basis.style.display = lib ? "none" : ""; libinfo.style.display = lib ? "" : "none";
      libinfo.textContent = lib ? (state.key + " — " + state.ndesc + (state.uom ? " (per " + state.uom + ")" : "")) : "";
      stampEl.textContent = state.stamp ? "Factor set by " + state.stamp : "";
      var q = num(qty.value), n = num(norm.value), f = num(factor.value);
      f = f == null ? 1 : f;
      hours.textContent = fmt(hoursOf(q, n, f));
      var w = [];
      if (desc.value.trim() || q != null || n != null) {
        if (q == null) w.push("No quantity");
        if (n == null) w.push("No norm");
        if (f !== 1 && !reason.value.trim()) w.push("Factor changed without a reason");
        if (!lib && n != null && !basis.value.trim()) w.push("Manual norm without a basis");
      }
      warn.style.display = w.length ? "" : "none"; warn.textContent = w.join(" · ");
      totals();
    }
    row.refresh = refresh;
    [desc, qty, factor, basis, reason].forEach(function (i) { i.addEventListener("input", function () { markDirty(); refresh(); }); });
    desc.addEventListener("input", function () { scheduleSuggest(row); });
    norm.addEventListener("input", function () {   // typing a norm makes it manual
      if (state.source === "library") { state.source = "manual"; state.key = ""; state.ndesc = ""; state.uom = ""; }
      markDirty(); refresh();
    });
    find.addEventListener("click", function () { openPicker(row); });
    kindBtn.addEventListener("click", function () {
      if (state.kind === "task") {
        if (!hasNote()) noteBox.textContent = desc.value.trim();        // keep whatever was already typed
        state.kind = "note"; state.source = "manual"; state.key = ""; state.ndesc = ""; state.uom = "";
        qty.value = ""; norm.value = ""; factor.value = 1; basis.value = ""; reason.value = "";   // a note carries no hours
        sugg.style.display = "none";
      } else {
        desc.value = noteBox.innerText.trim();
        noteBox.innerHTML = "";
        state.kind = "task";
      }
      applyKind(); markDirty(); refresh();
      (state.kind === "note" ? noteBox : desc).focus();
    });
    rm.addEventListener("click", function () { main.remove(); sub.remove(); tasks.splice(tasks.indexOf(row), 1); renumber(); markDirty(); totals(); });
    // A new task goes above the closing standard task, so that one always stays at the bottom.
    var closing = tasks.filter(function (r) { return r.state.role === "last"; })[0];
    var at = !state.role && closing ? tasks.indexOf(closing) : tasks.length;
    tasks.splice(at, 0, row);
    var before = tasks[at + 1] ? tasks[at + 1].main : null;
    [main, sub].forEach(function (tr) { tasksBody.insertBefore(tr, before); });
    applyKind(); renumber(); refresh();
    if (focus) desc.focus();
  }
  var tasks = [];

  // ---- suggestions: while a description is typed, offer norms that might fit. Nothing applies until clicked.
  function scheduleSuggest(row) {
    if (!D.hasNorms || !D.canEdit) return;
    clearTimeout(row.stimer);
    row.stimer = setTimeout(function () { suggest(row); }, 450);
  }
  function suggest(row) {
    var text = row.desc.value.trim();
    if (row.state.source === "library" || text.length < 4) { row.sugg.style.display = "none"; return; }
    var seq = (row.sseq = (row.sseq || 0) + 1);
    fetch(D.urls.suggest + "?q=" + encodeURIComponent(text)).then(function (r) { return r.json(); }).then(function (res) {
      if (seq !== row.sseq || row.state.source === "library") return;      // a newer request or a pick superseded this one
      row.sugg.textContent = "";
      if (!res.rows.length) { row.sugg.style.display = "none"; return; }
      row.sugg.appendChild(el("div", { "class": "sugg-head", text: "Norms that might apply — click one to use it, or ignore" }));
      res.rows.forEach(function (n) {
        var b = el("button", { type: "button", "class": "sugg-item" }, [
          el("b", { text: n.hours + " h" + (n.uom ? " per " + n.uom : "") }),
          el("span", { text: " " + [short(n.item, 40), n.row_desc, n.col_desc].filter(Boolean).join(" › ") })]);
        b.addEventListener("click", function () { activeRow = row; chooseNorm(n, true); });
        row.sugg.appendChild(b);
      });
      var more = el("button", { type: "button", "class": "btn small", text: "Search all norms" });
      more.addEventListener("click", function () { openPicker(row, text.split(/\s+/).slice(0, 3).join(" ")); });
      row.sugg.appendChild(more);
      row.sugg.style.display = "";
    }).catch(function () { row.sugg.style.display = "none"; });
  }
  function renumber() { tasks.forEach(function (r, i) { r.main.firstChild.textContent = i + 1; }); }
  function totals() {
    var lib = 0, man = 0;
    tasks.forEach(function (r) {
      if (r.state.kind === "note") return;          // a note carries no hours
      var q = num(r.qty.value), n = num(r.norm.value), f = num(r.factor.value);
      var h = hoursOf(q, n, f);
      if (r.state.source === "library") lib += h; else man += h;
    });
    $("#t-lib").textContent = fmt(lib); $("#t-man").textContent = fmt(man); $("#t-all").textContent = fmt(lib + man);
  }

  jc.drawings.forEach(addDrawing); jc.tasks.forEach(function (t) { addTask(t); });
  if (!jc.tasks.length && D.canEdit) addTask();
  $("#add-task").addEventListener("click", function () { addTask(null, true); markDirty(); });
  $("#add-drawing").addEventListener("click", function () { addDrawing(); markDirty(); });
  if (!D.canEdit) { $("#add-task").disabled = true; $("#add-drawing").disabled = true; }
  setStatus("");

  // ---- save
  function payload() {
    var p = { flags: [], drawings: [], tasks: [] };
    document.querySelectorAll("[data-f]").forEach(function (i) { p[i.dataset.f] = i.value; });
    document.querySelectorAll("[data-flag]").forEach(function (i) { if (i.checked) p.flags.push(i.dataset.flag); });
    drawBody.querySelectorAll("tr").forEach(function (tr) {
      p.drawings.push({ number: $("[data-k=number]", tr).value, title: $("[data-k=title]", tr).value });
    });
    tasks.forEach(function (r) {
      var isNote = r.state.kind === "note";
      p.tasks.push({ id: r.state.id, kind: r.state.kind, description: isNote ? "" : r.desc.value, qty: r.qty.value, norm_hours: r.norm.value,
        source: r.state.source, norm_key: r.state.key, norm_uom: r.state.uom, norm_desc: r.state.ndesc,
        basis: r.basis.value, factor: r.factor.value, factor_reason: r.reason.value,
        note: isNote && r.hasNote() ? r.noteBox.innerHTML : "" });
    });
    return p;
  }
  function save() {
    if (saving || !D.canEdit) return;
    saving = true; setStatus("Saving…");
    fetch(D.urls.save, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload()) })
      .then(function (r) {
        if (r.ok) return r.json();
        return r.json().catch(function () { return {}; }).then(function (b) { throw new Error(b.error || "HTTP " + r.status); });
      })
      .then(function (saved) {
        saved.tasks.forEach(function (t, i) {      // pick up new ids and factor stamps
          var r = tasks[i]; if (!r) return;
          r.state.id = t.id;
          r.state.stamp = t.factor_set_by ? (t.factor_set_by + ", " + (t.factor_set_at || "").slice(0, 10)) : "";
          r.refresh();
        });
        dirty = false; setStatus("Saved " + new Date().toLocaleTimeString());
      })
      .catch(function (e) { setStatus("Not saved: " + e.message); })
      .then(function () { saving = false; });
  }
  var sb = $("#save"); if (sb) sb.addEventListener("click", save);
  document.addEventListener("keydown", function (e) { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); } });
  window.addEventListener("beforeunload", function (e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

  // ---- norm picker
  var dlg = $("#norm-dialog"), q = $("#nd-q"), disc = $("#nd-d"), timer = null, loaded = false;
  function openPicker(row, prefill) {
    activeRow = row;
    if (!loaded) {
      loaded = true;
      fetch(D.urls.disciplines).then(function (r) { return r.json(); }).then(function (d) {
        d.disciplines.forEach(function (x) { var o = el("option", { text: x }); o.value = x; disc.appendChild(o); });
      });
    }
    q.value = prefill || "";
    dlg.showModal(); q.focus(); search();
  }
  function search() {
    var url = D.urls.search + "?q=" + encodeURIComponent(q.value) + "&discipline=" + encodeURIComponent(disc.value);
    fetch(url).then(function (r) { return r.json(); }).then(function (res) {
      var body = $("#nd-rows"); body.textContent = "";
      $("#nd-meta").textContent = res.total ? ("Showing " + res.rows.length + " of " + res.total + ". Click a line to use it.") : "No norms match. Try fewer words.";
      res.rows.forEach(function (n) {
        var tr = el("tr", { tabindex: "0" }, [
          el("td", { "class": "num", text: String(n.hours) }), el("td", { text: n.uom || "" }),
          el("td", { text: [n.discipline, n.item_no ? "Item " + n.item_no + " " + short(n.item, 60) : short(n.item, 60), n.row_desc, n.col_desc].filter(Boolean).join(" › ") })]);
        function use() { chooseNorm(n); }
        tr.addEventListener("click", use);
        tr.addEventListener("keydown", function (e) { if (e.key === "Enter") use(); });
        body.appendChild(tr);
      });
    });
  }
  function chooseNorm(n, keepDesc) {
    var r = activeRow, s = r.state;
    s.source = "library"; s.key = n.key; s.uom = n.uom || ""; s.ndesc = [short(n.item, 60), n.row_desc, n.col_desc].filter(Boolean).join(" › ");
    r.norm.value = n.hours;
    if (!r.desc.value.trim()) r.desc.value = [n.row_desc, n.col_desc].filter(Boolean).join(" - ") || n.item;
    if (dlg.open) dlg.close(); r.sugg.style.display = "none"; markDirty(); r.refresh(); r.qty.focus();
  }
  q.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(search, 200); });
  disc.addEventListener("change", search);
  $("#nd-close").addEventListener("click", function () { dlg.close(); });
})();