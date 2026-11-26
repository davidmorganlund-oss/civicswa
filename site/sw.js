/* CivicsWA service worker: lets the site be installed as an app and open
   without a signal.
   - Online, pages, scripts and data (calendar, roster) always come from the
     network, and data skips the browser's own cache, so nobody sees
     yesterday's meetings or last month's officials.
   - Every page and data file someone opens is also kept on the device, so
     offline the app shows the last copy it saw (the "recent" cache, kept
     between updates and trimmed to the newest 60 files).
   - Fonts and images rarely change, so they come from the device first.
   BUILD is replaced at publish with a fingerprint of the site's files (see
   "Stamp the app version" in .github/workflows/refresh.yml), so any change to
   the site installs a fresh copy of the app shell; nightly data refreshes
   don't need one. */
var PREFIX = 'civicswa-';
var BUILD = '__BUILD__';
var SHELL_CACHE = PREFIX + 'shell-' + BUILD;
var RECENT_CACHE = PREFIX + 'recent';
var RECENT_MAX = 60;
var SHELL = [
  '/', '/index.html', '/hearings.html', '/es/', '/es/index.html', '/es/hearings.html', '/styles.css',
  '/app.js', '/hearings.js', '/local.js', '/pwa.js', '/spotlight.js', '/data/calendar.json',
  '/fonts/montserrat-latin-wght-normal.woff2', '/icons/icon-192.png', '/barnone-phoenix.png',
  '/manifest.webmanifest', '/icons/icon-512.png', '/icons/apple-touch-icon.png', '/reps.html', '/reps.js',
  '/districts.js', '/engage.html', '/es/engage.html', '/es/reps.html', '/about.html'];

self.addEventListener('install', function (e) {
  // Cache each file on its own, so one missing file can't stop the install.
  e.waitUntil(caches.open(SHELL_CACHE).then(function (c) {
    return Promise.all(SHELL.map(function (u) { return c.add(new Request(u, { cache: 'reload' })).catch(function () {}); }));
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  // Drop older app shells (and the caches from before this layout), keep recent pages.
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) {
      return k.indexOf(PREFIX) === 0 && k !== SHELL_CACHE && k !== RECENT_CACHE;
    }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

function trim(cache) {
  return cache.keys().then(function (keys) {
    return Promise.all(keys.slice(0, Math.max(0, keys.length - RECENT_MAX)).map(function (k) { return cache.delete(k); }));
  });
}

function keep(req, res) {
  if (!res || !res.ok || res.type !== 'basic' || res.redirected) return;
  var copy = res.clone();
  caches.open(RECENT_CACHE).then(function (c) {
    // Delete first so the newest copy moves to the end and trimming drops the oldest.
    return c.delete(req, { ignoreSearch: true }).then(function () { return c.put(req, copy); }).then(function () { return trim(c); });
  }).catch(function () {});
}

function saved(req, nav) {
  var opts = { ignoreSearch: nav };
  return caches.open(RECENT_CACHE).then(function (c) { return c.match(req, opts); }).then(function (hit) {
    return hit || caches.open(SHELL_CACHE).then(function (c) { return c.match(req, opts); });
  });
}

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== location.origin) return;  // other sites (agendas, Census, maps) go straight to the network
  var path = url.pathname;
  // Subscription feeds and calendar files are for feed readers and calendar apps; leave them alone.
  if (path.indexOf('/data/feeds/') === 0 || path.indexOf('/data/ics/') === 0) return;
  var nav = req.mode === 'navigate';

  if (/\.(woff2?|png|ico|svg|jpe?g|webp|gif)$/i.test(path)) {
    e.respondWith(caches.open(SHELL_CACHE).then(function (c) { return c.match(req); }).then(function (hit) {
      return hit || fetch(req);
    }));
    return;
  }

  var isData = path.indexOf('/data/') === 0 && !nav;
  e.respondWith(fetch(isData ? new Request(req, { cache: 'no-cache' }) : req).then(function (res) {
    if (res.ok) { keep(req, res); return res; }
    // A server error on data: better the last good copy than an empty calendar.
    if (isData && res.status >= 500) return saved(req, false).then(function (hit) { return hit || res; });
    return res;
  }).catch(function () {
    return saved(req, nav).then(function (hit) {
      if (hit) return hit;
      // Offline on a page we haven't saved: show the calendar in the same language.
      if (nav) {
        var home = path.indexOf('/es/') === 0 ? '/es/index.html' : '/index.html';
        return saved(new Request(home), false).then(function (h) { return h || saved(new Request('/index.html'), false); })
          .then(function (h) { return h || Response.error(); });
      }
      return Response.error();
    });
  }));
});
