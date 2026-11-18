// CivicsWA service worker. Network first for everything, so people always
// see tonight's refresh when they're online; the last copy is kept so the
// app still opens, with the meetings it last loaded, when they're offline.
var CACHE = 'civicswa-v2';
var SHELL = ['/', '/index.html', '/hearings.html', '/styles.css', '/app.js', '/hearings.js', '/local.js', '/pwa.js',
  '/data/events.json', '/icons/icon-192.png', '/barnone-phoenix.png'];

self.addEventListener('install', function (event) {
  event.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
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
