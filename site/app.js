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

  // The visitor's county and city, shared with the Engage guides' "Near you"
  // boxes and the representatives lookup. Kept in this browser only.
  var KEY = 'civicswa.place';
  function loadPlace() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
  function savePlace(p) { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch (e) { /* private mode */ } }
  function slug(c) { return c.toLowerCase().replace(/[^a-z]+/g, '-').replace(/^-|-$/g, ''); }

  var state = { events: [], sources: [], cat: 'all', county: '', city: '', days: 14 };
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

  function visible() {
    var from = todayKey(), to = addDays(from, state.days);
    return state.events.filter(function (e) {
      var key = e.start.slice(0, 10);
      if (key < from || key > to) return false;
      if (state.cat !== 'all' && e.category !== state.cat) return false;
      if (state.county && e.county !== state.county) return false;
      if (state.city && e.area !== 'countywide' && e.area !== state.city) return false;
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

  // Hosts often paste a raw web address into the note ("Register to Attend:
  // https://us02web.zoom.us/..."). Show it as a short link so it can't spill
  // across the card, and keep long notes to a couple of lines.
  function noteNode(note) {
    var p = el('p', 'note');
    var budget = 220;
    note.split(/(https?:\/\/[^\s<>"']+)/).forEach(function (part) {
      if (!part) return;
      if (/^https?:\/\//.test(part)) {
        var url = part.replace(/[.,;:)\]]+$/, '');
        var host = '';
        try { host = new URL(url).hostname.replace(/^www\./, ''); } catch (err) { return; }
        var a = el('a', null, 'Open link (' + host + ')');
        a.href = url;
        a.rel = 'noopener';
        p.appendChild(a);
        return;
      }
      if (budget <= 0) return;
      var text = part.length > budget ? part.slice(0, budget - 1) + '…' : part;
      budget -= text.length;
      p.appendChild(document.createTextNode(text));
    });
    return p;
  }

  function card(e) {
    var p = parts(e.start);
    var art = el('article', 'event' + (e.cancelled ? ' is-cancelled' : ''));
    art.appendChild(el('div', 'when', e.all_day ? 'Time not listed' : clock(p)));

    var what = el('div', 'what');
    what.appendChild(el('span', 'tag' + (e.cancelled ? ' cancelled' : ''), e.cancelled ? 'Cancelled' : (LABELS[e.category] || 'Other')));
    what.appendChild(el('h3', null, e.title));
    what.appendChild(el('p', 'meta', e.host + (e.location ? ' · ' + e.location : '')));
    if (e.highlights && e.highlights.length) {
      var box = el('div', 'agenda');
      box.appendChild(el('p', 'agenda-label', 'On the agenda'));
      var ul = el('ul');
      e.highlights.forEach(function (h) { ul.appendChild(el('li', null, h)); });
      if (e.highlights_more) ul.appendChild(el('li', 'more-items', 'and ' + e.highlights_more + ' more ' + (e.highlights_more === 1 ? 'item' : 'items')));
      box.appendChild(ul);
      what.appendChild(box);
    }
    if (e.note) what.appendChild(noteNode(e.note));
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
    $('heading').textContent = 'Coming up ' + (state.city ? 'in and around ' + state.city : state.county ? 'in ' + state.county + ' County' : 'across Washington');
    var sub = $('subscribe');
    sub.href = 'data/ics/' + (state.county ? slug(state.county) : 'washington') + '.ics';
    sub.textContent = 'Subscribe to ' + (state.county ? state.county + ' County' : 'the statewide calendar');
    renderStatus();

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
    $('county').addEventListener('change', function () {
      state.county = $('county').value; state.city = '';
      savePlace({ county: state.county }); fillCities(); render();
    });
    $('city').addEventListener('change', function () {
      state.city = $('city').value;
      savePlace({ county: state.county, city: state.city }); render();
    });
  }

  // Counties and cities come from the sources we read, so the lists only
  // offer places that have meetings here.
  function fillCounties() {
    var counties = {};
    state.sources.forEach(function (s) { counties[s.county || 'Thurston'] = true; });
    var sel = $('county');
    sel.textContent = '';
    sel.appendChild(new Option('All of Washington', ''));
    Object.keys(counties).sort().forEach(function (c) { sel.appendChild(new Option(c + ' County', c, false, c === state.county)); });
    if (!counties[state.county]) state.county = '';
    sel.value = state.county;
    $('coverage').textContent = 'Now covering ' + Object.keys(counties).length + ' of Washington’s 39 counties, with more on the way.';
  }
  function fillCities() {
    var cities = {};
    state.events.forEach(function (e) { if (e.county === state.county && e.area !== 'countywide') cities[e.area] = true; });
    var sel = $('city');
    sel.textContent = '';
    sel.appendChild(new Option(state.county ? 'Anywhere in ' + state.county + ' County' : 'Choose a county first', ''));
    Object.keys(cities).sort().forEach(function (c) { sel.appendChild(new Option(c, c, false, c === state.city)); });
    if (!cities[state.city]) state.city = '';
    sel.value = state.city;
    sel.disabled = !state.county;
  }

  function renderStatus() {
    var status = state.status;
    if (!status) return;
    var ul = $('sources');
    ul.textContent = '';
    var words = { ok: 'Up to date', quiet: 'Nothing listed', failing: 'Not responding' };
    status.sources.filter(function (s) { return !state.county || (s.county || 'Thurston') === state.county; }).forEach(function (s) {
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

  var place = loadPlace();
  state.county = place.county || '';
  state.city = place.city || '';
  setup();
  Promise.all([
    fetch('data/events.json').then(function (r) { return r.json(); }),
    fetch('data/status.json').then(function (r) { return r.json(); }).catch(function () { return { sources: [] }; })
  ]).then(function (res) {
    state.events = (res[0].events || []).map(function (e) { e.county = e.county || 'Thurston'; return e; });
    state.status = res[1];
    state.sources = res[1].sources || [];
    fillCounties();
    fillCities();
    render();
  }).catch(function () {
    $('list').textContent = '';
    $('list').appendChild(el('p', 'empty', 'The calendar could not be loaded. Please try again later.'));
    $('sources').textContent = '';
  });
})();
