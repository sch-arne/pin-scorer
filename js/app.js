// Einstiegspunkt: registriert Views beim Router und startet ihn.

import { register, start } from './router.js';
import { keepAwake } from './wakelock.js';
import { menuView } from './views/menu.js';
import { neuesSpielView } from './views/neues-spiel.js';
import { statistikenView } from './views/statistiken.js';
import { setupWkView } from './views/setup-wk.js';
import { setupWettkampfView } from './views/setup-wettkampf.js';
import { wettkampfHubView } from './views/wettkampf-hub.js';
import { spielLaufendView } from './views/spiel-laufend.js';
import { setupHausnummernView } from './views/setup-hausnummern.js';
import { hausnummernSpielView } from './views/hausnummern-spiel.js';
import { beitretenView } from './views/beitreten.js';
import { spielerView } from './views/login.js';
import { anlagenView } from './views/anlagen.js';
import { importSportwinnerView } from './views/import-sportwinner.js';
import { importSwWebView } from './views/import-sw-web.js';
import { overlayView } from './views/overlay.js';

register('/menu', menuView);
register('/neues-spiel', neuesSpielView);
register('/statistiken', statistikenView);
register('/setup/sportkegler-wk', setupWkView);
register('/setup/wettkampf', setupWettkampfView);
register('/wettkampf', wettkampfHubView);
// Setup eines Wettkampf-Durchgangs = dieselbe Maske wie Training, nur im Wettkampf-Modus.
register('/setup/wettkampf-durchgang', () => setupWkView({ wettkampf: true }));
register('/spiel-laufend', spielLaufendView);
// Hausnummern: eigener Spiel-Typ mit eigener Erfassung (Ziffernfolge statt Holzsumme).
register('/setup/hausnummern', setupHausnummernView);
register('/hausnummern', hausnummernSpielView);
register('/beitreten', beitretenView);
register('/spieler', spielerView);
register('/anlagen', anlagenView);
register('/import/sportwinner', importSportwinnerView);
// Zweiter Import-Weg: ein GESPIELTES Spiel aus dem oeffentlichen Ergebnisdienst holen
// (ohne Bruecke, rein per Webabfrage ueber das Relay).
register('/import/sportwinner-web', importSwWebView);
// OBS-Livestream-Overlay (transparent, per Beitritts-Code): #/overlay?code=XXXX
register('/overlay', overlayView);

start({ mount: '#app', notFound: menuView });

// Bildschirm wach halten, solange die App offen ist.
keepAwake();
