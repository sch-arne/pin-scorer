// Kleine, view-übergreifende Helfer.

// HTML-escapen fuer sichere String-Interpolation in Templates (Spielernamen etc.).
export function esc(str) {
  return String(str == null ? '' : str).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Lesbare Kurzfassung eines Fehlers fuer Toast/Statuszeile.
//
// Supabase/PostgREST liefert kein Error-Objekt mit sprechendem message-Feld allein, sondern
// { message, details, hint, code }. Frueher zeigten die Sync-Views pauschal
// "fehlgeschlagen — online?" — dahinter verschwanden fehlende Anmeldung, RLS-Ablehnung und
// eine noch nicht eingespielte SQL-Migration ununterscheidbar. Genau die drei muss man aber
// auseinanderhalten koennen, ohne die Konsole zu oeffnen.
export function fehlerText(e, fallback = 'unbekannter Fehler') {
  if (!e) return fallback;
  const teile = [e.message, e.details, e.hint]
    .map((t) => (typeof t === 'string' ? t.trim() : ''))
    .filter(Boolean);
  const text = teile.length ? teile[0] : (typeof e === 'string' ? e.trim() : '');
  const code = e.code ? ` (${e.code})` : '';
  // Kein verwertbarer Text (z. B. ein leeres Fehlerobjekt): den Fallback zeigen statt
  // "[object Object]" — der Code bleibt trotzdem dran, er ist oft der einzige Hinweis.
  return (text || fallback) + code;
}
