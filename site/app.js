/* CivicsWA calendar page. Reads data/events.json and data/status.json,
   which the nightly pipeline writes. Everything runs in the browser. */
(function () {
  'use strict';

  // Language: the page's <html lang> picks the strings. Pages in a language
  // folder (es/) set data-base="../" so data and guide links still resolve.
  var LANG = (document.documentElement.lang || 'en').slice(0, 2);
  var BASE = document.documentElement.getAttribute('data-base') || '';
  var LOCALE = LANG === 'es' ? 'es-US' : 'en-US';
  var ES = {
    'All': 'Todo', 'Councils and commissions': 'Concejos y comisiones', 'Public hearings': 'Audiencias públicas',
    'State Legislature': 'Legislatura estatal', 'School boards': 'Juntas escolares', 'Libraries': 'Bibliotecas', 'Other': 'Otro',
    'Time not listed': 'Hora no indicada', 'Cancelled': 'Cancelada', 'Regular schedule: confirm first': 'Horario habitual: confirme antes',
    'On the agenda': 'En la agenda', 'Read the agenda': 'Ver la agenda', 'Details from the host': 'Detalles del organizador',
    'Add to my calendar': 'Agregar a mi calendario', 'Testify or sign in': 'Testificar o registrar su opinión',
    'How to take part': 'Cómo participar', 'Copy link': 'Copiar enlace', 'Link copied': 'Enlace copiado',
    'Copy this link:': 'Copie este enlace:', 'Open link': 'Abrir enlace',
    'Subscribe to State Legislature committee meetings': 'Suscribirse a las reuniones de comités de la Legislatura',
    'Pick your county above to subscribe to its meetings. Or follow the Legislature’s committee meetings in your own calendar app.':
      'Elija su condado arriba para suscribirse a sus reuniones. O siga las reuniones de comités de la Legislatura en su propia aplicación de calendario.',
    'Nothing of this type is listed for these dates. Try another filter or show more weeks.':
      'No hay nada de este tipo para estas fechas. Pruebe otro filtro o muestre más semanas.',
    'No events are loaded yet. The calendar fills in after its first nightly run.': 'Todavía no hay reuniones cargadas.',
    'All of Washington': 'Todo Washington', 'Choose a county first': 'Primero elija un condado',
    'The county posts its meetings and agendas on its own website. Until we can add them here, that’s the place to check.':
      'El condado publica sus reuniones y agendas en su propio sitio web. Hasta que podamos agregarlas aquí, consulte ese sitio.',
    'See what the calendar covers': 'Vea qué cubre el calendario',
    'The calendar could not be loaded. Please try again later.': 'No se pudo cargar el calendario. Inténtelo más tarde.',
    'No committee agenda lists bills right now. Bill hearings show up here once the Legislature schedules them, mostly during the session that starts each January.':
      'Ninguna agenda de comité incluye proyectos de ley en este momento. Las audiencias aparecerán aquí cuando la Legislatura las programe, sobre todo durante la sesión que comienza cada enero.',
    'Look up any bill on the Legislature’s site': 'Busque cualquier proyecto de ley en el sitio de la Legislatura',
    'bill': 'proyecto de ley', 'bills': 'proyectos de ley', 'on this agenda': 'en esta agenda'
  };
  function T(s) { return LANG === 'es' && ES[s] ? ES[s] : s; }
  function guide(name) { return BASE + 'guides/' + name + '.html'; }

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
    return new Date(p.y, p.mo - 1, p.d).toLocaleDateString(LOCALE, { weekday: 'long', month: 'long', day: 'numeric' });
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
    var bills = (e.bills || []).map(function (b) { return b.id + ' ' + b.id.replace(/\s+/g, '') + ' ' + b.about; }).join(' ');
    var hay = [e.title, e.host, e.location, (e.highlights || []).join(' '), e.area, bills].join(' ').toLowerCase();
    return q.toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) !== -1; });
  }
  var SCHEDULE_PREFIX = 'From the regular meeting schedule';

  // "HB 1001", "sb5002", "ESSB 5187", "HJR 4200": a search for one bill.
  function looksLikeBill(q) { return /^(?:[a-z]{0,3}[hs]b|[hs]j[rm]|[hs]cr)\s*\d{3,4}$/i.test(q.trim()); }
  // Between sessions no agenda carries bills, so a bill search can't match.
  // Say that plainly instead of "no meetings match".
  function noBillsYet() {
    var p = el('p', 'empty', T('No committee agenda lists bills right now. Bill hearings show up here once the Legislature schedules them, mostly during the session that starts each January.') + ' ');
    var a = el('a', null, T('Look up any bill on the Legislature’s site'));
    a.href = 'https://app.leg.wa.gov/billinfo/'; a.rel = 'noopener';
    p.appendChild(a);
    p.appendChild(document.createTextNode('.'));
    return p;
  }

  // Keep the place, filter and search in the address bar so the view can be
  // shared or bookmarked ("?county=King&city=Seattle"). Nothing is sent
  // anywhere: the address only changes in this browser.
  function syncUrl() {
    if (!window.history || !history.replaceState) return;
    var qs = [];
    var add = function (k, v) { if (v) qs.push(k + '=' + encodeURIComponent(v).replace(/%20/g, '+')); };
    add('county', state.county); add('city', state.city);
    add('cat', state.cat !== 'all' ? state.cat : ''); add('q', state.q);
    try { history.replaceState(null, '', location.pathname + (qs.length ? '?' + qs.join('&') : '')); } catch (e) { /* file: pages */ }
  }
  function param(name) {
    var m = new RegExp('[?&]' + name + '=([^&#]*)').exec(location.search);
    if (!m) return null;
    try { return decodeURIComponent(m[1].replace(/\+/g, ' ')).trim().slice(0, 80); } catch (e) { return null; }
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
        var a = el('a', null, T('Open link') + ' (' + host + ')');
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

  // Bills on a Legislature agenda, each linked to its summary page. Searching
  // for a bill number opens this list so the match is visible.
  function billList(e) {
    var year = e.start.slice(0, 4);
    var box = el('details', 'bills');
    var n = e.bills.length;
    box.appendChild(el('summary', null, n + ' ' + T(n === 1 ? 'bill' : 'bills') + ' ' + T('on this agenda')));
    if (state.q && /\d/.test(state.q)) box.open = true;
    var ul = el('ul');
    e.bills.forEach(function (b) {
      var li = el('li');
      var a = el('a', null, b.id);
      a.href = 'https://app.leg.wa.gov/billsummary?BillNumber=' + encodeURIComponent(b.id.replace(/^\D+\s*/, '')) + '&Year=' + year;
      a.rel = 'noopener';
      li.appendChild(a);
      li.appendChild(document.createTextNode((b.kind ? ' · ' + b.kind : '') + (b.about ? ': ' + b.about : '')));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    return box;
  }

  function card(e) {
    var p = parts(e.start);
    var art = el('article', 'event' + (e.cancelled ? ' is-cancelled' : '') + (state.focus === e.id ? ' is-focus' : ''));
    art.id = 'm-' + e.id;
    art.appendChild(el('div', 'when', e.all_day ? T('Time not listed') : clock(p)));

    var what = el('div', 'what');
    what.appendChild(el('span', 'tag' + (e.cancelled ? ' cancelled' : ''), e.cancelled ? T('Cancelled') : T(LABELS[e.category] || 'Other')));
    if (!e.cancelled && (e.note || '').indexOf(SCHEDULE_PREFIX) === 0) what.appendChild(el('span', 'tag schedule', T('Regular schedule: confirm first')));
    what.appendChild(el('h3', null, e.title));
    what.appendChild(el('p', 'meta', e.host + (e.location ? ' · ' + e.location : '')));
    if (e.highlights && e.highlights.length) {
      var box = el('div', 'agenda');
      box.appendChild(el('p', 'agenda-label', T('On the agenda')));
      var ul = el('ul');
      e.highlights.forEach(function (h) { ul.appendChild(el('li', null, h)); });
      if (e.highlights_more) ul.appendChild(el('li', 'more-items', LANG === 'es' ? ('y ' + e.highlights_more + ' ' + (e.highlights_more === 1 ? 'punto más' : 'puntos más')) : ('and ' + e.highlights_more + ' more ' + (e.highlights_more === 1 ? 'item' : 'items'))));
      box.appendChild(ul);
      what.appendChild(box);
    }
    if (e.bills && e.bills.length) what.appendChild(billList(e));
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
    if (safeUrl(e.agenda_url)) link(safeUrl(e.agenda_url), T('Read the agenda'));
    if (safeUrl(e.url) && e.url !== e.agenda_url) link(safeUrl(e.url), T('Details from the host'));
    if (!e.cancelled) link(icsLink(e), T('Add to my calendar'), 'civicswa-event.ics');
    if (!e.cancelled && e.category === 'legislature' && /public hearing/i.test(e.note || '')) link('https://app.leg.wa.gov/csi', T('Testify or sign in'));
    if (!e.cancelled) link(guide(e.category === 'legislature' ? 'weigh-in-on-a-state-bill' : 'speak-at-a-public-meeting'), T('How to take part'));
    var share = el('button', 'share', T('Copy link'));
    share.type = 'button';
    share.setAttribute('aria-label', T('Copy link') + ': ' + e.title + ', ' + dayLabel(p));
    share.addEventListener('click', function () {
      var url = location.origin + location.pathname + '?m=' + encodeURIComponent(e.id);
      var done = function () { share.textContent = T('Link copied'); setTimeout(function () { share.textContent = T('Copy link'); }, 2000); };
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, function () { prompt(T('Copy this link:'), url); });
      else prompt(T('Copy this link:'), url);
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
    var fmt = function (k) { return new Date(k + 'T12:00:00').toLocaleDateString(LOCALE, { month: 'short', day: 'numeric' }); };
    if (LANG === 'es') {
      $('range').textContent = fmt(from) + ' a ' + fmt(to) + ' · ' + rows.length + (rows.length === 1 ? ' reunión' : ' reuniones');
      $('heading').textContent = 'Próximamente ' + (state.city ? 'en ' + state.city + ' y alrededores' : state.county ? 'en el condado de ' + state.county : 'en todo Washington');
    } else {
      $('range').textContent = fmt(from) + ' to ' + fmt(to) + ' · ' + rows.length + (rows.length === 1 ? ' event' : ' events');
      $('heading').textContent = 'Coming up ' + (state.city ? 'in and around ' + state.city : state.county ? 'in ' + state.county + ' County' : 'across Washington');
    }
    // One county is the useful subscription. With no county picked, offer the
    // Legislature, which matters to everyone.
    var sub = $('subscribe'), connected = state.county && (!state.connected || state.connected[state.county]);
    sub.href = BASE + 'data/ics/' + (connected ? slug(state.county) : 'statewide') + '.ics';
    sub.textContent = connected ? (LANG === 'es' ? 'Suscribirse a las reuniones del condado de ' + state.county : 'Subscribe to ' + state.county + ' County meetings') : T('Subscribe to State Legislature committee meetings');
    $('subscribe-text').textContent = connected
      ? (LANG === 'es' ? 'Suscríbase una vez y las reuniones del condado de ' + state.county + ' aparecerán en la aplicación de calendario que ya usa.'
        : 'Subscribe once and ' + state.county + ' County meetings show up in the calendar app you already use.')
      : T('Pick your county above to subscribe to its meetings. Or follow the Legislature’s committee meetings in your own calendar app.');
    renderStatus();

    if (state.county && state.connected && !state.connected[state.county]) {
      list.appendChild(notConnected());
    } else if (!rows.length && state.q && looksLikeBill(state.q) && state.events.length &&
               !state.events.some(function (e) { return e.bills && e.bills.length; })) {
      list.appendChild(noBillsYet());
    } else if (!rows.length) {
      list.appendChild(el('p', 'empty', state.events.length
        ? (state.q ? (LANG === 'es' ? 'Ninguna reunión coincide con “' + state.q + '” en estas fechas. Pruebe otra palabra, un área más amplia o más semanas.'
          : 'No meetings match “' + state.q + '” for these dates. Try another word, a wider area or more weeks.')
          : T('Nothing of this type is listed for these dates. Try another filter or show more weeks.'))
        : T('No events are loaded yet. The calendar fills in after its first nightly run.')));
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

  // The search box filters as you type, so pressing Enter shouldn't reload the page.
  var searchForm = $('search');
  if (searchForm) searchForm.addEventListener('submit', function (ev) { ev.preventDefault(); });

  function setup() {
    var q = $('q'), timer;
    q.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () { state.q = q.value.trim(); syncUrl(); render(); }, 200);
    });
    CATEGORIES.forEach(function (c) {
      var b = el('button', 'chip', T(c.label));
      b.type = 'button';
      b.dataset.cat = c.id;
      b.addEventListener('click', function () { state.cat = c.id; syncUrl(); render(); });
      $('chips').appendChild(b);
    });
    $('more').addEventListener('click', function () { state.days += 14; render(); });
    $('county').addEventListener('change', function () {
      state.county = $('county').value; state.city = '';
      savePlace({ county: state.county }); fillCities(); syncUrl(); render();
    });
    $('city').addEventListener('change', function () {
      state.city = $('city').value;
      savePlace({ county: state.county, city: state.city }); syncUrl(); render();
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
    sel.appendChild(new Option(T('All of Washington'), ''));
    all.sort().forEach(function (c) {
      sel.appendChild(new Option((LANG === 'es' ? 'Condado de ' + c + (counties[c] ? '' : ' (solo enlaces)') : c + ' County' + (counties[c] ? '' : ' (links only)')), c, false, c === state.county));
    });
    if (all.indexOf(state.county) === -1) state.county = '';
    sel.value = state.county;
    state.connected = counties;
    var n = Object.keys(counties).length;
    $('coverage').textContent = LANG === 'es' ? 'Reuniones de ' + n + ' de los 39 condados de Washington hasta ahora, y enlaces para el resto.'
      : 'Meetings from ' + n + ' of Washington’s 39 counties so far, and links for the rest.';
  }

  // For a county whose calendar we can't read yet, point to its own page.
  function notConnected() {
    var c = state.county, info = (state.local.counties || {})[c] || {};
    var box = el('div', 'card notice-card');
    box.appendChild(el('h3', null, LANG === 'es' ? 'Todavía no podemos leer el calendario de reuniones del condado de ' + c : 'We can’t read ' + c + ' County’s meeting calendar yet'));
    box.appendChild(el('p', null, T('The county posts its meetings and agendas on its own website. Until we can add them here, that’s the place to check.')));
    var href = info.meetings || info.site;
    if (href) {
      var a = el('a', 'link', LANG === 'es' ? 'Reuniones y agendas del condado de ' + c : c + ' County meetings and agendas');
      a.href = href; a.rel = 'noopener';
      box.appendChild(a);
    }
    var cov = el('a', 'link', T('See what the calendar covers'));
    cov.href = BASE + 'coverage.html';
    box.appendChild(cov);
    return box;
  }
  function fillCities() {
    var cities = {};
    state.events.forEach(function (e) { if (e.county === state.county && e.area !== 'countywide') cities[e.area] = true; });
    var sel = $('city');
    sel.textContent = '';
    sel.appendChild(new Option(state.county ? (LANG === 'es' ? 'Cualquier lugar del condado de ' + state.county : 'Anywhere in ' + state.county + ' County') : T('Choose a county first'), ''));
    Object.keys(cities).sort().forEach(function (c) { sel.appendChild(new Option(c, c, false, c === state.city)); });
    if (!cities[state.city]) state.city = '';
    sel.value = state.city;
    sel.disabled = !state.county;
  }

  function renderStatus() {
    var status = state.status;
    if (!status) return;
    var when = new Date(status.generated);
    if (!isNaN(when)) $('updated').textContent = (LANG === 'es' ? 'Actualizado el ' : 'Last refreshed ') + when.toLocaleDateString(LOCALE, { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'America/Los_Angeles' }) + '.';
  }

  var place = loadPlace();
  var wanted = (location.search.match(/[?&]cat=([a-z]+)/) || [])[1];
  if (wanted && CATEGORIES.some(function (c) { return c.id === wanted; })) state.cat = wanted;
  state.county = place.county || '';
  state.city = place.city || '';
  // A shared link names its own place and search; it wins over what this
  // browser had saved, without replacing the saved place.
  var linkCounty = param('county'), linkCity = param('city'), linkQ = param('q');
  if (linkCounty !== null) { state.county = linkCounty; state.city = linkCity || ''; }
  if (linkQ) { state.q = linkQ; $('q').value = linkQ; }
  setup();
  Promise.all([
    fetch(BASE + 'data/events.json').then(function (r) { return r.json(); }),
    fetch(BASE + 'data/status.json').then(function (r) { return r.json(); }).catch(function () { return { sources: [] }; }),
    fetch(BASE + 'data/local.json').then(function (r) { return r.json(); }).catch(function () { return {}; })
  ]).then(function (res) {
    state.local = res[2] || {};
    state.events = (res[0].events || []).map(function (e) { e.county = e.county || 'Thurston'; return e; });
    state.status = res[1];
    state.sources = res[1].sources || [];
    // Links are forgiving about capitals: "?county=king" finds King.
    var same = function (a, b) { return String(a).toLowerCase() === String(b).toLowerCase(); };
    if (linkCounty) {
      Object.keys(state.local.counties || {}).forEach(function (c) { if (same(c, state.county.replace(/\s+county$/i, ''))) state.county = c; });
      state.events.some(function (e) { if (e.county === state.county && same(e.area, state.city)) { state.city = e.area; return true; } return false; });
    }
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
    if (!hit) syncUrl();   // a link to one meeting keeps its own address
    render();
    if (hit) {
      var node = document.getElementById('m-' + hit.id);
      if (node) { node.scrollIntoView({ block: 'center' }); node.setAttribute('tabindex', '-1'); node.focus({ preventScroll: true }); }
    }
  }).catch(function () {
    $('list').textContent = '';
    $('list').appendChild(el('p', 'empty', T('The calendar could not be loaded. Please try again later.')));
  });
})();
