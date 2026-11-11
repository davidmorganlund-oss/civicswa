/* CivicsWA calendar page. Reads data/events.json and data/status.json,
   which the nightly pipeline writes. Everything runs in the browser. */
(function () {
  'use strict';

  var CATEGORIES = [
    { id: 'all', label: 'All' },
    { id: 'council', label: 'Councils and commissions' },
    { id: 'hearing', label: 'Public hearings' },
    { id: 'school', label: 'School boards' },
    { id: 'library', label: 'Library programs' },
    { id: 'other', label: 'Other' }
  ];
  var LABELS = { council: 'Councils and commissions', hearing: 'Public hearings', school: 'School boards', library: 'Library programs', other: 'Other' };

  // ZIP codes are approximate and overlap city lines; a ZIP can map to two cities.
  var ZIPS = {
    '98501': ['Olympia', 'Tumwater'], '98502': ['Olympia'], '98505': ['Olympia'], '98506': ['Olympia'],
    '98507': ['Olympia'], '98512': ['Olympia', 'Tumwater'], '98511': ['Tumwater'],
    '98503': ['Lacey'], '98509': ['Lacey'], '98513': ['Lacey'], '98516': ['Lacey'],
    '98530': [], '98540': [], '98556': [], '98576': [], '98579': [], '98589': [], '98597': []
  };
  var CITIES = ['Olympia', 'Lacey', 'Tumwater'];

  var state = { events: [], cat: 'all', areas: null, placeLabel: '', days: 14 };
  var $ = function (id) { return document.getElementById(id); };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function safeUrl(url) { return /^https?:\/\//i.test(url || '') ? url : ''; }

  // Event times arrive as local Pacific wall-clock ISO strings; read the parts
  // directly so the page shows Olympia time wherever the visitor is.
  function parts(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
    return { y: +m[1], mo: +m[2], d: +m[3], h: +m[4], mi: +m[5], key: m[1] + '-' + m[2] + '-' + m[3] };
  }
  function clock(p) {
    var h = p.h % 12 || 12;
    return h + (p.mi ? ':' + String(p.mi).padStart(2, '0') : '') + (p.h < 12 ? ' AM' : ' PM');
  }
  function dayLabel(p) {
    return new Date(p.y, p.mo - 1, p.d).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  }
  function todayKey() {
    var s = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Los_Angeles' });
    return s.slice(0, 10);
  }
  function addDays(key, n) {
    var d = new Date(key + 'T12:00:00Z');
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }

  function resolvePlace(text) {
    var t = text.trim();
    if (!t) return { areas: null, label: '' };
    var zip = /\b(\d{5})\b/.exec(t);
    if (zip) {
      if (ZIPS[zip[1]]) return { areas: ZIPS[zip[1]], label: zip[1] };
      return { unknown: true };
    }
    var hit = CITIES.filter(function (c) { return t.toLowerCase().indexOf(c.toLowerCase()) !== -1; });
    return hit.length ? { areas: hit, label: hit[0] } : { unknown: true };
  }

  function visible() {
    var from = todayKey(), to = addDays(from, state.days);
    return state.events.filter(function (e) {
      var key = e.start.slice(0, 10);
      if (key < from || key > to) return false;
      if (state.cat !== 'all' && e.category !== state.cat) return false;
      if (state.areas && e.area !== 'countywide' && state.areas.indexOf(e.area) === -1) return false;
      return true;
    });
  }

  function icsLink(e) {
    var p = parts(e.start);
    var stamp = function (q) { return '' + q.y + String(q.mo).padStart(2, '0') + String(q.d).padStart(2, '0'); };
    var esc = function (s) { return String(s || '').replace(/([\\;,])/g, '\\$1').replace(/\n/g, '\\n'); };
    var lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CivicsWA//EN', 'BEGIN:VEVENT', 'UID:' + e.id + '@civicswa'];
    if (e.all_day) {
      lines.push('DTSTART;VALUE=DATE:' + stamp(p));
    } else {
      var t = function (q) { return stamp(q) + 'T' + String(q.h).padStart(2, '0') + String(q.mi).padStart(2, '0') + '00'; };
      lines.push('DTSTART;TZID=America/Los_Angeles:' + t(p));
      if (e.end) lines.push('DTEND;TZID=America/Los_Angeles:' + t(parts(e.end)));
    }
    lines.push('SUMMARY:' + esc(e.title + ' (' + e.host + ')'), 'LOCATION:' + esc(e.location), 'URL:' + (safeUrl(e.url) || ''), 'END:VEVENT', 'END:VCALENDAR');
    return 'data:text/calendar;charset=utf-8,' + encodeURIComponent(lines.join('\r\n'));
  }

  function card(e) {
    var p = parts(e.start);
    var art = el('article', 'event' + (e.cancelled ? ' is-cancelled' : ''));
    art.appendChild(el('div', 'when', e.all_day ? 'Time not listed' : clock(p)));

    var what = el('div', 'what');
    what.appendChild(el('span', 'tag' + (e.cancelled ? ' cancelled' : ''), e.cancelled ? 'Cancelled' : (LABELS[e.category] || 'Other')));
    what.appendChild(el('h3', null, e.title));
    what.appendChild(el('p', 'meta', e.host + (e.location ? ' · ' + e.location : '')));
    if (e.note) what.appendChild(el('p', null, e.note.length > 220 ? e.note.slice(0, 217) + '…' : e.note));
    art.appendChild(what);

    var actions = el('div', 'actions');
    var link = function (href, text, download) {
      var a = el('a', null, text);
      a.href = href;
      a.setAttribute('aria-label', text + ': ' + e.title + ', ' + dayLabel(p));
      if (download) a.download = download; else a.rel = 'noopener';
      actions.appendChild(a);
    };
    if (safeUrl(e.url)) link(safeUrl(e.url), 'Details from the host');
    if (safeUrl(e.agenda_url)) link(safeUrl(e.agenda_url), 'Agenda');
    if (!e.cancelled) link(icsLink(e), 'Add to my calendar', 'civicswa-event.ics');
    art.appendChild(actions);
    return art;
  }

  function render() {
    var list = $('list');
    list.textContent = '';
    var rows = visible();
    var from = todayKey(), to = addDays(from, state.days);
    var fmt = function (k) { return new Date(k + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); };
    $('range').textContent = fmt(from) + ' to ' + fmt(to) + ' · ' + rows.length + (rows.length === 1 ? ' event' : ' events');
    $('heading').textContent = 'Coming up ' + (state.placeLabel ? 'near ' + state.placeLabel : 'in Thurston County');

    if (!rows.length) {
      list.appendChild(el('p', 'empty', state.events.length
        ? 'Nothing of this type is listed for these dates. Try another filter or show more weeks.'
        : 'No events are loaded yet. The calendar fills in after its first nightly run.'));
    }
    var lastDay = '';
    rows.forEach(function (e) {
      var p = parts(e.start);
      if (p.key !== lastDay) { list.appendChild(el('h3', 'day', dayLabel(p))); lastDay = p.key; }
      list.appendChild(card(e));
    });

    var lastKey = state.events.length ? state.events[state.events.length - 1].start.slice(0, 10) : from;
    $('more').hidden = to >= lastKey;
    Array.prototype.forEach.call($('chips').children, function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.cat === state.cat));
    });
  }

  function setup() {
    CATEGORIES.forEach(function (c) {
      var b = el('button', 'chip', c.label);
      b.type = 'button';
      b.dataset.cat = c.id;
      b.addEventListener('click', function () { state.cat = c.id; render(); });
      $('chips').appendChild(b);
    });
    $('more').addEventListener('click', function () { state.days += 14; render(); });
    $('search').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var r = resolvePlace($('place').value), msg = $('place-msg');
      if (r.unknown) {
        state.areas = null; state.placeLabel = '';
        msg.textContent = 'We only cover Thurston County so far, so here is everything we have.';
        msg.hidden = false;
      } else {
        state.areas = r.areas; state.placeLabel = r.label;
        msg.hidden = !(r.areas && !r.areas.length);
        msg.textContent = 'We don’t have your town’s own calendar yet. These are the countywide meetings.';
      }
      render();
      $('events').scrollIntoView({ behavior: 'smooth' });
    });
  }

  function renderStatus(status) {
    var ul = $('sources');
    ul.textContent = '';
    var words = { ok: 'Up to date', quiet: 'Nothing listed', failing: 'Not responding' };
    status.sources.forEach(function (s) {
      var li = el('li');
      var a = el('a', null, s.name);
      if (safeUrl(s.homepage)) { a.href = s.homepage; a.rel = 'noopener'; }
      li.appendChild(a);
      li.appendChild(el('span', 'state-' + s.state, words[s.state] || s.state));
      ul.appendChild(li);
    });
    var when = new Date(status.generated);
    if (!isNaN(when)) $('updated').textContent = 'Last refreshed ' + when.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'America/Los_Angeles' }) + '.';
  }

  setup();
  fetch('data/events.json').then(function (r) { return r.json(); }).then(function (d) {
    state.events = d.events || [];
    render();
  }).catch(function () {
    $('list').textContent = '';
    $('list').appendChild(el('p', 'empty', 'The calendar could not be loaded. Please try again later.'));
  });
  fetch('data/status.json').then(function (r) { return r.json(); }).then(renderStatus).catch(function () {
    $('sources').textContent = '';
  });
})();
