// Kleine, view-übergreifende Helfer.

// HTML-escapen fuer sichere String-Interpolation in Templates (Spielernamen etc.).
export function esc(str) {
  return String(str == null ? '' : str).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
