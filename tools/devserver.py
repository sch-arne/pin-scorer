"""Lokaler Entwicklungs-Server fuer Pin-Scorer.

Wie `python -m http.server`, aber mit `Cache-Control: no-store`.

Warum: ohne Cache-Header cacht der Browser die Dateien heuristisch. Beim Entwickeln
sieht man dann nach einem Reload manchmal noch den ALTEN Stand — besonders tueckisch
bei ES-Modulen, weil dann Teile der App neu und Teile alt sind. Genau darum schaltet
`index.html` auf localhost auch schon den Service-Worker ab; die Header hier sind das
fehlende Gegenstueck dazu.

Start (aus der Projektwurzel):

    python tools/devserver.py          # http://localhost:5173
    python tools/devserver.py 8080     # anderer Port
"""

import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5173
    handler = partial(NoCacheHandler, directory=WURZEL)
    with ThreadingHTTPServer(('', port), handler) as httpd:
        print(f'Pin-Scorer laeuft auf http://localhost:{port}/ (ohne Browser-Cache)')
        print(f'E2E-Tests:  http://localhost:{port}/tests/e2e/')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nbeendet')


if __name__ == '__main__':
    main()
