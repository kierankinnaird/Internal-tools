// Ask before anything is deleted: any form marked data-confirm shows its message first.
document.addEventListener("submit", function (event) {
  var message = event.target.getAttribute("data-confirm");
  if (message && !window.confirm(message)) { event.preventDefault(); }
});