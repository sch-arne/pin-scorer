// Schlanker hash-basierter Router.
// Views registrieren sich mit einer Route (z.B. "/menu") und einer render()-Funktion,
// die einen DOM-Knoten oder HTML-String zurückgibt. Neue Views (Spielmodi) lassen sich
// später einfach per register() ergaenzen, ohne den Router zu aendern.

const routes = new Map();
let mountEl = null;
let notFoundHandler = null;

export function register(path, renderFn) {
  routes.set(path, renderFn);
}

export function navigate(path) {
  // Setzt den Hash; loest ueber "hashchange" das Rendern aus.
  if (currentPath() === path) {
    render();
  } else {
    location.hash = '#' + path;
  }
}

export function currentPath() {
  const raw = location.hash.replace(/^#/, '');
  return raw || '/menu';
}

function render() {
  if (!mountEl) return;
  const path = currentPath();
  const fn = routes.get(path) || notFoundHandler;
  mountEl.innerHTML = '';
  if (!fn) {
    mountEl.textContent = 'Seite nicht gefunden: ' + path;
    return;
  }
  const out = fn();
  if (out instanceof Node) {
    mountEl.appendChild(out);
  } else if (typeof out === 'string') {
    mountEl.innerHTML = out;
  }
  window.scrollTo(0, 0);
}

export function start({ mount, notFound } = {}) {
  mountEl = typeof mount === 'string' ? document.querySelector(mount) : mount;
  notFoundHandler = notFound || null;
  window.addEventListener('hashchange', render);
  render();
}
