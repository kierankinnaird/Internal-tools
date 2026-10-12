(function () {
  var $ = function (s) { return document.querySelector(s); };
  var q = $('#q'), disc = $('#discipline'), item = $('#item'), all = $('#all');
  var rows = $('#rows'), meta = $('#meta'), empty = $('#empty');
  var timer = null, controller = null;

  function fmt(n) { return String(Math.round(n * 10000) / 10000); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function params() {
    var p = new URLSearchParams();
    if (q.value.trim()) p.set('q', q.value.trim());
    if (disc.value) p.set('discipline', disc.value);
    if (item.value) p.set('item', item.value);
    if (all.checked) p.set('all', '1');
    return p;
  }

  function loadItems(keep) {
    var p = new URLSearchParams();
    if (disc.value) p.set('discipline', disc.value);
    return fetch('/norms/api/items?' + p).then(function (r) { return r.json(); }).then(function (list) {
      item.textContent = '';
      item.appendChild(new Option('All items', ''));
      list.forEach(function (i) {
        var label = i.item_no + '  ' + i.item;
        item.appendChild(new Option(label.length > 90 ? label.slice(0, 88) + '…' : label, i.item_id));
      });
      if (keep) item.value = keep;
    });
  }

  function render(data) {
    rows.textContent = '';
    data.rows.forEach(function (r) {
      var usable = r.status === 'OK';
      var tr = el('tr', usable ? '' : 'dim');
      tr.appendChild(el('td', 'num hours', usable ? fmt(r.hours) : '–'));
      tr.appendChild(el('td', '', r.uom || ''));
      var what = el('td');
      what.appendChild(el('div', 'what', [r.row_desc, r.col_desc].filter(Boolean).join('  ›  ')));
      what.appendChild(el('div', 'item', r.item_no + '  ' + r.item));
      if (!usable) what.appendChild(el('span', 'pill', r.status.split(':')[0].replace(/ - .*/, '')));
      tr.appendChild(what);
      var key = el('td');
      key.appendChild(el('div', 'key', r.key));
      key.appendChild(el('div', 'src', r.source_cell));
      tr.appendChild(key);
      var act = el('td', 'num');
      if (usable) {
        var b = el('button', 'copy', 'Copy key');
        b.type = 'button';
        b.addEventListener('click', function () { copyKey(r.key, b); });
        act.appendChild(b);
      }
      tr.appendChild(act);
      rows.appendChild(tr);
    });
    empty.hidden = data.rows.length > 0;
    var total = data.total.toLocaleString();
    meta.textContent = data.total === 0 ? 'No matches'
      : data.shown < data.total ? 'Showing the first ' + data.shown + ' of ' + total + ' lines. Add words or filters to narrow down.'
      : total + (data.total === 1 ? ' line' : ' lines');
  }

  function copyKey(key, btn) {
    var done = function () {
      btn.textContent = 'Copied';
      btn.classList.add('done');
      setTimeout(function () { btn.textContent = 'Copy key'; btn.classList.remove('done'); }, 1400);
      fetch('/norms/api/copied', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                   body: JSON.stringify({ key: key }) });
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(key).then(done);
    } else {
      var t = document.createElement('textarea');
      t.value = key; document.body.appendChild(t); t.select();
      try { document.execCommand('copy'); done(); } catch (e) { /* ignore */ }
      document.body.removeChild(t);
    }
  }

  function run() {
    if (controller) controller.abort();
    controller = new AbortController();
    var p = params();
    history.replaceState(null, '', p.toString() ? '?' + p : location.pathname);
    fetch('/norms/api/search?' + p, { signal: controller.signal })
      .then(function (r) { return r.json(); }).then(render)
      .catch(function (e) { if (e.name !== 'AbortError') meta.textContent = 'Search failed. Restart the tool and try again.'; });
  }
  function later() { clearTimeout(timer); timer = setTimeout(run, 160); }

  q.addEventListener('input', later);
  all.addEventListener('change', run);
  item.addEventListener('change', run);
  disc.addEventListener('change', function () { item.value = ''; loadItems().then(run); });
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); q.select(); }
  });

  var start = new URLSearchParams(location.search);
  q.value = start.get('q') || '';
  disc.value = start.get('discipline') || '';
  all.checked = start.get('all') === '1';
  loadItems(start.get('item') || '').then(run);
})();