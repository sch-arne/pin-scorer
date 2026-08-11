// Schlanker Service-Worker für Pin-Scorer.
// Zweck: saubere Installierbarkeit auf Android + Robustheit bei kurzen
// Verbindungsaussetzern. Cache-first für die App-Shell, Netzwerk-Fallback.
// Bei Änderungen an den App-Dateien CACHE hochzählen (v1 -> v2 ...).

const CACHE = 'pin-scorer-v32';

// Relative Pfade -> funktionieren auch unter GitHub-Pages-Unterpfad /<repo>/
const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './css/app.css',
  './js/app.js',
  './js/router.js',
  './js/store.js',
  './js/backend/supabase.js',
  './js/backend/geraet.js',
  './js/backend/sync.js',
  './js/backend/auth.js',
  './js/data/standardbilder-default.js',
  './js/util.js',
  './js/wakelock.js',
  './js/logic/teilsaetze.js',
  './js/logic/abraeumen.js',
  './js/logic/holz.js',
  './js/logic/bahnwechsel.js',
  './js/logic/statistik.js',
  './js/views/menu.js',
  './js/views/neues-spiel.js',
  './js/views/beitreten.js',
  './js/views/login.js',
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

  const url = new URL(req.url);
  // Supabase-API (REST/Auth/Realtime) NIE cachen — immer frisch übers Netz,
  // sonst würden Live-Daten veralten. Der SW fasst diese Requests gar nicht an.
  if (url.hostname.endsWith('.supabase.co')) return;

  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req)
        .then((res) => {
          // Erfolgreiche GETs cachen: eigene App-Shell + das Supabase-JS vom CDN
          // (esm.sh) für Folgestarts/Offline.
          if (res && res.ok && (url.origin === self.location.origin || url.hostname === 'esm.sh')) {
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
