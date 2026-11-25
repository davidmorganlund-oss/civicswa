/* CivicsWA coverage page: lists the calendars the nightly run reads, from
   data/status.json, grouped by county, plus counties with links only. */
(function () {
  'use strict';
  // Pages under es/ set <html lang="es" data-base="../">: Spanish wording, data one folder up.
  var ES = (document.documentElement.lang || '').slice(0, 2) === 'es';
  var BASE = document.documentElement.getAttribute('data-base') || '';
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function day(iso) {
    var d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleDateString(ES ? 'es-US' : 'en-US', { month: 'short', day: 'numeric', timeZone: 'America/Los_Angeles' });
  }
  Promise.all([
    fetch(BASE + 'data/status.json').then(function (r) { return r.json(); }),
    fetch(BASE + 'data/local.json').then(function (r) { return r.json(); }).catch(function () { return {}; })
  ]).then(function (res) {
    var sources = res[0].sources || [], local = res[1] || {};
    var by = {};
    sources.forEach(function (s) { (by[s.county || 'Statewide'] = by[s.county || 'Statewide'] || []).push(s); });
    var counties = Object.keys(local.counties || {}).sort();
    var withData = counties.filter(function (c) { return by[c]; }).length;
    $('cov-summary').textContent = ES
      ? sources.length + ' calendarios públicos leídos cada noche, que cubren ' + withData +
        ' de los 39 condados de Washington, además de la Legislatura estatal. Última lectura: ' + day(res[0].generated) + '.'
      : sources.length + ' public calendars read every night, covering ' + withData +
        ' of Washington’s 39 counties, plus the State Legislature. Last run ' + day(res[0].generated) + '.';
    var list = $('cov-list');
    ['Statewide'].concat(counties).forEach(function (c) {
      var rows = by[c] || [];
      var box = el('details', 'card cov');
      var sum = ES
        ? el('summary', null, (c === 'Statewide' ? 'Todo el estado' : 'Condado de ' + c) + ' · ' +
          (rows.length ? rows.length + (rows.length === 1 ? ' calendario' : ' calendarios') : 'solo enlaces'))
        : el('summary', null, (c === 'Statewide' ? 'Statewide' : c + ' County') + ' · ' +
          (rows.length ? rows.length + (rows.length === 1 ? ' calendar' : ' calendars') : 'links only'));
      box.appendChild(sum);
      if (!rows.length) {
        var info = (local.counties || {})[c] || {};
        box.appendChild(el('p', null, ES ? 'Todavía no podemos leer los calendarios de reuniones de este condado.' : 'We can’t read this county’s meeting calendars yet.'));
        var href = info.meetings || info.site;
        if (href) {
          var a = el('a', 'link', ES ? 'Reuniones y agendas del condado de ' + c + ' (en inglés)' : c + ' County meetings and agendas');
          a.href = href; a.rel = 'noopener';
          if (ES) a.hreflang = 'en';
          box.appendChild(a);
        }
      } else {
        var ul = el('ul', 'cov-rows');
        rows.sort(function (a, b) { return a.name.localeCompare(b.name); }).forEach(function (s) {
          var li = el('li');
          var name = el('a', null, s.name); name.href = s.homepage || '#'; name.rel = 'noopener';
          li.appendChild(name);
          var ok = s.state === 'ok' || s.state === 'quiet';
          li.appendChild(el('span', 'cov-state' + (ok ? '' : ' warn'),
            ES
              ? (ok ? ' · leído el ' + day(s.last_success || s.checked) + (s.state === 'quiet' ? ', sin reuniones en este momento' : '') : ' · sin respuesta desde el ' + day(s.failing_since || s.checked) + '; mostramos lo que tenía antes')
              : (ok ? ' · read ' + day(s.last_success || s.checked) + (s.state === 'quiet' ? ', no meetings listed right now' : '') : ' · couldn’t reach since ' + day(s.failing_since || s.checked) + '; showing what it listed before')));
          ul.appendChild(li);
        });
        box.appendChild(ul);
      }
      list.appendChild(box);
    });
  }).catch(function () { $('cov-summary').textContent = ES ? 'No se pudo cargar la cobertura. Inténtelo más tarde.' : 'Coverage could not be loaded. Please try again later.'; });
})();
