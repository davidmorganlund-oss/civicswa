// This Week in Olympia: Legislature committee meetings by day, with the bills
// on each agenda, topic filters and the links people need to weigh in.
(function () {
  'use strict';

  var SESSION_START = '2027-01-11'; // second Monday in January
  var TOPICS = {
    justice: 'Criminal legal & public safety',
    housing: 'Housing & homelessness',
    education: 'Schools & colleges',
    health: 'Health & behavioral health',
    elections: 'Elections & state government',
    environment: 'Environment, energy & land',
    transportation: 'Transportation',
    budget: 'Budget & taxes',
    labor: 'Workers & jobs',
    families: 'Families & human services',
    tribes: 'Tribal relations',
    business: 'Business, consumers & tech',
    local: 'Cities & counties'
  };
  var CSI = 'https://app.leg.wa.gov/csi';

  var state = { events: [], day: '', topic: '', q: '' };
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function safeUrl(url) { return /^https?:\/\//i.test(url || '') ? url : ''; }
  function parts(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
    return { y: +m[1], mo: +m[2], d: +m[3], h: +m[4], mi: +m[5], key: m[1] + '-' + m[2] + '-' + m[3] };
  }
  function clock(p) {
    var h = p.h % 12 || 12;
    return h + (p.mi ? ':' + String(p.mi).padStart(2, '0') : '') + (p.h < 12 ? ' AM' : ' PM');
  }
  function todayKey() { return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Los_Angeles' }).slice(0, 10); }
  function addDays(key, n) {
    var d = new Date(key + 'T12:00:00Z');
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function longDay(key) {
    return new Date(key + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  }
  function shortDay(key) {
    var t = todayKey();
    if (key === t) return 'Today';
    if (key === addDays(t, 1)) return 'Tomorrow';
    return new Date(key + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  }

  function isHearing(e) {
    return /public hearing/i.test(e.note || '') || (e.bills || []).some(function (b) { return /public hearing/i.test(b.kind || ''); });
  }
  // What a bill's agenda line means for someone who wants to take part.
  function kindLabel(kind) {
    if (/public hearing/i.test(kind)) return 'Public hearing: testimony welcome';
    if (/executive/i.test(kind)) return /possible/i.test(kind) ? 'Possible committee vote' : 'Committee vote';
    if (/work session/i.test(kind)) return 'Briefing';
    return kind || '';
  }
  function billUrl(b, e) {
    return 'https://app.leg.wa.gov/billsummary?BillNumber=' + encodeURIComponent(b.id.replace(/^\D+\s*/, '')) + '&Year=' + e.start.slice(0, 4);
  }
  function billMatches(b) {
    if (state.topic && (b.topics || []).indexOf(state.topic) === -1) return false;
    if (state.q) {
      var hay = (b.id + ' ' + b.id.replace(/\s+/g, '') + ' ' + (b.about || '')).toLowerCase();
      if (!state.q.toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) !== -1; })) return false;
    }
    return true;
  }
  function eventMatches(e) {
    if (state.topic && (e.topics || []).indexOf(state.topic) === -1) return false;
    if (state.q) {
      var hay = [e.title, e.location, (e.highlights || []).join(' ')].concat((e.bills || []).map(function (b) {
        return b.id + ' ' + b.id.replace(/\s+/g, '') + ' ' + (b.about || '');
      })).join(' ').toLowerCase();
      if (!state.q.toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) !== -1; })) return false;
    }
    return true;
  }
  function filtering() { return !!(state.topic || state.q); }

  function icsLink(e) {
    var p = parts(e.start);
    var stamp = '' + p.y + String(p.mo).padStart(2, '0') + String(p.d).padStart(2, '0') + 'T' + String(p.h).padStart(2, '0') + String(p.mi).padStart(2, '0') + '00';
    var esc = function (s) { return String(s || '').replace(/([\\;,])/g, '\\$1').replace(/\n/g, '\\n'); };
    var lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CivicsWA//EN', 'BEGIN:VEVENT', 'UID:' + e.id + '@civicswa',
      'DTSTART;TZID=America/Los_Angeles:' + stamp, 'SUMMARY:' + esc(e.title + ' (Legislature)'),
      'LOCATION:' + esc(e.location), 'URL:' + (safeUrl(e.url) || ''), 'END:VEVENT', 'END:VCALENDAR'];
    return 'data:text/calendar;charset=utf-8,' + encodeURIComponent(lines.join('\r\n'));
  }

  function billBlock(e) {
    var bills = e.bills || [];
    var shown = filtering() ? bills.filter(billMatches) : bills;
    // A meeting can match by its committee or work-session topics with no
    // single bill matching; show the whole agenda then.
    if (filtering() && !shown.length) shown = bills;
    var box = el('div', 'agenda');
    box.appendChild(el('p', 'agenda-label', bills.length === 1 ? '1 bill on the agenda' : bills.length + ' bills on the agenda'));
    var ul = el('ul', 'bill-list');
    shown.forEach(function (b) {
      var li = el('li');
      var a = el('a', null, b.id);
      a.href = billUrl(b, e);
      a.rel = 'noopener';
      li.appendChild(a);
      if (b.about) li.appendChild(document.createTextNode(' ' + b.about));
      var k = kindLabel(b.kind || '');
      if (k) li.appendChild(el('span', 'bill-kind' + (/testimony/.test(k) ? ' open' : ''), k));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    var rest = bills.length - shown.length;
    if (rest > 0) box.appendChild(el('p', 'more-items', 'and ' + rest + ' other ' + (rest === 1 ? 'bill' : 'bills') + ' on this agenda'));
    return box;
  }

  function card(e) {
    var p = parts(e.start);
    var art = el('article', 'event' + (e.cancelled ? ' is-cancelled' : ''));
    art.appendChild(el('div', 'when', e.all_day ? 'Time TBA' : clock(p)));
    var what = el('div', 'what');
    var tags = el('div', 'tag-row');
    if (e.cancelled) tags.appendChild(el('span', 'tag cancelled', 'Cancelled'));
    else if (isHearing(e)) tags.appendChild(el('span', 'tag open', 'Public hearing'));
    else tags.appendChild(el('span', 'tag', (e.bills || []).length ? 'Committee meeting' : 'Work session'));
    // A busy committee can touch many topics; two tags are enough to scan by,
    // with the topic being followed always shown first.
    var tops = (e.topics || []).filter(function (t) { return TOPICS[t]; });
    if (state.topic && tops.indexOf(state.topic) > 0) tops = [state.topic].concat(tops.filter(function (t) { return t !== state.topic; }));
    tops.slice(0, 2).forEach(function (t) { tags.appendChild(el('span', 'tag topic', TOPICS[t])); });
    what.appendChild(tags);
    what.appendChild(el('h3', null, e.title));
    what.appendChild(el('p', 'meta', e.location || 'Olympia'));
    if ((e.bills || []).length) what.appendChild(billBlock(e));
    else if ((e.highlights || []).length) {
      var box = el('div', 'agenda');
      box.appendChild(el('p', 'agenda-label', 'On the agenda'));
      var ul = el('ul');
      e.highlights.forEach(function (h) { ul.appendChild(el('li', null, h)); });
      if (e.highlights_more) ul.appendChild(el('li', 'more-items', 'and ' + e.highlights_more + ' more'));
      box.appendChild(ul);
      what.appendChild(box);
    }
    art.appendChild(what);

    var actions = el('div', 'actions');
    var link = function (href, text, download) {
      var a = el('a', null, text);
      a.href = href;
      a.setAttribute('aria-label', text + ': ' + e.title + ', ' + longDay(p.key));
      if (download) a.download = download; else a.rel = 'noopener';
      actions.appendChild(a);
    };
    if (safeUrl(e.url)) link(e.url, 'Full agenda');
    if (!e.cancelled && isHearing(e)) link(CSI, 'Testify or sign in');
    if (!e.cancelled) link('https://tvw.org/', 'Watch on TVW');
    if (!e.cancelled) link(icsLink(e), 'Add to my calendar', 'civicswa-hearing.ics');
    art.appendChild(actions);
    return art;
  }

  function upcoming() {
    var from = todayKey();
    return state.events.filter(function (e) { return e.category === 'legislature' && e.start.slice(0, 10) >= from; });
  }

  function renderDays() {
    var box = $('days');
    box.textContent = '';
    var t = todayKey(), counts = {};
    upcoming().forEach(function (e) { var k = e.start.slice(0, 10); counts[k] = (counts[k] || 0) + 1; });
    var keys = Object.keys(counts).sort().slice(0, 8);
    if (keys.indexOf(t) === -1) keys.unshift(t);
    var all = el('button', 'chip', 'All upcoming');
    all.type = 'button';
    all.setAttribute('aria-pressed', String(state.day === 'all'));
    all.addEventListener('click', function () { state.day = 'all'; update(); });
    keys.forEach(function (k) {
      var b = el('button', 'chip', shortDay(k) + (counts[k] ? ' (' + counts[k] + ')' : ''));
      b.type = 'button';
      b.setAttribute('aria-pressed', String(state.day === k));
      b.setAttribute('aria-label', longDay(k) + ': ' + (counts[k] || 0) + (counts[k] === 1 ? ' meeting' : ' meetings'));
      b.addEventListener('click', function () { state.day = k; update(); });
      box.appendChild(b);
    });
    box.appendChild(all);
  }

  function renderTopics() {
    var present = {};
    upcoming().forEach(function (e) { (e.topics || []).forEach(function (t) { present[t] = true; }); });
    var keys = Object.keys(TOPICS).filter(function (k) { return present[k] || k === state.topic; });
    $('topics-wrap').hidden = !keys.length;
    var box = $('topics');
    box.textContent = '';
    keys.forEach(function (k) {
      var b = el('button', 'chip', TOPICS[k]);
      b.type = 'button';
      b.setAttribute('aria-pressed', String(state.topic === k));
      b.addEventListener('click', function () {
        state.topic = state.topic === k ? '' : k;
        if (state.topic) state.day = 'all';
        update();
      });
      box.appendChild(b);
    });
  }

  function emptyMessage() {
    var t = todayKey();
    // Between sessions no agenda carries bills, so a bill number can't match.
    if (state.q && /^(?:[a-z]{0,3}[hs]b|[hs]j[rm]|[hs]cr)\s*\d{3,4}$/i.test(state.q) &&
        !state.events.some(function (e) { return e.bills && e.bills.length; })) {
      return 'No committee agenda lists bills right now. Bill hearings show up here once the Legislature schedules them, mostly during the session that starts each January.';
    }
    if (filtering()) return 'No upcoming committee meetings match. Try another word or topic, or check back as committees post their agendas.';
    var msg = 'No committee meetings are scheduled ' + (state.day === t ? 'today' : 'on this day') + '.';
    if (t < SESSION_START) msg += ' Between sessions, committees meet only a few days a month. The 2027 session starts Monday, January 11, and most committees meet every weekday after that.';
    return msg;
  }

  function renderList() {
    var list = $('list');
    list.textContent = '';
    var rows = upcoming().filter(eventMatches);
    if (state.day !== 'all') rows = rows.filter(function (e) { return e.start.slice(0, 10) === state.day; });
    rows.sort(function (a, b) { return a.start < b.start ? -1 : a.start > b.start ? 1 : a.title.localeCompare(b.title); });

    var hearings = rows.filter(function (e) { return !e.cancelled && isHearing(e); }).length;
    $('day-heading').textContent = state.day === 'all'
      ? (state.topic ? TOPICS[state.topic] + ': all upcoming' : 'All upcoming committee meetings')
      : longDay(state.day);
    $('day-count').textContent = rows.length + (rows.length === 1 ? ' meeting' : ' meetings') +
      (hearings ? ' · ' + hearings + (hearings === 1 ? ' public hearing' : ' public hearings') : '');

    if (!rows.length) { list.appendChild(el('p', 'empty', emptyMessage())); return; }
    var last = '';
    rows.forEach(function (e) {
      var k = e.start.slice(0, 10);
      if (state.day === 'all' && k !== last) { list.appendChild(el('h3', 'day-head', longDay(k))); last = k; }
      list.appendChild(card(e));
    });
  }

  function saveUrl() {
    var q = new URLSearchParams();
    if (state.day && state.day !== todayKey()) q.set('day', state.day);
    if (state.topic) q.set('topic', state.topic);
    if (state.q) q.set('q', state.q);
    var s = q.toString();
    try { history.replaceState(null, '', location.pathname + (s ? '?' + s : '')); } catch (err) { /* file:// */ }
  }

  function update() { renderDays(); renderTopics(); renderList(); saveUrl(); }

  function start() {
    var params = new URLSearchParams(location.search);
    state.topic = TOPICS[params.get('topic')] ? params.get('topic') : '';
    state.q = (params.get('q') || '').slice(0, 80);
    var d = params.get('day') || '';
    state.day = /^\d{4}-\d{2}-\d{2}$/.test(d) || d === 'all' ? d : '';
    $('bill').value = state.q;
    var timer;
    $('bill').addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        state.q = $('bill').value.trim().slice(0, 80);
        if (state.q) state.day = 'all';
        update();
      }, 200);
    });

    fetch('data/events.json').then(function (r) { return r.json(); }).then(function (data) {
      state.events = data.events || [];
      if (data.generated) {
        $('updated').textContent = 'Last refreshed ' + new Date(data.generated).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }) + '.';
      }
      if (!state.day) {
        // Open on today, or on the next day that has meetings.
        var t = todayKey();
        var next = upcoming().map(function (e) { return e.start.slice(0, 10); }).sort()[0];
        state.day = filtering() ? 'all' : (upcoming().some(function (e) { return e.start.slice(0, 10) === t; }) || !next ? t : next);
      }
      update();
    }).catch(function () {
      $('list').textContent = '';
      $('list').appendChild(el('p', 'empty', 'The meeting list didn’t load. Refresh the page, or see the Legislature’s committee schedule at leg.wa.gov.'));
    });
  }
  start();
})();
