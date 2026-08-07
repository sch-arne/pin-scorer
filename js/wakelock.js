// Hält den Bildschirm wach, solange die App offen ist (Screen Wake Lock API).
// Das Lock gibt der Browser bei Tab-Wechsel / Display-Aus automatisch frei,
// darum wird es bei jedem Sichtbar-Werden erneut angefordert.

let sentinel = null;
let aktiv = false; // gewünschter Zustand: soll das Lock gehalten werden?

async function anfordern() {
  if (!aktiv) return;
  if (!('wakeLock' in navigator)) return; // nicht unterstützt (z. B. iOS < 16.4)
  if (sentinel) return; // schon aktiv
  if (document.visibilityState !== 'visible') return; // nur bei sichtbarer Seite möglich
  try {
    sentinel = await navigator.wakeLock.request('screen');
    sentinel.addEventListener('release', () => {
      sentinel = null; // vom System freigegeben (Tab weg, Akku-Sparmodus …)
    });
  } catch (err) {
    // Häufig NotAllowedError, wenn kein Gesture/kein Fokus – still schlucken,
    // beim nächsten Interaktions-/Sichtbarkeits-Event klappt es meist.
    sentinel = null;
    console.warn('Wake Lock nicht möglich:', err && err.name);
  }
}

async function freigeben() {
  aktiv = false;
  if (sentinel) {
    try { await sentinel.release(); } catch { /* egal */ }
    sentinel = null;
  }
}

/** Bildschirm-Wachhalten einschalten und dauerhaft am Leben halten. */
export function keepAwake() {
  aktiv = true;
  anfordern();
}

/** Wachhalten wieder abschalten (falls je gebraucht). */
export function releaseAwake() {
  freigeben();
}

// Nach Tab-Wechsel / Aufwecken erneut anfordern.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') anfordern();
});
// Manche Browser vergeben das Lock erst nach einer echten Nutzer-Interaktion.
window.addEventListener('pointerdown', anfordern, { passive: true });
