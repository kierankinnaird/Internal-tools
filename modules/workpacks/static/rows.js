// The table editor: paste from Excel, add and remove rows, Enter to go down a row, warn before leaving unsaved.
(function () {
  var form = document.getElementById("rows-form");
  if (!form || form.getAttribute("data-readonly")) { return; }
  var body = form.querySelector("tbody");
  var template = document.getElementById("row-template");
  var status = document.getElementById("rows-status");
  var heads = Array.prototype.slice.call(form.querySelectorAll("thead th[data-col]"));
  var names = heads.map(function (th) { return th.getAttribute("data-col"); });
  var labels = heads.map(function (th) { return th.firstChild.textContent.trim().toLowerCase(); });
  var dirty = false;

  function say(text) { if (status) { status.textContent = text; } }
  function rows() { return Array.prototype.slice.call(body.querySelectorAll("tr")); }
  function inputAt(tr, c) { return tr.querySelector('input[name="' + names[c] + '"]'); }
  function addRow() {
    var tr = template.content.firstElementChild.cloneNode(true);
    body.appendChild(tr);
    return tr;
  }

  // Excel puts tab-separated columns and newline-separated rows on the clipboard; a cell holding a line break is quoted.
  function parseTable(text) {
    var out = [], row = [], cell = "", quoted = false;
    text = text.replace(/\r\n?/g, "\n");
    for (var i = 0; i < text.length; i++) {
      var ch = text.charAt(i);
      if (quoted) {
        if (ch === '"') { if (text.charAt(i + 1) === '"') { cell += '"'; i++; } else { quoted = false; } }
        else { cell += ch; }
      } else if (ch === '"' && cell === "") { quoted = true; }
      else if (ch === "\t") { row.push(cell); cell = ""; }
      else if (ch === "\n") { row.push(cell); out.push(row); row = []; cell = ""; }
      else { cell += ch; }
    }
    if (cell !== "" || row.length) { row.push(cell); out.push(row); }
    return out;
  }

  function oneLine(value) { return value.replace(/\s*\n\s*/g, " ").trim(); }

  body.addEventListener("paste", function (event) {
    var target = event.target;
    if (!target || target.tagName !== "INPUT") { return; }
    var text = (event.clipboardData || window.clipboardData).getData("text");
    if (text.indexOf("\t") === -1 && text.indexOf("\n") === -1) { return; }      // one value: an ordinary paste
    event.preventDefault();
    var table = parseTable(text);
    var tr = target.closest("tr");
    var startRow = rows().indexOf(tr);
    var startCol = names.indexOf(target.getAttribute("name"));
    var skipped = 0, ignored = 0;
    // A copied header row (the column names) is not data.
    var first = table[0] || [];
    var isHeader = first.length > 0 && first.every(function (v, j) {
      return startCol + j < labels.length && v.trim().toLowerCase() === labels[startCol + j];
    });
    if (isHeader) { table = table.slice(1); skipped = 1; }
    table.forEach(function (values, i) {
      var line = rows()[startRow + i] || addRow();
      values.forEach(function (value, j) {
        if (startCol + j >= names.length) { ignored++; return; }
        inputAt(line, startCol + j).value = oneLine(value);
      });
    });
    dirty = true;
    say("Pasted " + table.length + (table.length === 1 ? " row" : " rows") +
        (skipped ? " (the header row was skipped)" : "") +
        (ignored ? "; " + ignored + " cells beyond the last column were ignored" : "") + ". Check them, then save.");
  });

  body.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" || event.target.tagName !== "INPUT") { return; }
    event.preventDefault();                                                       // Enter moves down, it does not submit
    var all = rows(), at = all.indexOf(event.target.closest("tr"));
    var next = all[at + 1] || addRow();
    inputAt(next, names.indexOf(event.target.getAttribute("name"))).focus();
  });

  body.addEventListener("click", function (event) {
    var button = event.target.closest(".rmbtn");
    if (!button) { return; }
    button.closest("tr").remove();
    dirty = true;
    say("Row removed. Save to keep the change.");
  });

  document.getElementById("add-rows").addEventListener("click", function () {
    var last;
    for (var i = 0; i < 5; i++) { last = addRow(); }
    inputAt(last, 0).scrollIntoView({ block: "nearest" });
    say("Added 5 rows.");
  });

  form.addEventListener("input", function () { dirty = true; });
  form.addEventListener("submit", function () { dirty = false; });
  window.addEventListener("beforeunload", function (event) {
    if (dirty) { event.preventDefault(); event.returnValue = ""; }
  });
})();