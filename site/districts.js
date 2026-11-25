/* CivicsWA special-district lookup.
   Takes the map point the Census Bureau returned for an address and asks two
   free public map services which districts that point falls in:
   - Washington Department of Revenue taxing district boundaries (fire,
     library, port, PUD, hospital, park, water, sewer and other districts)
   - WSDOT public transit agency boundaries
   Only the map coordinates are sent, never the address, and nothing is kept.
   Both services answer JSONP, so this works from a static site with no key. */
(function (root) {
  'use strict';

  // Spanish pages (html lang="es") get Spanish labels and notes. Official
  // district names stay in English, as the state publishes them.
  var ES = !!(root.document && (root.document.documentElement.lang || '').slice(0, 2) === 'es');

  var DOR = 'https://webgis.dor.wa.gov/arcgis/rest/services/Programs/WADOR_PropertyTax/MapServer';
  var TRANSIT = 'https://services.arcgis.com/IYrj3otxNjPsrTRD/ArcGIS/rest/services/Public_Transit_Agency_Boundaries/FeatureServer/1/query';

  // Court of Appeals divisions and election districts, RCW 2.06.020.
  var APPEALS = {
    'I-1': ['King'],
    'I-2': ['Snohomish'],
    'I-3': ['Island', 'San Juan', 'Skagit', 'Whatcom'],
    'II-1': ['Pierce'],
    'II-2': ['Clallam', 'Grays Harbor', 'Jefferson', 'Kitsap', 'Mason', 'Thurston'],
    'II-3': ['Clark', 'Cowlitz', 'Lewis', 'Pacific', 'Skamania', 'Wahkiakum'],
    'III-1': ['Ferry', 'Lincoln', 'Okanogan', 'Pend Oreille', 'Spokane', 'Stevens'],
    'III-2': ['Adams', 'Asotin', 'Benton', 'Columbia', 'Franklin', 'Garfield', 'Grant', 'Walla Walla', 'Whitman'],
    'III-3': ['Chelan', 'Douglas', 'Kittitas', 'Klickitat', 'Yakima']
  };

  // Regional and county library systems, by county. Used only when the
  // Department of Revenue says the address pays a library district levy.
  var LIBRARIES = {
    'Thurston': 'Timberland Regional Library', 'Mason': 'Timberland Regional Library',
    'Grays Harbor': 'Timberland Regional Library', 'Pacific': 'Timberland Regional Library',
    'Lewis': 'Timberland Regional Library',
    'King': 'King County Library System', 'Pierce': 'Pierce County Library System',
    'Snohomish': 'Sno-Isle Libraries', 'Island': 'Sno-Isle Libraries',
    'Kitsap': 'Kitsap Regional Library', 'Spokane': 'Spokane County Library District',
    'Clark': 'Fort Vancouver Regional Libraries', 'Skamania': 'Fort Vancouver Regional Libraries',
    'Klickitat': 'Fort Vancouver Regional Libraries', 'Whatcom': 'Whatcom County Library System',
    'Yakima': 'Yakima Valley Libraries',
    'Chelan': 'NCW Libraries', 'Douglas': 'NCW Libraries', 'Ferry': 'NCW Libraries',
    'Grant': 'NCW Libraries', 'Okanogan': 'NCW Libraries'
  };

  // District codes the Department of Revenue uses that aren't a plain number.
  var NAMED = {
    PRT: { SEA: 'Port of Seattle' },
    PRK: { SMPD: 'Seattle Park District', OMPD: 'Olympia Metropolitan Park District' },
    FZN: { KCFZ: 'King County Flood Control District' }
  };

  // What each Department of Revenue layer is, and who runs it. Layers left
  // out on purpose: SCH (the Census lookup names school districts), RTA
  // (the transit lookup names Sound Transit), CRD (every county has one),
  // FRY, APR and RSV (too few, and we couldn't confirm what they are).
  var TYPES = {
    FIR: { label: 'Fire', name: function (n, c) { return c + ' County Fire Protection District No. ' + n; },
      note: 'Fire and emergency response. Run by elected fire commissioners, or by a board of local elected officials for a regional fire authority.' },
    EMS: { label: 'Emergency medical services', name: function () { return 'EMS levy area'; },
      note: 'Voters here approved a property tax for ambulance and paramedic service.' },
    LIB: { label: 'Library', name: function (n, c) { return LIBRARIES[c] || c + ' County library district'; },
      note: 'Rural and regional library districts are run by trustees appointed by county commissioners.' },
    CLB: { label: 'Library buildings', name: function () { return 'Library capital facility area'; },
      note: 'Voters here approved a tax to build or fix up library buildings.' },
    HSP: { label: 'Hospital', name: function (n, c) { return c + ' County Public Hospital District No. ' + n; },
      note: 'Elected commissioners oversee the district’s hospital or clinics.' },
    PRT: { label: 'Port', name: function (n, c) { return c + ' County port district No. ' + n; },
      note: 'Elected port commissioners oversee marine terminals, marinas, airports or economic development.' },
    PUD: { label: 'Public utility', name: function (n, c) { return 'Public Utility District No. ' + n + ' of ' + c + ' County'; },
      note: 'Elected commissioners run this public electric, water or broadband utility.' },
    PRK: { label: 'Parks', name: function (n, c) { return c + ' County metropolitan park district'; },
      note: 'A park district with its own levy. Its board is either elected or made up of city council members.' },
    PKR: { label: 'Parks and recreation', name: function (n, c) { return c + ' County Park and Recreation District No. ' + n; },
      note: 'Elected commissioners run local parks and recreation programs.' },
    CEM: { label: 'Cemetery', name: function (n, c) { return c + ' County Cemetery District No. ' + n; },
      note: 'Elected commissioners look after local cemeteries.' },
    AIR: { label: 'Airport', name: function (n, c) { return c + ' County airport district'; },
      note: 'Runs a local public airport.' },
    FLD: { label: 'Flood control', name: function (n, c) { return c + ' County flood control district'; },
      note: 'Pays for levees and flood protection.' },
    FZN: { label: 'Flood control', name: function (n, c) { return c + ' County flood control zone district'; },
      note: 'Pays for flood protection. Most are governed by the county council or commissioners.' },
    MSQ: { label: 'Mosquito control', name: function (n, c) { return c + ' County mosquito control district'; },
      note: 'Run by a board appointed by the local governments it serves.' },
    SEW: { label: 'Sewer', name: function (n, c) { return c + ' County sewer district'; },
      note: 'Elected commissioners run local sewer service.' },
    WAT: { label: 'Water', name: function (n, c) { return c + ' County Water District No. ' + n; },
      note: 'Elected commissioners run local water service, and often sewer too.' }
  };
  // The same layers in Spanish. Names that are official titles stay in
  // English; names we build as a plain description are in Spanish.
  var TYPES_ES = {
    FIR: { label: 'Bomberos', name: TYPES.FIR.name,
      note: 'Bomberos y respuesta a emergencias. Lo dirigen comisionados de bomberos elegidos, o una junta de funcionarios locales elegidos en el caso de una autoridad regional de bomberos (regional fire authority).' },
    EMS: { label: 'Servicios médicos de emergencia', name: function () { return 'Zona del impuesto para servicios médicos de emergencia (EMS levy area)'; },
      note: 'Los votantes de esta zona aprobaron un impuesto a la propiedad para el servicio de ambulancias y paramédicos.' },
    LIB: { label: 'Biblioteca', name: function (n, c) { return LIBRARIES[c] || 'Distrito de bibliotecas del condado de ' + c; },
      note: 'Los distritos de bibliotecas rurales y regionales los dirigen miembros de la junta directiva (trustees) nombrados por los comisionados del condado.' },
    CLB: { label: 'Edificios de bibliotecas', name: function () { return 'Zona de instalaciones para bibliotecas (library capital facility area)'; },
      note: 'Los votantes de esta zona aprobaron un impuesto para construir o reparar edificios de bibliotecas.' },
    HSP: { label: 'Hospital', name: TYPES.HSP.name,
      note: 'Comisionados elegidos supervisan el hospital o las clínicas del distrito.' },
    PRT: { label: 'Puerto', name: function (n, c) { return 'Distrito portuario No. ' + n + ' del condado de ' + c; },
      note: 'Comisionados del puerto elegidos supervisan terminales marítimas, marinas, aeropuertos o el desarrollo económico.' },
    PUD: { label: 'Servicios públicos', name: TYPES.PUD.name,
      note: 'Comisionados elegidos dirigen este servicio público de electricidad, agua o internet de banda ancha.' },
    PRK: { label: 'Parques', name: function (n, c) { return 'Distrito metropolitano de parques del condado de ' + c; },
      note: 'Un distrito de parques con su propio impuesto. Su junta es elegida o está formada por miembros del concejo municipal.' },
    PKR: { label: 'Parques y recreación', name: TYPES.PKR.name,
      note: 'Comisionados elegidos dirigen los parques y los programas de recreación locales.' },
    CEM: { label: 'Cementerio', name: TYPES.CEM.name,
      note: 'Comisionados elegidos cuidan los cementerios locales.' },
    AIR: { label: 'Aeropuerto', name: function (n, c) { return 'Distrito aeroportuario del condado de ' + c; },
      note: 'Dirige un aeropuerto público local.' },
    FLD: { label: 'Control de inundaciones', name: function (n, c) { return 'Distrito de control de inundaciones del condado de ' + c; },
      note: 'Paga diques y obras de protección contra inundaciones.' },
    FZN: { label: 'Control de inundaciones', name: function (n, c) { return 'Distrito de zona de control de inundaciones del condado de ' + c; },
      note: 'Paga la protección contra inundaciones. La mayoría los gobierna el concejo o los comisionados del condado.' },
    MSQ: { label: 'Control de mosquitos', name: function (n, c) { return 'Distrito de control de mosquitos del condado de ' + c; },
      note: 'Lo dirige una junta nombrada por los gobiernos locales a los que sirve.' },
    SEW: { label: 'Alcantarillado', name: function (n, c) { return 'Distrito de alcantarillado del condado de ' + c; },
      note: 'Comisionados elegidos dirigen el servicio local de alcantarillado.' },
    WAT: { label: 'Agua', name: TYPES.WAT.name,
      note: 'Comisionados elegidos dirigen el servicio local de agua, y muchas veces también el de alcantarillado.' }
  };
  var ORDER = ['FIR', 'EMS', 'HSP', 'LIB', 'CLB', 'PRT', 'PUD', 'WAT', 'SEW', 'PKR', 'PRK', 'CEM', 'AIR', 'FLD', 'FZN', 'MSQ'];

  function titleCase(s) {
    return String(s).toLowerCase().replace(/\b[a-z]/g, function (c) { return c.toUpperCase(); });
  }

  function jsonp(url, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var name = '__civicswa_d' + Date.now() + Math.floor(Math.random() * 1e6);
      var script = document.createElement('script');
      var timer = setTimeout(function () { finish(); reject(new Error('timeout')); }, timeoutMs || 15000);
      function finish() { clearTimeout(timer); delete root[name]; script.remove(); }
      root[name] = function (data) { finish(); resolve(data); };
      script.onerror = function () { finish(); reject(new Error('network')); };
      script.src = url + (url.indexOf('?') < 0 ? '?' : '&') + 'callback=' + name;
      document.head.appendChild(script);
    });
  }

  // The service adds a new year group each year (named "2025", "2026"...),
  // which shifts layer ids. Pick the newest year and its layers by name.
  function newestYearLayers(service) {
    var layers = (service && service.layers) || [];
    var years = layers.filter(function (l) { return /^\d{4}$/.test(l.name); })
      .map(function (l) { return +l.name; });
    if (!years.length) return null;
    var year = String(Math.max.apply(null, years));
    var ids = {};
    layers.forEach(function (l) {
      var m = /^([A-Z]{3})(\d{4})$/.exec(l.name);
      if (m && m[2] === year && TYPES[m[1]]) ids[l.id] = m[1];
      if (m && m[2] === year && m[1] === 'TCA') ids[l.id] = 'TCA';
    });
    return { year: year, ids: ids };
  }

  // Fire codes can name more than one district ("11/WTRFA/11B"). Pieces
  // ending in B, or with GOB in them, are bond levies, not districts.
  function fireParts(code) {
    return String(code).split('/').map(function (s) { return s.trim(); })
      .filter(function (s) { return s && !/B$|GOB/.test(s); });
  }

  function describe(type, code, county, lang) {
    var es = lang ? lang === 'es' : ES;
    var t = (es ? TYPES_ES : TYPES)[type];
    var raw = String(code || '').trim();
    var n = /^\d+$/.test(raw) ? String(+raw) : '';
    var named = NAMED[type] && NAMED[type][raw];
    var name;
    if (named) name = named;
    else if (type === 'PRT' && !n && raw.length > 4) name = 'Port of ' + titleCase(raw);
    else if (type === 'FIR' && /RFA$/.test(raw)) name = es ? 'Autoridad regional de bomberos (regional fire authority; el estado la registra como ' + raw + ')' : 'Regional fire authority (listed by the state as ' + raw + ')';
    else if (n || type === 'EMS' || type === 'LIB' || type === 'CLB') name = t.name(n, county);
    else name = t.name('', county) + (es ? ' (el estado lo registra como ' : ' (listed by the state as ') + raw + ')';
    // Templates that need a number read badly without one.
    if (!n) name = name.replace(/ No\. ?/, ' ');
    name = name.replace(/\s{2,}/g, ' ').trim();
    return { type: type, label: t.label, name: name, note: t.note };
  }

  // Turn a Department of Revenue identify response into a list of districts.
  function fromDor(response, idTypes, county) {
    var out = [];
    var tca = '';
    var seen = {};
    ((response && response.results) || []).forEach(function (r) {
      var type = idTypes[r.layerId];
      var code = r.attributes && r.attributes.DISTATTRIB;
      if (!type || code == null || !String(code).trim()) return;
      if (type === 'TCA') { tca = String(code).trim(); return; }
      var codes = type === 'FIR' ? fireParts(code) : [code];
      codes.forEach(function (c) {
        var d = describe(type, c, county);
        if (seen[d.name]) return;
        seen[d.name] = true;
        out.push(d);
      });
    });
    out.sort(function (a, b) { return ORDER.indexOf(a.type) - ORDER.indexOf(b.type); });
    return { districts: out, taxCodeArea: tca };
  }

  var TRANSIT_NOTES = {
    'Public Transportation Benefit Area': 'Its board is made up of local elected officials from the area it serves.',
    'Regional Transit Authority': 'Its board is made up of local elected officials from King, Pierce and Snohomish counties, plus the state transportation secretary.',
    'County Public Transportation Authority': 'Run by the county.',
    'City Transit System': 'Run by the city.'
  };
  var TRANSIT_NOTES_ES = {
    'Public Transportation Benefit Area': 'Su junta está formada por funcionarios locales elegidos de la zona a la que sirve.',
    'Regional Transit Authority': 'Su junta está formada por funcionarios locales elegidos de los condados de King, Pierce y Snohomish, más el secretario estatal de transporte.',
    'County Public Transportation Authority': 'Lo dirige el condado.',
    'City Transit System': 'Lo dirige la ciudad.'
  };

  function fromTransit(response) {
    return ((response && response.features) || []).map(function (f) {
      var a = f.attributes || {};
      return { type: 'TRANSIT', label: ES ? 'Transporte público' : 'Transit', name: a.AgencyName, note: (ES ? TRANSIT_NOTES_ES : TRANSIT_NOTES)[a.AgencyType] || '' };
    }).filter(function (d) { return d.name; });
  }

  function courtOfAppeals(county) {
    var key = Object.keys(APPEALS).filter(function (k) { return APPEALS[k].indexOf(county) >= 0; })[0];
    if (!key) return null;
    var parts = key.split('-');
    if (ES) {
      return { type: 'COA', label: 'Corte de Apelaciones (Court of Appeals)', name: 'División ' + parts[0] + ', Distrito ' + parts[1],
        note: 'Usted vota por los jueces de apelaciones que se eligen en este distrito. Cumplen períodos de seis años.' };
    }
    return { type: 'COA', label: 'Court of Appeals', name: 'Division ' + parts[0] + ', District ' + parts[1],
      note: 'You vote for the appeals court judges elected from this district. They serve six-year terms.' };
  }

  var serviceInfo = null;
  function lookup(x, y, county) {
    var pt = encodeURIComponent(x + ',' + y);
    var dor = (serviceInfo ? Promise.resolve(serviceInfo) : jsonp(DOR + '?f=json').then(function (s) {
      serviceInfo = newestYearLayers(s);
      return serviceInfo;
    })).then(function (info) {
      if (!info) throw new Error('no layers');
      var ids = Object.keys(info.ids).join(',');
      var span = (x - 0.5) + ',' + (y - 0.5) + ',' + (x + 0.5) + ',' + (y + 0.5);
      return jsonp(DOR + '/identify?geometry=' + pt + '&geometryType=esriGeometryPoint&sr=4326' +
        '&layers=all:' + ids + '&tolerance=0&mapExtent=' + span + '&imageDisplay=100,100,96' +
        '&returnGeometry=false&f=json').then(function (r) {
        var res = fromDor(r, info.ids, county);
        res.year = info.year;
        return res;
      });
    });
    var transit = jsonp(TRANSIT + '?geometry=' + pt + '&geometryType=esriGeometryPoint&inSR=4326' +
      '&spatialRel=esriSpatialRelIntersects&outFields=AgencyName,AgencyType&returnGeometry=false&f=json')
      .then(fromTransit);
    return Promise.all([
      dor.catch(function () { return null; }),
      transit.catch(function () { return null; })
    ]).then(function (both) {
      return { special: both[0], transit: both[1] };
    });
  }

  var api = { lookup: lookup, fromDor: fromDor, fromTransit: fromTransit, newestYearLayers: newestYearLayers,
    describe: describe, courtOfAppeals: courtOfAppeals };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.CivicsWADistricts = api;
})(typeof window !== 'undefined' ? window : this);
