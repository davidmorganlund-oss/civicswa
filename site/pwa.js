// Installs CivicsWA as an app: registers the offline cache and shows the
// "Put CivicsWA on your phone" box where the browser supports it.
(function () {
  'use strict';
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
    window.addEventListener('load', function () { navigator.serviceWorker.register('/sw.js').catch(function () {}); });
  }
  // Offline, the app shows the meetings it last saved; say so up top.
  function offlineNote() {
    var bar = document.querySelector('.notice');
    if (!bar) return;
    var note = document.getElementById('offline-note');
    if (navigator.onLine) { if (note) note.remove(); return; }
    if (note) return;
    note = document.createElement('strong');
    note.id = 'offline-note';
    note.style.display = 'block';
    note.textContent = document.documentElement.lang === 'es'
      ? 'Sin conexión: mostrando las reuniones guardadas en este dispositivo. Pueden estar desactualizadas.'
      : 'You’re offline. Showing the meetings saved on this device, which may be out of date.';
    bar.appendChild(note);
  }
  window.addEventListener('online', offlineNote);
  window.addEventListener('offline', offlineNote);
  document.addEventListener('DOMContentLoaded', offlineNote);
  if (document.readyState !== 'loading') offlineNote();

  var box = document.getElementById('install');
  if (!box) return;
  var es = document.documentElement.lang === 'es';
  var standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  if (standalone) return;
  var text = document.getElementById('install-text');
  var btn = document.getElementById('install-btn');
  var ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);

  if (ios) {
    text.textContent = es
      ? 'En Safari, toque el botón Compartir (el cuadro con la flecha hacia arriba) y luego “Agregar a inicio”. CivicsWA aparecerá con sus otras aplicaciones.'
      : 'In Safari, tap the Share button (the square with the arrow pointing up), then “Add to Home Screen.” CivicsWA shows up with your other apps.';
    box.hidden = false;
    return;
  }
  var deferred = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferred = e;
    text.textContent = es
      ? 'Instálelo y CivicsWA se abre como una aplicación, desde su pantalla de inicio. Gratis, sin cuenta y sin anuncios.'
      : 'Install it and CivicsWA opens like an app, right from your home screen. Free, no account, no ads.';
    btn.hidden = false;
    box.hidden = false;
  });
  btn.addEventListener('click', function () {
    if (!deferred) return;
    deferred.prompt();
    deferred.userChoice.then(function () { deferred = null; box.hidden = true; });
  });
  window.addEventListener('appinstalled', function () { box.hidden = true; });
})();
