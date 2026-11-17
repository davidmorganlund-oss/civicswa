/* CivicsWA calendar page. Reads data/events.json and data/status.json,
   which the nightly pipeline writes. Everything runs in the browser. */
(function () {
  'use strict';

  var CATEGORIES = [
    { id: 'all', label: 'All' },
    { id: 'council', label: 'Councils and commissions' },
    { id: 'hearing', label: 'Public hearings' },
    { id: 'legislature', label: 'State Legislature' },
    { id: 'school', label: 'School boards' },
    { id: 'library', label: 'Libraries' },
    { id: 'other', label: 'Other' }
  ];
  var LABELS = { legislature: 'State Legislature', council: 'Councils and commissions', hearing: 'Public hearings', school: 'School boards', library: 'Libraries', other: 'Other' };

  // The visitor's county and city, shared with the Engage guides' "Near you"
  // boxes and the representatives lookup. Kept in this browser only.
  var KEY = 'civicswa.place';
  function loadPlace() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
  function savePlace(p) { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch (e) { /* private mode */ } }
  function slug(c) { return c.toLowerCase().replace(/[^a-z]+/g, '-').replace(/^-|-$/g, ''); }

  var state = { events: [], sources: [], local: {}, connected: null, cat: 'all', county: '', city: '', days: 14, q: '', focus: '' };
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

  function visible(cat) {
    var from = todayKey(), to = addDays(from, state.days);
    cat = cat || state.cat;
    return state.events.filter(function (e) {
      var key = e.start.slice(0, 10);
      if (key < from || key > to) return false;
      if (cat !== 'all' && e.category !== cat) return false;
      if (state.q && !matches(e, state.q)) return false;
      // Legislature meetings belong to everyone: they show statewide, and in a
      // county view when the "State Legislature" filter is on.
      if (e.county === 'Statewide') return !state.county || cat === 'legislature';
      if (state.county && e.county !== state.county) return false;
      if (state.city && e.area !== 'countywide' && e.area !== state.city) return false;
      return true;
    });
  }

  // Search looks at the meeting name, the host, the place and agenda items.
  function matches(e, q) {
    var hay = [e.title, e.host, e.location, (e.highlights || []).join(' '), e.area].join(' ').toLowerCase();
    return q.toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) !== -1; });
  }
  var SCHEDULE_PREFIX = 'From the regular meeting schedule';

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
    var art = el('article', 'event' + (e.cancelled ? ' is-cancelled' : '') + (state.focus === e.id ? ' is-focus' : ''));
    art.id = 'm-' + e.id;
    art.appendChild(el('div', 'when', e.all_day ? 'Time not listed' : clock(p)));

    var what = el('div', 'what');
    what.appendChild(el('span', 'tag' + (e.cancelled ? ' cancelled' : ''), e.cancelled ? 'Cancelled' : (LABELS[e.category] || 'Other')));
    if (!e.cancelled && (e.note || '').indexOf(SCHEDULE_PREFIX) === 0) what.appendChild(el('span', 'tag schedule', 'Regular schedule: confirm first'));
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
    // When the agenda lives on the meeting's own page, one link is enough.
    if (safeUrl(e.agenda_url)) link(safeUrl(e.agenda_url), 'Read the agenda');
    if (safeUrl(e.url) && e.url !== e.agenda_url) link(safeUrl(e.url), 'Details from the host');
    if (!e.cancelled) link(icsLink(e), 'Add to my calendar', 'civicswa-event.ics');
    if (!e.cancelled) link(e.category === 'legislature' ? 'guides/weigh-in-on-a-state-bill.html' : 'guides/speak-at-a-public-meeting.html', 'How to take part');
    var share = el('button', 'share', 'Copy link');
    share.type = 'button';
    share.setAttribute('aria-label', 'Copy a link to ' + e.title + ', ' + dayLabel(p));
    share.addEventListener('click', function () {
      var url = location.origin + location.pathname + '?m=' + encodeURIComponent(e.id);
      var done = function () { share.textContent = 'Link copied'; setTimeout(function () { share.textContent = 'Copy link'; }, 2000); };
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, function () { prompt('Copy this link:', url); });
      else prompt('Copy this link:', url);
    });
    actions.appendChild(share);
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
    // One county is the useful subscription. With no county picked, offer the
    // Legislature, which matters to everyone.
    var sub = $('subscribe'), connected = state.county && (!state.connected || state.connected[state.county]);
    sub.href = 'data/ics/' + (connected ? slug(state.county) : 'statewide') + '.ics';
    sub.textContent = connected ? 'Subscribe to ' + state.county + ' County meetings' : 'Subscribe to State Legislature committee meetings';
    $('subscribe-text').textContent = connected
      ? 'Subscribe once and ' + state.county + ' County meetings show up in the calendar app you already use.'
      : 'Pick your county above to subscribe to its meetings. Or follow the Legislature’s committee meetings in your own calendar app.';
    renderStatus();

    if (state.county && state.connected && !state.connected[state.county]) {
      list.appendChild(notConnected());
    } else if (!rows.length) {
      list.appendChild(el('p', 'empty', state.events.length
        ? (state.q ? 'No meetings match “' + state.q + '” for these dates. Try another word, a wider area or more weeks.'
          : 'Nothing of this type is listed for these dates. Try another filter or show more weeks.')
        : 'No events are loaded yet. The calendar fills in after its first nightly run.'));
    }
    var lastDay = '';
    rows.forEach(function (e) {
      var p = parts(e.start);
      if (p.key !== lastDay) { list.appendChild(el('h3', 'day', dayLabel(p))); lastDay = p.key; }
      list.appendChild(card(e));
    });

    structuredData(rows.slice(0, 40));

    var lastKey = state.events.length ? state.events[state.events.length - 1].start.slice(0, 10) : from;
    $('more').hidden = to >= lastKey;
    // Only offer filters that have meetings for this place right now.
    Array.prototype.forEach.call($('chips').children, function (b) {
      var c = b.dataset.cat;
      b.hidden = c !== 'all' && c !== state.cat && !visible(c).length;
      b.setAttribute('aria-pressed', String(c === state.cat));
    });
  }

  // Event markup for search engines, for the meetings on screen.
  function structuredData(rows) {
    var old = document.getElementById('ld-events');
    if (old) old.remove();
    if (!rows.length) return;
    var tag = document.createElement('script');
    tag.type = 'application/ld+json';
    tag.id = 'ld-events';
    tag.textContent = JSON.stringify(rows.map(function (e) {
      return {
        '@context': 'https://schema.org', '@type': 'Event', name: e.title + ' (' + e.host + ')',
        startDate: e.start, endDate: e.end || undefined,
        eventStatus: 'https://schema.org/' + (e.cancelled ? 'EventCancelled' : 'EventScheduled'),
        eventAttendanceMode: 'https://schema.org/OfflineEventAttendanceMode',
        location: { '@type': 'Place', name: e.location || e.host, address: (e.area !== 'countywide' ? e.area + ', ' : '') + (e.county !== 'Statewide' ? e.county + ' County, ' : '') + 'WA' },
        organizer: { '@type': 'GovernmentOrganization', name: e.host, url: safeUrl(e.url) || undefined },
        isAccessibleForFree: true, url: location.origin + location.pathname + '?m=' + encodeURIComponent(e.id)
      };
    }));
    document.head.appendChild(tag);
  }

  function setup() {
    var q = $('q'), timer;
    q.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () { state.q = q.value.trim(); render(); }, 200);
    });
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
    state.sources.forEach(function (s) { if (s.county !== 'Statewide') counties[s.county || 'Thurston'] = true; });
    var all = Object.keys(state.local.counties || {});
    if (!all.length) all = Object.keys(counties);
    var sel = $('county');
    sel.textContent = '';
    sel.appendChild(new Option('All of Washington', ''));
    all.sort().forEach(function (c) {
      sel.appendChild(new Option(c + ' County' + (counties[c] ? '' : ' (links only)'), c, false, c === state.county));
    });
    if (all.indexOf(state.county) === -1) state.county = '';
    sel.value = state.county;
    state.connected = counties;
    $('coverage').textContent = 'Meetings from ' + Object.keys(counties).length + ' of Washington’s 39 counties so far, and links for the rest.';
  }

  // For a county whose calendar we can't read yet, point to its own page.
  function notConnected() {
    var c = state.county, info = (state.local.counties || {})[c] || {};
    var box = el('div', 'card notice-card');
    box.appendChild(el('h3', null, 'We can’t read ' + c + ' County’s meeting calendar yet'));
    box.appendChild(el('p', null, 'The county posts its meetings and agendas on its own website. Until we can add them here, that’s the place to check.'));
    var href = info.meetings || info.site;
    if (href) {
      var a = el('a', 'link', c + ' County meetings and agendas');
      a.href = href; a.rel = 'noopener';
      box.appendChild(a);
    }
    var cov = el('a', 'link', 'See what the calendar covers');
    cov.href = 'coverage.html';
    box.appendChild(cov);
    return box;
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
    var when = new Date(status.generated);
    if (!isNaN(when)) $('updated').textContent = 'Last refreshed ' + when.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'America/Los_Angeles' }) + '.';
  }

  var place = loadPlace();
  var wanted = (location.search.match(/[?&]cat=([a-z]+)/) || [])[1];
  if (wanted && CATEGORIES.some(function (c) { return c.id === wanted; })) state.cat = wanted;
  state.county = place.county || '';
  state.city = place.city || '';
  setup();
  Promise.all([
    fetch('data/events.json').then(function (r) { return r.json(); }),
    fetch('data/status.json').then(function (r) { return r.json(); }).catch(function () { return { sources: [] }; }),
    fetch('data/local.json').then(function (r) { return r.json(); }).catch(function () { return {}; })
  ]).then(function (res) {
    state.local = res[2] || {};
    state.events = (res[0].events || []).map(function (e) { e.county = e.county || 'Thurston'; return e; });
    state.status = res[1];
    state.sources = res[1].sources || [];
    fillCounties();
    // A shared link to one meeting: show it, whatever place or filter this
    // browser had saved, and bring it into view.
    var m = (location.search.match(/[?&]m=([A-Za-z0-9_-]+)/) || [])[1];
    var hit = m && state.events.filter(function (e) { return e.id === m; })[0];
    if (hit) {
      state.focus = hit.id; state.cat = 'all';
      state.county = hit.county === 'Statewide' ? '' : hit.county;
      state.city = hit.area !== 'countywide' ? hit.area : '';
      var span = Math.ceil((new Date(hit.start.slice(0, 10) + 'T12:00:00Z') - new Date(todayKey() + 'T12:00:00Z')) / 864e5);
      if (span > state.days) state.days = span;
      $('county').value = state.county;
    }
    fillCities();
    render();
    if (hit) {
      var node = document.getElementById('m-' + hit.id);
      if (node) { node.scrollIntoView({ block: 'center' }); node.setAttribute('tabindex', '-1'); node.focus({ preventScroll: true }); }
    }
  }).catch(function () {
    $('list').textContent = '';
    $('list').appendChild(el('p', 'empty', 'The calendar could not be loaded. Please try again later.'));
  });
})();
