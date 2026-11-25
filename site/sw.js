// CivicsWA service worker. Network first for everything, so people always
// see tonight's refresh when they're online; the last copy is kept so the
// app still opens, with the meetings it last loaded, when they're offline.
var CACHE = 'civicswa-v7';
var SHELL = ['/', '/index.html', '/hearings.html', '/styles.css', '/app.js', '/hearings.js', '/local.js', '/pwa.js', '/spotlight.js',
  '/data/calendar.json', '/fonts/montserrat-latin-wght-normal.woff2', '/icons/icon-192.png', '/barnone-phoenix.png'];

self.addEventListener('install', function (event) {
  // Cache each file on its own, so one missing file (calendar.json before the
  // first nightly build writes it) doesn't stop the app from installing.
  event.waitUntil(caches.open(CACHE).then(function (c) {
    return Promise.all(SHELL.map(function (u) { return c.add(u).catch(function () {}); }));
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // fonts, agency sites: leave alone
  event.respondWith(fetch(req).then(function (res) {
    if (res && res.ok && res.type === 'basic') {
      var copy = res.clone();
      caches.open(CACHE).then(function (c) { c.put(req, copy); });
    }
    return res;
  }).catch(function () {
    return caches.match(req, { ignoreSearch: req.mode === 'navigate' }).then(function (hit) {
      if (hit) return hit;
      if (req.mode === 'navigate') return caches.match('/index.html');
      return Response.error();
    });
  }));
});
