// Schlanker Service-Worker für Pin-Scorer.
// Zweck: saubere Installierbarkeit auf Android + Robustheit bei kurzen
// Verbindungsaussetzern. Cache-first für die App-Shell, Netzwerk-Fallback.
// Bei Änderungen an den App-Dateien CACHE hochzählen (v1 -> v2 ...).

const CACHE = 'pin-scorer-v1';

// Relative Pfade -> funktionieren auch unter GitHub-Pages-Unterpfad /<repo>/
const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './css/app.css',
  './js/app.js',
  './js/router.js',
  './js/store.js',
  './js/util.js',
  './js/logic/teilsaetze.js',
  './js/logic/abraeumen.js',
  './js/logic/holz.js',
  './js/logic/bahnwechsel.js',
  './js/views/menu.js',
  './js/views/neues-spiel.js',
  './js/views/setup-wk.js',
  './js/views/spiel-laufend.js',
  './js/views/statistiken.js',
  './assets/icon-192.png',
  './assets/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      // Einzelne fehlende Datei soll die Installation nicht sprengen
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req)
        .then((res) => {
          // Erfolgreiche Antworten gleichen Ursprungs nachträglich cachen
          if (res && res.ok && new URL(req.url).origin === self.location.origin) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => {
          // Offline und nicht im Cache: für Navigationsanfragen die App-Shell liefern
          if (req.mode === 'navigate') return caches.match('./index.html');
          return Response.error();
        });
    })
  );
});
