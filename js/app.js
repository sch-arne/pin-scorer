// Einstiegspunkt: registriert Views beim Router und startet ihn.

import { register, start } from './router.js';
import { keepAwake } from './wakelock.js';
import { menuView } from './views/menu.js';
import { neuesSpielView } from './views/neues-spiel.js';
import { statistikenView } from './views/statistiken.js';
import { setupWkView } from './views/setup-wk.js';
import { spielLaufendView } from './views/spiel-laufend.js';
import { beitretenView } from './views/beitreten.js';

register('/menu', menuView);
register('/neues-spiel', neuesSpielView);
register('/statistiken', statistikenView);
register('/setup/sportkegler-wk', setupWkView);
register('/spiel-laufend', spielLaufendView);
register('/beitreten', beitretenView);

start({ mount: '#app', notFound: menuView });

// Bildschirm wach halten, solange die App offen ist.
keepAwake();
