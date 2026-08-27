// Lokale Brücke zum Vereins-PC (Sportwinner interface.dll). Die Brücke öffnet die App mit
// einem Deeplink-Parameter `?push=http://127.0.0.1:<port>`; darüber
//   • meldet die App den Beitrittscode + die Match-Identität zurück (damit die Brücke beim
//     Neustart genau dieses Match wiedererkennt und den Browser automatisch wieder beitreten
//     lässt), und
//   • schickt die App die Ergebnisse (Volle/Abräumen/Fehler je Slot & Bahn), die die Brücke
//     per DLL-Setter nach Sportwinner schreibt.
// Nur auf dem Vereins-PC relevant — andere Geräte bekommen den `?push`-Parameter nie und
// schreiben daher nichts. `http://127.0.0.1` ist als „potentially trustworthy" von der
// Mixed-Content-Sperre ausgenommen, auch von einer per https gehosteten App aus.

const KEY = 'pins-scorer:sw-push'; // Basis-URL der Brücke, für diese Browser-Session

const clean = (u) => (u || '').replace(/\/+$/, '');

export function setBruecke(url) {
  try { if (url) sessionStorage.setItem(KEY, clean(url)); } catch (e) { /* privater Modus */ }
}

export function getBruecke() {
  try { return sessionStorage.getItem(KEY) || ''; } catch (e) { return ''; }
}

export function clearBruecke() {
  try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ }
}

// POST an die Brücke. Liefert das geparste Antwort-Objekt (z. B. { ok, offen, geschrieben,
// allow_write }) oder `null`, wenn die Brücke nicht erreichbar ist / mit Fehler antwortet.
async function post(pfad, body) {
  const base = getBruecke();
  if (!base) return null;
  try {
    const res = await fetch(base + pfad, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      keepalive: true,
    });
    if (!res || !res.ok) return null;
    try { return await res.json(); } catch (e) { return {}; }
  } catch (e) {
    return null; // Brücke gerade nicht erreichbar — App läuft normal weiter.
  }
}

// Beitrittscode + Match-Identität an die Brücke melden (Auto-Wiederbeitritt beim Neustart).
export function meldeWettkampf(info) {
  return post('/wettkampf', info);
}

// Ein gemerktes Match bei der Brücke wieder vergessen lassen — z. B. wenn der Wettkampf
// gelöscht bzw. sein Link gekappt wurde. Danach zeigt die Brücke beim nächsten Öffnen aus
// Sportwinner wieder den Import, statt automatisch dem (nun toten) Code beizutreten. Die
// Identifikation läuft bevorzugt über den Code (den die App sicher kennt); optional spielNr.
export function vergissWettkampf(info) {
  return post('/wettkampf', { vergessen: true, ...info });
}

// Ergebnis-Auftrag an die Brücke schicken. Leerer Auftrag -> nichts tun.
export function pushErgebnis(payload) {
  if (!payload || !Array.isArray(payload.updates) || !payload.updates.length) return Promise.resolve(null);
  return post('/ergebnis', payload);
}

// Live-Status der Brücke abfragen: ist die Sportwinner-Schnittstelle wirklich offen?
// Liefert { offen, allow_write, pending } oder `null`, wenn die Brücke nicht läuft.
export async function holeStatus() {
  const base = getBruecke();
  if (!base) return null;
  try {
    const res = await fetch(base + '/status', { method: 'GET', cache: 'no-store' });
    if (!res || !res.ok) return null;
    return await res.json();
  } catch (e) {
    return null; // Brücke nicht erreichbar
  }
}

// Aktuellen Sportwinner-Live-Stand von der Brücke holen (Aufstellung + Wurfwerte je Slot/Bahn).
// Liefert das Snapshot-Objekt (seiten.{G,GG}.aufstellung[…]) oder `null` (Brücke nicht erreichbar).
// Basis für die Konflikt-Erkennung: die App vergleicht das mit ihrem eigenen Stand.
export async function holeSportwinnerLive() {
  const base = getBruecke();
  if (!base) return null;
  try {
    const res = await fetch(base + '/sportwinner', { method: 'GET', cache: 'no-store' });
    if (!res || !res.ok) return null;
    return await res.json();
  } catch (e) {
    return null; // Brücke nicht erreichbar
  }
}

// Übersetzt den Brücken-Status (aus holeStatus) in ein Badge: state (für die Farbe/CSS-Klasse
// `is-<state>`), Kurz-Label und Hinweis-Text. `null` = Brücke nicht erreichbar.
export function brueckeStatusInfo(st) {
  if (st === null) {
    return { state: 'offline', label: 'Brücke offline',
      hint: 'Brücke nicht erreichbar — läuft die Brücke auf diesem PC?' };
  }
  if (!st.offen) {
    const n = st.pending || 0;
    const wartet = n ? ` (${n} Bahn${n === 1 ? '' : 'en'} warten)` : '';
    return { state: 'closed', label: 'Schnittstelle zu',
      hint: 'Sportwinner-Schnittstelle geschlossen — in Sportwinner das Spiel öffnen und „Start" drücken.' + wartet };
  }
  if (!st.allow_write) {
    return { state: 'readonly', label: 'offen · nur lesen',
      hint: 'Schnittstelle offen — Rückschreiben ist gesperrt (Brücke ohne --allow-write gestartet).' };
  }
  return { state: 'open', label: 'Schnittstelle offen',
    hint: 'Schnittstelle offen — Ergebnisse werden nach Sportwinner geschrieben.' };
}

// Kurze Rückmeldung nach einem Ergebnis-Push (nutzt die Antwort der Brücke, nicht nur „ok").
export function brueckePushText(res) {
  const t = new Date().toLocaleTimeString('de-DE');
  if (!res || !res.allow_write) return 'Empfangen · Rückschreiben gesperrt (Testmodus) · ' + t;
  if (!res.offen) return 'Empfangen · Schnittstelle geschlossen, wird nachgezogen · ' + t;
  return 'An Sportwinner übertragen · ' + t;
}
