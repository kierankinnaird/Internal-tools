// Ask before anything is deleted: any form marked data-confirm shows its message first.
document.addEventListener("submit", function (event) {
  var message = event.target.getAttribute("data-confirm");
  if (message && !window.confirm(message)) { event.preventDefault(); }
});

// New-workpack form: show only the jobcards options for the choice that is selected.
(function () {
  var radios = document.querySelectorAll("input[name=jc_mode]");
  if (!radios.length) { return; }
  function sync() {
    var chosen = document.querySelector("input[name=jc_mode]:checked");
    var mode = chosen ? chosen.value : "none";
    document.querySelectorAll("[data-jc-panel]").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-jc-panel") !== mode;
    });
  }
  radios.forEach(function (radio) { radio.addEventListener("change", sync); });
  window.addEventListener("pageshow", sync);
  sync();
})();

// Tick all / tick none on the fill page.
document.addEventListener("click", function (event) {
  var button = event.target.closest ? event.target.closest("[data-check]") : null;
  if (!button) { return; }
  var on = button.getAttribute("data-check") === "all";
  document.querySelectorAll("input[name=cert]").forEach(function (box) { box.checked = on; });
});

// A form marked data-busy locks its submit button while it runs, so a slow fill is not started twice.
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (event.defaultPrevented || !form.hasAttribute("data-busy")) { return; }
  var button = form.querySelector("button[type=submit]");
  window.setTimeout(function () {
    if (button) { button.disabled = true; button.setAttribute("data-label", button.textContent); button.textContent = form.getAttribute("data-busy"); }
  }, 0);
});
window.addEventListener("pageshow", function (event) {
  if (!event.persisted) { return; }
  document.querySelectorAll("button[data-label]").forEach(function (b) { b.disabled = false; b.textContent = b.getAttribute("data-label"); });
});