/* CivicsWA "Near you" box. Any element with class "near-you" becomes a
   county and city picker that shows that place's own pages. The choice is
   remembered in this browser only (localStorage), and the address lookup
   on reps.html fills it in too. Data: data/local.json. */
(function () {
  'use strict';

  var KEY = 'civicswa.place';
  // Spanish pages (html lang="es") get Spanish text. Outside sites are in
  // English, so their links say so.
  var ES = (document.documentElement.lang || '').slice(0, 2) === 'es';
  var STATE_BOARDS = 'https://governor.wa.gov/boards-and-commissions/boards-commissions/apply-serve';
  var OSPI_DIRECTORY = 'https://eds.ospi.k12.wa.us/DirectoryEDS.aspx';
  // Other local governments in the county (data/local.json "districts"), by kind.
  var DISTRICT_NOTES = {
    esd: 'Educational service district: serves the school districts in this area. Board meetings and agendas.',
    port: 'Port district: elected commissioners. Meetings, agendas and how to comment.',
    library: 'Library: board of trustees meetings and agendas.',
    utility: 'Public utility district: elected commissioners set rates. Meetings and agendas.',
    transit: 'Transit agency: board meetings, agendas and service changes.',
    hospital: 'Public hospital district: elected commissioners. Meetings and agendas.',
    fire: 'Fire district or authority: elected commissioners. Meetings and agendas.',
    other: 'Board meetings and agendas are on its website.'
  };
  var DISTRICT_NOTES_ES = {
    esd: 'Distrito de servicios educativos (educational service district): atiende a los distritos escolares de esta zona. Reuniones y agendas de la junta.',
    port: 'Distrito portuario: comisionados elegidos. Reuniones, agendas y cómo opinar.',
    library: 'Biblioteca: reuniones y agendas de los miembros de la junta directiva (board of trustees).',
    utility: 'Distrito de servicios públicos (public utility district): comisionados elegidos fijan las tarifas. Reuniones y agendas.',
    transit: 'Agencia de transporte público: reuniones de la junta, agendas y cambios en el servicio.',
    hospital: 'Distrito hospitalario público: comisionados elegidos. Reuniones y agendas.',
    fire: 'Distrito o autoridad de bomberos: comisionados elegidos. Reuniones y agendas.',
    other: 'Las reuniones y agendas de la junta están en su sitio web.'
  };
  function L(en, es) { return ES ? es : en; }
  // A CivicsWA page in the visitor's language.
  function page(name) { return base() + (ES ? 'es/' : '') + name; }

  function base() {
    var s = document.querySelector('script[src$="local.js"]');
    return s ? s.getAttribute('src').replace(/local\.js$/, '') : '';
  }
  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; }
  }
  function save(place) {
    try { localStorage.setItem(KEY, JSON.stringify(place)); } catch (e) { /* private mode */ }
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function item(list, href, text, note) {
    var li = el('li');
    var outside = /^https?:\/\//i.test(href);
    var a = el('a', null, ES && outside ? text + ' (en inglés)' : text);
    a.href = href;
    a.rel = 'noopener';
    if (ES && outside) a.hreflang = 'en';
    if (note) a.appendChild(el('span', null, note));
    li.appendChild(a);
    list.appendChild(li);
  }
  function option(select, value, text, selected) {
    var o = el('option', null, text);
    o.value = value;
    if (selected) o.selected = true;
    select.appendChild(o);
  }

  function links(data, show, place) {
    var ul = el('ul', 'guide-links near-links');
    var county = data.counties[place.county];
    var city = place.city && data.cities[place.city];
    show.forEach(function (kind) {
      if (kind === 'boards') {
        if (city && city.boards) item(ul, city.boards, L('City of ' + place.city + ' boards and commissions', 'Juntas y comisiones de la ciudad de ' + place.city), L('Openings, applications and what each board does.', 'Vacantes, solicitudes y qué hace cada junta.'));
        else if (city) item(ul, city.site, L('City of ', 'Ciudad de ') + place.city, L('The city does not list its boards on one page we could link. Look under City Hall or Government on its website, or ask the city clerk about openings.',
          'La ciudad no publica sus juntas en una sola página que podamos enlazar. Busque en la sección del ayuntamiento o del gobierno (City Hall o Government) de su sitio web, o pregunte por las vacantes a la secretaría municipal (city clerk).'));
        if (county) item(ul, county.boards, county.appoints ? L(place.county + ' County commissioners', 'Comisionados del condado de ' + place.county) : L(place.county + ' County boards and commissions', 'Juntas y comisiones del condado de ' + place.county),
          county.appoints ? L('This county does not list its boards on one page. The commissioners make appointments, so ask their office about openings.', 'Este condado no publica sus juntas en una sola página. Los comisionados hacen los nombramientos, así que pregunte por las vacantes en su oficina.')
            : L('County advisory boards, openings and how to apply.', 'Juntas asesoras del condado, vacantes y cómo presentar una solicitud.'));
        item(ul, STATE_BOARDS, L('State boards and commissions', 'Juntas y comisiones estatales'), L('Apply to the Governor’s office any time.', 'Puede presentar su solicitud a la oficina del Gobernador en cualquier momento.'));
      }
      if (kind === 'site') {
        if (city) item(ul, city.site, L('City of ', 'Ciudad de ') + place.city, L('Official website: council, departments and service requests.', 'Sitio web oficial: concejo, departamentos y solicitudes de servicio.'));
        if (county) item(ul, county.site, L(place.county + ' County', 'Condado de ' + place.county), L('Official website: commissioners or council, departments and services.', 'Sitio web oficial: comisionados o concejo, departamentos y servicios.'));
      }
      if (kind === 'schools') {
        if (place.county) item(ul, page('./?cat=school'), L('School board meetings in ' + place.county + ' County', 'Reuniones de juntas escolares en el condado de ' + place.county),
          L('The CivicsWA calendar, filtered to school boards. If your district isn’t there yet, use its website.', 'El calendario de CivicsWA, filtrado por juntas escolares. Si su distrito todavía no aparece, use su sitio web.'));
        ((county && county.schools) || []).forEach(function (d) {
          item(ul, d.site, d.name, L('District website: school board meetings, agendas and elections.', 'Sitio web del distrito: reuniones de la junta escolar, agendas y elecciones.'));
        });
        item(ul, OSPI_DIRECTORY, L('Find your school district', 'Encuentre su distrito escolar'), L('OSPI’s directory of every district, with its address and superintendent’s contact.',
          'El directorio de OSPI (la Oficina del Superintendente de Instrucción Pública) con cada distrito, su dirección y el contacto de su superintendente.'));
      }
      if (kind === 'districts') {
        var list = (county && county.districts) || [];
        var notes = ES ? DISTRICT_NOTES_ES : DISTRICT_NOTES;
        list.forEach(function (d) { item(ul, d.site, d.name, notes[d.kind] || notes.other); });
      }
      if (kind === 'meetings') {
        if (place.county) item(ul, page('./'), L('Public meetings in ' + place.county + ' County', 'Reuniones públicas en el condado de ' + place.county), L('The CivicsWA calendar, set to your county.', 'El calendario de CivicsWA, con su condado seleccionado.'));
        if (city) item(ul, city.site, L('City of ' + place.city + ' meetings', 'Reuniones de la ciudad de ' + place.city), L('Council agendas are on the city’s website.', 'Las agendas del concejo están en el sitio web de la ciudad.'));
        if (county) item(ul, county.site, L(place.county + ' County meetings', 'Reuniones del condado de ' + place.county), L('Commission or council agendas are on the county’s website.', 'Las agendas de la comisión o del concejo están en el sitio web del condado.'));
      }
    });
    return ul;
  }

  function build(box, data) {
    var show = (box.getAttribute('data-show') || 'boards').split(',');
    var place = load();
    if (!data.counties[place.county]) place = {};

    box.textContent = '';
    box.appendChild(el('h2', null, box.getAttribute('data-title') || L('Near you', 'Cerca de usted')));
    var form = el('div', 'near-pick');
    var cl = el('label', null, L('County', 'Condado'));
    var cs = el('select');
    cs.id = 'near-county-' + Math.random().toString(36).slice(2, 7);
    cl.htmlFor = cs.id;
    option(cs, '', L('Choose your county', 'Elija su condado'), !place.county);
    Object.keys(data.counties).sort().forEach(function (c) { option(cs, c, L(c + ' County', 'Condado de ' + c), c === place.county); });
    var tl = el('label', null, L('City or town', 'Ciudad o pueblo'));
    var ts = el('select');
    ts.id = cs.id.replace('county', 'city');
    tl.htmlFor = ts.id;
    [cl, cs, tl, ts].forEach(function (n) { form.appendChild(n); });
    box.appendChild(form);
    var out = el('div', 'near-out');
    box.appendChild(out);
    var help = el('p', 'muted');
    help.appendChild(document.createTextNode(L('Not sure which county or city you’re in? ', '¿No sabe en qué condado o ciudad está? ')));
    var a = el('a', null, L('Look up your address', 'Busque su dirección'));
    a.href = page('reps.html');
    help.appendChild(a);
    help.appendChild(document.createTextNode(L('. We remember your choice on this device only.', '. Recordamos su elección solo en este dispositivo.')));
    box.appendChild(help);

    function fillCities() {
      ts.textContent = '';
      var names = Object.keys(data.cities).filter(function (n) { return data.cities[n].county === cs.value; }).sort();
      option(ts, '', cs.value ? L('Another town, or outside city limits', 'Otro pueblo, o fuera de los límites de la ciudad') : L('Choose a county first', 'Primero elija un condado'), !place.city);
      names.forEach(function (n) { option(ts, n, n, n === place.city); });
      ts.disabled = !cs.value;
    }
    function draw() {
      out.textContent = '';
      if (!place.county) return;
      out.appendChild(links(data, show, place));
      if (!place.city && show.indexOf('boards') !== -1) {
        out.appendChild(el('p', 'muted', L('Most cities and towns post their boards on their own website, usually under City Hall or Government. If you live outside city limits, the county is your local government.',
          'La mayoría de las ciudades y pueblos publican sus juntas en su propio sitio web, por lo general en la sección del ayuntamiento o del gobierno (City Hall o Government). Si usted vive fuera de los límites de la ciudad, el condado es su gobierno local.')));
      }
    }
    cs.addEventListener('change', function () { place = { county: cs.value }; save(place); fillCities(); draw(); });
    ts.addEventListener('change', function () { place = { county: cs.value, city: ts.value }; save(place); draw(); });
    fillCities();
    draw();
  }

  window.CivicsWALocal = { save: save, load: load };
  var boxes = document.querySelectorAll('.near-you');
  if (!boxes.length) return;
  fetch(base() + 'data/local.json').then(function (r) { return r.json(); }).then(function (data) {
    Array.prototype.forEach.call(boxes, function (b) { build(b, data); });
  }).catch(function () {
    Array.prototype.forEach.call(boxes, function (b) { b.hidden = true; });
  });
})();
