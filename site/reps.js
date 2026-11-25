/* CivicsWA "Who represents you" lookup.
   The address goes straight from the visitor's browser to the U.S. Census
   Bureau geocoder, which returns the districts it sits in. districts.js then
   sends only the map point (not the address) to state map services for
   special districts. CivicsWA has no server, so it never receives or stores
   the address. Names come from data/officials.json, rebuilt nightly. */
(function () {
  'use strict';

  // Spanish pages (html lang="es", data-base="../") get Spanish text and load
  // data from one folder up. Official names of offices and districts stay in
  // English, with a Spanish label beside them.
  var ES = (document.documentElement.lang || '').slice(0, 2) === 'es';
  var BASE = document.documentElement.getAttribute('data-base') || '';
  function L(en, es) { return ES ? es : en; }
  // Links to outside sites, which are in English, say so on Spanish pages.
  var EN = ES ? ' (en inglés)' : '';

  var GEOCODER = 'https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress';
  var LEG_FINDER = 'https://app.leg.wa.gov/districtfinder/';

  // Local governments with a council or commission page we have checked.
  var LOCAL = {
    places: {
      Olympia: { label: 'Olympia City Council', es: 'Concejo municipal de Olympia (Olympia City Council)', url: 'https://olympia.legistar.com/Calendar.aspx', note: 'Meetings, agendas and members', esNote: 'reuniones, agendas y miembros' },
      Lacey: { label: 'Lacey City Council', es: 'Concejo municipal de Lacey (Lacey City Council)', url: 'https://cityoflacey.org/government/lacey-city-council/', note: 'Members and meeting schedule', esNote: 'miembros y calendario de reuniones' },
      Spokane: { label: 'Spokane City Council', es: 'Concejo municipal de Spokane (Spokane City Council)', url: 'https://my.spokanecity.org/citycouncil/meetings', note: 'Meetings, agendas and how to take part', esNote: 'reuniones, agendas y cómo participar' }
    },
    counties: {
      Thurston: { label: 'Thurston County Board of County Commissioners', es: 'Junta de comisionados del condado de Thurston (Thurston County Board of County Commissioners)', url: 'https://www.thurstoncountywa.gov/departments/board-county-commissioners/meetings-public-hearings-and-work-session-agendas', note: 'Meetings and agendas', esNote: 'reuniones y agendas' }
    }
  };

  // Swearing-in days for the next new terms. Around each one (60 days before to
  // 14 days after) the cards name the date; otherwise they show a general note.
  // Update after each general election: the Legislature on the second Monday
  // of January in odd years, Congress on January 3.
  var NEW_TERM = { legislature: '2027-01-11', congress: '2027-01-03' };
  var NEW_TERM_BEFORE = 60, NEW_TERM_AFTER = 14;

  function newTermNote(key, today) {
    var day = NEW_TERM[key];
    if (!day) return '';
    var now = today || new Date();
    var at = new Date(day + 'T12:00:00');
    // Whole calendar days from today to the swearing-in day.
    var diff = Math.round((Date.UTC(at.getFullYear(), at.getMonth(), at.getDate()) -
      Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5);
    if (diff > NEW_TERM_BEFORE || diff < -NEW_TERM_AFTER) return '';
    var when = at.toLocaleDateString(ES ? 'es-US' : 'en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    if (ES) {
      return diff >= 0
        ? 'Los nuevos miembros asumen el cargo el ' + when + '. Esta lista se actualiza después de que juren su cargo.'
        : 'Los nuevos miembros asumieron el cargo el ' + when + '. Esta lista puede tardar unos días en ponerse al día.';
    }
    return diff >= 0
      ? 'New members take office on ' + when + '. This list updates after they are sworn in.'
      : 'New members took office on ' + when + '. This list may take a few days to catch up.';
  }

  var PARTIES = { Democrat: 'Partido Demócrata', Democratic: 'Partido Demócrata', Republican: 'Partido Republicano', Independent: 'Independiente' };

  var officials = null;
  var localData = null;
  var $ = function (id) { return document.getElementById(id); };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function safeUrl(url) { return /^https?:\/\//i.test(url || '') ? url : ''; }
  function link(href, text) {
    var a = el('a', null, text);
    a.href = href;
    a.rel = 'noopener';
    return a;
  }
  // A link to an outside website: on Spanish pages it says it's in English.
  function outLink(href, text) {
    var a = link(href, text + EN);
    if (ES) a.hreflang = 'en';
    return a;
  }

  function geocode(address) {
    return new Promise(function (resolve, reject) {
      var name = '__civicswa_geo_' + Date.now();
      var script = document.createElement('script');
      var timer = setTimeout(function () { finish(); reject(new Error('timeout')); }, 20000);
      function finish() { clearTimeout(timer); delete window[name]; script.remove(); }
      window[name] = function (data) { finish(); resolve(data); };
      script.onerror = function () { finish(); reject(new Error('network')); };
      script.src = GEOCODER + '?address=' + encodeURIComponent(address) +
        '&benchmark=Public_AR_Current&vintage=Current_Current&layers=all&format=jsonp&callback=' + name;
      document.head.appendChild(script);
    });
  }

  // Layer names carry a year or Congress number ("2026 State Legislative
  // Districts - Upper"), so match on the stable part of the name.
  function layer(geographies, pattern) {
    var key = Object.keys(geographies).filter(function (k) { return pattern.test(k); })[0];
    var rows = key ? geographies[key] : null;
    return rows && rows[0] ? rows[0].BASENAME : '';
  }

  // Full names ("Olympia School District") from every layer that matches.
  function names(geographies, pattern) {
    var out = [];
    Object.keys(geographies).filter(function (k) { return pattern.test(k); }).forEach(function (k) {
      (geographies[k] || []).forEach(function (row) {
        if (row.NAME && out.indexOf(row.NAME) < 0) out.push(row.NAME);
      });
    });
    return out;
  }

  function districtItem(list, d) {
    var li = el('li', 'district');
    li.appendChild(el('strong', null, d.label + ': '));
    li.appendChild(document.createTextNode(d.name));
    if (d.note) li.appendChild(el('span', 'muted', d.note));
    list.appendChild(li);
  }

  // One card listing every district the address sits in. The districts the
  // Census lookup already named show right away; special districts and
  // transit come from two more map services, which get only the map point.
  function districtsCard(g, match, parts) {
    var card = section(L('Your districts', 'Sus distritos'), L('Every district you live in', 'Todos los distritos donde usted vive'));
    var list = el('ul', 'districts');
    card.appendChild(list);
    var add = function (d) { districtItem(list, d); };
    if (ES) {
      if (parts.cd) add({ label: 'Cámara de Representantes de EE. UU. (U.S. House)', name: 'Distrito Congresional ' + parts.cd + ' (Congressional District ' + parts.cd + ')' });
      if (parts.ld) add({ label: 'Legislatura estatal', name: 'Distrito Legislativo ' + parts.ld + ' (Legislative District ' + parts.ld + ')', note: 'En este distrito usted elige a un senador estatal y a dos representantes estatales.' });
      if (parts.county) add({ label: 'Condado', name: 'Condado de ' + parts.county + ' (' + parts.county + ' County)' });
      add({ label: 'Ciudad', name: parts.city ? 'Ciudad de ' + parts.city : 'Zona no incorporada (fuera de los límites de una ciudad)' });
    } else {
      if (parts.cd) add({ label: 'U.S. House', name: 'Congressional District ' + parts.cd });
      if (parts.ld) add({ label: 'State Legislature', name: 'Legislative District ' + parts.ld, note: 'You elect one state senator and two state representatives from this district.' });
      if (parts.county) add({ label: 'County', name: parts.county + ' County' });
      add({ label: 'City', name: parts.city ? 'City of ' + parts.city : 'Unincorporated (outside city limits)' });
    }
    names(g, /School Districts/).forEach(function (n) {
      add({ label: L('School district', 'Distrito escolar'), name: n, note: L('Elected school board directors run your public schools.', 'Los miembros de la junta escolar (school board directors), elegidos por los votantes, dirigen sus escuelas públicas.') });
    });
    var D = window.CivicsWADistricts;
    var coa = D && parts.county ? D.courtOfAppeals(parts.county) : null;
    if (coa) add(coa);
    names(g, /American Indian Reservations|Off-Reservation Trust Lands/).forEach(function (n) {
      add({ label: L('Tribal land', 'Tierras tribales'), name: n, note: L('This address is on tribal land. The tribe’s own government serves its members here.', 'Esta dirección está en tierras tribales. El propio gobierno de la tribu atiende aquí a sus miembros.') });
    });

    var status = el('p', 'muted', L('Looking up fire, library, port, utility, transit and other special districts…', 'Buscando los distritos de bomberos, bibliotecas, puertos, servicios públicos, transporte público y otros distritos especiales…'));
    card.appendChild(status);
    var c = match.coordinates || {};
    if (!D || typeof c.x !== 'number' || typeof c.y !== 'number') {
      status.textContent = L('We could not look up special districts for this address.', 'No pudimos buscar los distritos especiales para esta dirección.');
      return card;
    }
    D.lookup(c.x, c.y, parts.county).then(function (r) {
      (r.transit || []).forEach(add);
      var sp = r.special;
      (sp ? sp.districts : []).forEach(add);
      status.textContent = '';
      if (!sp || !r.transit) {
        status.appendChild(document.createTextNode(L('Part of the special district lookup did not respond, so this list may be missing some districts. Try again in a few minutes.',
          'Una parte de la búsqueda de distritos especiales no respondió, así que puede que falten algunos distritos en esta lista. Inténtelo de nuevo en unos minutos.')));
      } else if (ES) {
        status.appendChild(document.createTextNode('Los distritos especiales vienen de los mapas de distritos tributarios de ' + sp.year + ' del Departamento de Ingresos de Washington (Washington Department of Revenue). ' +
          (sp.taxCodeArea ? 'Su área de código tributario (tax code area) es la ' + sp.taxCodeArea + ', el número que aparece en el estado de cuenta del impuesto a la propiedad. ' : '') +
          'Las agencias de transporte público vienen del Departamento de Transporte del estado (WSDOT).'));
      } else {
        status.appendChild(document.createTextNode('Special districts come from the Washington Department of Revenue’s ' + sp.year + ' taxing district maps' + (sp.taxCodeArea ? ' (tax code area ' + sp.taxCodeArea + ', the number on a property tax statement)' : '') + ' and transit agencies from WSDOT.'));
      }
      card.appendChild(el('p', 'muted', L('Not listed here: county commissioner or council districts, city council districts, voting precincts and conservation districts. Your county elections office can tell you those.',
        'No aparecen aquí: los distritos de los comisionados o del concejo del condado, los distritos del concejo municipal, los precintos electorales y los distritos de conservación. La oficina de elecciones de su condado puede decirle cuáles son los suyos.')));
    });
    return card;
  }

  function person(p) {
    var li = el('li', 'person');
    li.appendChild(el('strong', null, p.name));
    if (p.party) li.appendChild(el('span', 'muted', ' · ' + (ES && PARTIES[p.party] || p.party)));
    var contact = el('div', 'contact');
    if (p.phone) contact.appendChild(link('tel:' + p.phone.replace(/[^\d+]/g, ''), p.phone));
    if (p.email) contact.appendChild(link('mailto:' + p.email, p.email));
    if (safeUrl(p.url)) contact.appendChild(outLink(p.url, L('Website', 'Sitio web')));
    if (contact.children.length) li.appendChild(contact);
    return li;
  }

  function section(title, subtitle) {
    var card = el('section', 'card');
    card.appendChild(el('span', 'eyebrow', title));
    if (subtitle) card.appendChild(el('h3', null, subtitle));
    return card;
  }

  function people(card, list, emptyText) {
    if (list && list.length) {
      var ul = el('ul', 'people');
      list.forEach(function (p) { ul.appendChild(person(p)); });
      card.appendChild(ul);
    } else {
      card.appendChild(el('p', 'muted', emptyText));
    }
  }

  // Official website and boards page for counties and the larger cities,
  // from data/local.json (the same list the Engage guides' "Near you" boxes use).
  function extraLinks(card, place) {
    if (!place) return;
    var p = el('p');
    p.appendChild(outLink(place.site, L('Official website', 'Sitio web oficial')));
    p.appendChild(document.createTextNode(' · '));
    p.appendChild(outLink(place.boards, place.appoints ? L('Commissioners (they appoint board members)', 'Comisionados (ellos nombran a los miembros de las juntas)') : L('Boards and commissions', 'Juntas y comisiones')));
    card.appendChild(p);
  }

  function localCard(title, name, entry, fallback, place) {
    var card = section(title, name);
    if (!entry && place) { extraLinks(card, place); return card; }
    if (entry) {
      var p = el('p');
      p.appendChild(outLink(entry.url, ES ? entry.es : entry.label));
      p.appendChild(document.createTextNode(': ' + (ES ? entry.esNote : entry.note) + '.'));
      card.appendChild(p);
    } else {
      card.appendChild(el('p', 'muted', fallback));
    }
    extraLinks(card, place);
    return card;
  }

  function render(match) {
    var g = match.geographies;
    var out = $('results');
    out.textContent = '';

    var state = layer(g, /^States$/);
    if (state && state !== 'Washington') {
      out.appendChild(el('p', 'empty', L('That address is in ' + state + '. CivicsWA only covers Washington.', 'Esa dirección está en ' + state + '. CivicsWA solo cubre el estado de Washington.')));
      return;
    }

    var city = layer(g, /Incorporated Places/);
    var county = layer(g, /^Counties$/);
    var ld = layer(g, /State Legislative Districts - Upper/);
    var cd = layer(g, /Congressional Districts/);

    out.appendChild(el('p', 'muted', L('Showing results for ', 'Resultados para ') + match.matchedAddress + '.'));
    out.appendChild(districtsCard(g, match, { city: city, county: county, ld: ld, cd: cd }));
    if (window.CivicsWALocal && county) {
      // Remember only the county and city, so the Engage guides can show local links.
      window.CivicsWALocal.save({ county: county, city: localData && localData.cities[city] ? city : '' });
    }

    out.appendChild(city
      ? localCard(L('City', 'Ciudad'), L('City of ', 'Ciudad de ') + city, LOCAL.places[city], L('Your mayor and council members are listed on the city’s website. We have not added a direct link for this city yet.',
        'Su alcalde y los miembros del concejo municipal aparecen en el sitio web de la ciudad. Todavía no hemos agregado un enlace directo para esta ciudad.'), localData && localData.cities[city])
      : localCard(L('City', 'Ciudad'), L('Outside city limits', 'Fuera de los límites de una ciudad'), null, L('This address is in an unincorporated area, so the county is your local government.',
        'Esta dirección está en una zona no incorporada, así que el condado es su gobierno local.')));

    if (county) {
      out.appendChild(localCard(L('County', 'Condado'), L(county + ' County', 'Condado de ' + county), LOCAL.counties[county], L('Your county commissioners or council members are listed on the county’s website. We have not added a direct link for this county yet.',
        'Los comisionados o los miembros del concejo de su condado aparecen en el sitio web del condado. Todavía no hemos agregado un enlace directo para este condado.'), localData && localData.counties[county]));
    }

    var seats = (officials && officials.legislators && officials.legislators[ld]) || null;
    var leg = section(L('State Legislature', 'Legislatura estatal'), ld ? L('Legislative District ', 'Distrito Legislativo ') + ld : L('Legislative district not found', 'No se encontró el distrito legislativo'));
    if (seats) {
      leg.appendChild(el('h4', null, L('State Senator', 'Senador o senadora estatal')));
      people(leg, seats.senate, L('No senator listed.', 'No aparece ningún senador.'));
      leg.appendChild(el('h4', null, L('State Representatives', 'Representantes estatales')));
      people(leg, seats.house, L('No representatives listed.', 'No aparece ningún representante.'));
      if (seats.senate.length > 1 || seats.house.length > 2) {
        leg.appendChild(el('p', 'muted', L('This district changed members during the current term, so the list includes someone who has left the seat.',
          'Este distrito cambió de miembros durante el período actual, así que la lista incluye a alguien que ya dejó el cargo.')));
      }
    } else {
      leg.appendChild(el('p', 'muted', L('We could not load the member list.', 'No pudimos cargar la lista de miembros.')));
    }
    var confirm = el('p', 'muted');
    confirm.appendChild(document.createTextNode((newTermNote('legislature') || L('Newly elected members take office in January.', 'Los miembros recién elegidos asumen el cargo en enero.')) +
      L(' Confirm current members with the Legislature’s ', ' Confirme quiénes son los miembros actuales con el buscador de distritos de la Legislatura, ')));
    confirm.appendChild(outLink(LEG_FINDER, 'District Finder'));
    confirm.appendChild(document.createTextNode('.'));
    leg.appendChild(confirm);
    out.appendChild(leg);

    var congress = (officials && officials.congress) || { senators: [], house: {} };
    var fed = section(L('Congress', 'Congreso'), cd ? L('Congressional District ', 'Distrito Congresional ') + cd : L('Congressional district not found', 'No se encontró el distrito congresional'));
    fed.appendChild(el('h4', null, L('U.S. Representative', 'Representante en la Cámara de Representantes de EE. UU.')));
    people(fed, congress.house[cd] ? [congress.house[cd]] : [], L('No representative listed.', 'No aparece ningún representante.'));
    fed.appendChild(el('h4', null, L('U.S. Senators', 'Senadores de EE. UU.')));
    people(fed, congress.senators, L('No senators listed.', 'No aparece ningún senador.'));
    fed.appendChild(el('p', 'muted', newTermNote('congress') || L('Newly elected members of Congress take office on January 3 after the election. This list updates after they are sworn in.',
      'Los miembros del Congreso recién elegidos asumen el cargo el 3 de enero después de la elección. Esta lista se actualiza después de que juren su cargo.')));
    out.appendChild(fed);
  }

  $('lookup').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var address = $('address').value.trim();
    var out = $('results');
    out.textContent = '';
    if (address.length < 6) {
      out.appendChild(el('p', 'empty', L('Enter a street address with a city or ZIP code, like 601 4th Ave E, Olympia.', 'Escriba una dirección con la ciudad o el código postal, por ejemplo: 601 4th Ave E, Olympia.')));
      return;
    }
    out.appendChild(el('p', 'empty', L('Looking up your districts…', 'Buscando sus distritos…')));
    geocode(/\bwa\b|washington/i.test(address) ? address : address + ', WA').then(function (data) {
      var matches = data && data.result && data.result.addressMatches;
      if (!matches || !matches.length) {
        out.textContent = '';
        out.appendChild(el('p', 'empty', L('We could not find that address. Check the street number, spelling and ZIP code, and leave off apartment numbers. If it still does not work, try a nearby street address. Some government buildings are not in the Census Bureau’s address list.',
          'No pudimos encontrar esa dirección. Revise el número, la ortografía y el código postal, y no incluya el número de apartamento. Si aun así no funciona, pruebe con una dirección cercana. Algunos edificios del gobierno no están en la lista de direcciones de la Oficina del Censo.')));
        return;
      }
      render(matches[0]);
    }).catch(function () {
      out.textContent = '';
      var p = el('p', 'empty');
      p.appendChild(document.createTextNode(L('The address lookup is not responding right now. You can use the Legislature’s ', 'La búsqueda de direcciones no responde en este momento. En su lugar, puede usar el buscador de distritos de la Legislatura, ')));
      p.appendChild(outLink(LEG_FINDER, 'District Finder'));
      p.appendChild(document.createTextNode(L(' instead.', '.')));
      out.appendChild(p);
    });
  });

  fetch(BASE + 'data/local.json').then(function (r) { return r.json(); }).then(function (d) { localData = d; }).catch(function () {});
  fetch(BASE + 'data/officials.json').then(function (r) { return r.json(); }).then(function (d) { officials = d; }).catch(function () {});
})();
