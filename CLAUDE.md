# sky42 — guida per Claude

Console personale di follow-up del Sistema Solare. Gira 24/7 sul Mac mini,
tiene aggiornato un catalogo orbitale locale, precalcola nei tempi morti chi
torna alla portata dei telescopi, e la mattina dice **cosa osservare, da quale
sito e in quale finestra**.

Documenti: [IDEA.md](IDEA.md) è il progetto originale e non si tocca;
[README.md](README.md) dice cosa c'è e come si avvia; [MEMORANDUM.md](MEMORANDUM.md)
dice perché ogni cosa è com'è. Lo schema commentato sta in
[docs/schema.sql](docs/schema.sql), le formule in [docs/modelli.md](docs/modelli.md).

## Le cinque regole che non si violano

1. **Il catalogo è scaricato: SQLite è un indice rigenerabile — tranne cinque
   tabelle.** La prova è sempre la stessa: *se cancello `data/sky42.db` e
   riavvio, perdo qualcosa?* Per `target`, `orbit`, `screening_track`,
   `target_stats`, `night`, `observation_window` la risposta deve essere no:
   si riscaricano da ASTORB/MPC e si ricalcolano. Non vale per
   **`mpc_candidate` + `mpc_candidate_snapshot`** (l'MPC la lista NEOCP la
   riscrive e non conserva niente: quella storia esiste solo qui),
   **`state_transition`**, **`observation_log`**, **`watchlist`** e
   **`setup_calibration`**. Quelle cinque si salvano nel backup e non hanno
   chiavi esterne distruttive verso il gruppo rigenerabile: `observation_log`
   e `state_transition` puntano a `setup(id)` **senza CASCADE**, o rigenerare
   l'hardware cancellerebbe la storia delle osservazioni.

2. **Non si chiama JPL per cercare, solo per confermare.** Horizons e SBDB
   entrano *dopo* lo screening, sulla shortlist, con budget giornaliero e cache
   su disco. Un lavoro che itera su Horizons per decidere *quali* oggetti sono
   interessanti è sbagliato per costruzione, non lento: va riscritto sul
   catalogo locale. Ogni chiamata lascia una riga in `external_call` — è così
   che ci si accorge di stare esagerando prima che se ne accorgano loro.

3. **L'hardware non si cancella mai.** Un sito che chiude, una camera che si
   rompe, un setup che cambia binning: `active: false` e `valid_to` nello YAML.
   Cancellare la voce falsifica la storia — `observation_log` punta lì, e fra
   tre anni «con quale campo era stata presa quell'immagine» deve avere una
   risposta. Il reconcile disattiva, non elimina.

4. **Il visibility engine non sa che cosa sia un asteroide.** Riceve array di
   RA/Dec/Δ/V da un *positioner* e lavora su quelli. Se in `visibility/`
   compare la parola `orbit`, `tisserand` o `astorb`, la stratificazione è
   rotta: quel calcolo appartiene a `orbits/`. È l'unica ragione per cui gli
   oggetti deep sky, un domani, costeranno un ingestore e un positioner invece
   di una riscrittura.

5. **Nessun numero senza la sua scomposizione.** `eff_vlim` si salva insieme a
   `pen_airmass`, `pen_moon`, `pen_twilight`, `pen_trailing`; lo `score`
   insieme a `score_json`. Un ranking che non si sa spiegare non si tara, e la
   taratura *è* il progetto: i pesi stanno in `scoring_profile`, non nel
   codice. Corollario: **`GEOMETRICALLY OBSERVABLE` e `ACTUALLY USEFUL` non si
   fondono mai in un unico flag.** Sapere che un oggetto era alto 60° ma
   irrimediabilmente sotto il limite per colpa della Luna è informazione, non
   rumore.

## Stratificazione (non invertire le dipendenze)

Lo schema è quello di stock42: `core/` è il dominio, `services/` orchestra,
`gui/` disegna, `main.py` avvia. Le voci con ⏳ sono progettate e non ancora
scritte: stanno qui perché il loro posto è già deciso.

```
main.py                 avvia NiceGUI. Prima di importare numpy mette
                        OMP_NUM_THREADS=1: su macOS Accelerate si prende tutti i
                        core da sola, e il Mac mini fa girare altro
cli.py                  gli stessi lavori senza interfaccia. Nessuna logica
core/
├── config.py           l'unico modulo che sa dove stanno i file e quanto può
│                       consumare la macchina
├── timeutil.py         l'unico posto in cui si converte fra UTC, JD e date dei
│                       cataloghi. Nel resto del codice esistono solo JD e UTC
├── db.py               connessioni, PRAGMA, migrazioni, registro dei job. Lo
│                       schema **è** docs/schema.sql: non c'è una seconda copia
├── applog.py           log su file, o un errore all'avvio sparisce
├── ingest/http.py      l'unico modulo che fa GET verso l'esterno: ETag,
│                       scrittura atomica, tracciamento in external_call.
│                       Nessun ingestore apre una connessione da sé
├── ingest/mpcorb.py    la fonte. JSON in streaming con `raw_decode`, non un
│                       parser scritto a mano e non il file a colonne fisse
├── ingest/astorb.py    lo strato dell'incertezza. Le colonne stanno in una
│                       tabella dichiarativa: è un formato FORTRAN del 1996 e
│                       l'unico modo di accorgersi che cambia è avere un solo
│                       posto da guardare
├── ingest/cometels.py  le comete. q e Tp, mai a e M
├── ingest/{neocp,pccp,mpec}.py     ⏳ M2
├── orbits/elements.py  derivati e **Tisserand**. L'unico posto dove Tj si calcola
├── orbits/kepler.py    ⏳ M1 il solutore vettoriale: array di elementi × array di
│                       epoche, nessun ciclo Python sugli oggetti
├── orbits/photometry.py ⏳ M1 H-G per gli asteroidi, m1/k1 per le comete. Le due
│                       non si mescolano: una cometa con H asteroidale è un bug
├── orbits/positioner.py ⏳ M1 il contratto verso il resto del mondo:
│                       `positions(target, jd) -> RA, Dec, Δ, r, V, motion`.
│                       Chi sta a valle non sa quale implementazione è in uso
├── visibility/         ⏳ M1 night, geometry, sky, limits, trailing, windows
├── ranking/            ⏳ M1 feature 0-1 e pesi da `scoring_profile`
├── radar/              ⏳ M1 macchina a stati, returning, comete, candidati
├── sites/reconcile.py  ⏳ M1 da config/sites/*.yml a observatory/telescope/
│                       camera/setup, con scala e campo derivati dalla focale
└── external/           ⏳ M2 confine verso JPL, con budget e cache
services/
├── jobs.py             registro dei job, blocchi, cortesia verso la macchina
├── ingest_service.py   scarica → analizza → scrive. Le uniche INSERT dei cataloghi
├── catalog_service.py  letture per l'interfaccia. Nessuna scrittura
├── backup_service.py   copia le sole tabelle non rigenerabili. Il catalogo no:
│                       quello si riscarica in 100 secondi
├── maintenance_service.py  pota i registri, riallinea le statistiche
└── scheduler.py        APScheduler dentro questo processo. Non si avvia se
                        SKY42_TESTING è impostata, o una suite di test
                        accoderebbe download veri
gui/
├── layout.py           registro delle funzioni, intestazione, formati
└── pages/*.py          una rotta per funzione, registrate con @ui.page
```

- `core/visibility/` non importa `core/orbits/elements` né `core/ingest/`.
  `core/ranking/` non importa `core/ingest/`. Nessun modulo di `core/` importa
  da `services/` o `gui/`, e `gui/` non tocca mai SQLite: passa dai servizi.
- **Ogni pagina avrà un endpoint JSON gemello.** Oggi le pagine sono tabelle;
  il giorno delle curve di visibilità la sorgente dati deve già esserci, o
  ogni grafico diventa una riscrittura della pagina che lo contiene. Per questo
  `catalog_service` restituisce dict e liste, mai righe di sqlite3 e mai HTML.
- Il costo di calcolo scala con il **numero di siti**, non con il numero di
  setup: alt/az e Luna si calcolano una volta per osservatorio e ogni setup ci
  applica sopra i propri limiti, che è aritmetica. Un lavoro scritto in modo da
  ricalcolare la geometria per ogni setup va riscritto.
- Il lavoro numerico pesante gira in un `ProcessPoolExecutor`, mai nel loop
  async: l'interfaccia deve restare viva mentre il Mac mini macina.

## Job di fondo

Uno scheduler solo (APScheduler nel processo dell'app), `max_instances=1` per
job, ogni job idempotente e con una riga in `job_run`.

| job | cadenza | fa |
|---|---|---|
| `mpcorb_sync` | ogni 6 h, :05 | scarica se l'ETag è cambiato, importa, `ANALYZE` |
| `astorb_sync` | ogni 6 h, :20 | lo strato dell'incertezza CEU/PEU |
| `cometels_sync` | ogni 6 h, :35 | elementi cometari MPC |
| `backup` | 03:00 UTC | le sei tabelle non rigenerabili |
| `housekeeping` | domenica 04:00 UTC | pota i registri, riallinea le statistiche |
| `neocp_poll` | ⏳ M2, 10 min | lista NEOCP → candidati e snapshot |
| `pccp_poll` | ⏳ M2, 20 min | lista PCCP |
| `mpec_poll` | ⏳ M2, 30 min | circolari recenti, e il **destino** dei candidati |
| `screening` | ⏳ M1, 1/giorno | propagazione 24 mesi avanti + 15 anni indietro |
| `radar_states` | ⏳ M1, dopo screening | stati, transizioni, `target_stats` |
| `night_plan` | ⏳ M1, 1/giorno per sito | crepuscoli e Luna |
| `windows` | ⏳ M1, dopo `night_plan` | finestre e score per (target × setup) |
| `horizons_verify` | ⏳ M2 | solo shortlist, con budget |

**Le cadenze a ore fisse si evitano.** Le sorgenti pubblicano a orari che si
spostano — Lowell slitta di ore nella data di Luna piena — e inseguirli
fallisce in silenzio: si resta indietro di un giorno senza nessun errore. Con
il download condizionato all'ETag un controllo a vuoto costa poche centinaia di
byte, quindi si controlla spesso. Al riavvio si guarda **l'età dei dati**, non
l'orario mancato.

Un job non chiama mai un altro job: pubblica il suo risultato nel database e il
successivo lo trova. Così ognuno si può rilanciare a mano senza effetti a
cascata.

## Come si lavora

- **Le date non si confrontano come stringhe in SQL.** I nostri timestamp sono
  `2026-08-15T07:46:00Z`, `datetime('now')` produce `2026-08-15 10:46:52`, e
  come testo `'T'` viene dopo lo spazio: nessuna riga dello stesso giorno
  risulta mai più vecchia della soglia. Si usa `julianday(...)` da entrambe le
  parti. E **i dati finti dei test si scrivono nel formato che scrive
  l'applicazione**, o il test verifica un mondo che non esiste (è successo).
- **Il progetto sta in `~/GitHub/sky42`, mai dentro `~/Documents`, `~/Desktop`
  o `~/Downloads`.** Quelle tre sono protette da TCC e un LaunchAgent non ha
  modo di chiedere il consenso: il backup muore con `Operation not permitted`
  mentre lo stesso comando dal Terminale funziona (diagnosi già pagata su
  brain42, 2026-08-04).
- Il servizio gira in Docker sul Mac mini. Il venv di progetto (`.venv`,
  Python 3.13) è per sviluppo e test.
- Se `.venv` non c'è: `python3.13 -m venv .venv && .venv/bin/pip install -r
  requirements.txt`. **`python3.13`, non `python3`** — su macOS quello di
  sistema è il 3.9.
- Test: `.venv/bin/python -m pytest`. Ogni test gira su una `data_dir`
  temporanea, mai su quella vera.
- Lingua: identificatori di codice in inglese, commenti e interfaccia in
  italiano.
- Percorsi: `pathlib` ovunque, mai percorsi assoluti nel codice — la radice dei
  dati viene solo da `config.py`.
- Angoli in gradi ai confini, radianti solo dentro le funzioni di calcolo.
  Tempi: JD (TDB) nei calcoli, ISO-8601 UTC nelle colonne testuali, ora locale
  **solo** in interfaccia.
- Un modulo di calcolo nuovo nasce con il suo test di verità: un caso con il
  numero atteso preso da Horizons o dalla letteratura, scritto nel test come
  costante con la fonte in commento. Le tolleranze si dichiarano (es. `< 2"`
  in posizione, `< 0.2 mag`), non si aggiustano finché il test passa.

## Il servizio non si aggiorna da solo

Sul Mac mini sky42 gira in un container e l'unico bind mount è `./data`: il
codice sta dentro l'immagine. Quindi, come ultimo passo di ogni lavoro che
tocca `sky42/` o `web/`:

```bash
docker compose up -d --build
```

E poi si verifica che sia davvero cambiato invece di fidarsi dello "Started":

```bash
curl -s localhost:8242/health          # 'ok'/'degraded', età del catalogo, esito dei sync
docker compose ps                      # 'Up ... (healthy)'
```

La riga di comando si esegue **dentro** il container
(`docker compose exec sky42 python cli.py ...`): host e container che scrivono
insieme sullo stesso SQLite attraverso il bind mount è il modo documentato di
corromperlo — in WAL il coordinamento fra scrittori passa da un file di memoria
condivisa che non attraversa il confine della VM.

Due cose che il `restart: unless-stopped` **non** copre, e vanno sapute:
`docker compose kill` e `docker compose stop` contano come arresto voluto e non
fanno ripartire niente; e **Docker non riavvia un container `unhealthy`** — la
sonda riporta, non agisce. Se il processo si pianta invece di morire, il
container resta unhealthy finché qualcuno guarda.

`data/` non viene toccata. Se il lavoro ha cambiato lo schema, la migrazione
gira all'avvio e deve essere idempotente.

## Sincronia della documentazione

- **MEMORANDUM.md a ogni scelta.** Una decisione architetturale, un formato
  dati, una soglia, un default, una dipendenza aggiunta o scartata,
  un'ipotesi smentita da una misura: si aggiunge una voce datata con il
  criterio e **l'alternativa scartata**, nello stesso lavoro che introduce il
  cambiamento. Le domande aperte in fondo si chiudono con numeri, non con
  previsioni. Vale in particolare per le costanti fisiche e le soglie: un
  `0.15` senza il suo perché, dopo tre mesi, è indistinguibile da un capriccio.
- **README.md a ogni funzione** nuova, completata o cambiata di stato:
  tabella delle funzioni ed endpoint.
- **IDEA.md non si aggiorna nei contenuti.** Gli scostamenti si registrano nel
  memorandum, non correggendo l'originale.

## Da dove si riparte

M0 è chiuso: catalogo, pianificatore, backup, container. Il prossimo passo è
**M1**, e l'ordine non è indifferente perché ogni pezzo è il terreno del
successivo:

1. **`core/orbits/kepler.py`** — il solutore vettoriale. Nasce con il suo test
   di verità: la posizione di un asteroide noto confrontata con Horizons, con
   la tolleranza dichiarata nel test e non aggiustata finché passa. È il pezzo
   su cui poggia tutto il resto, ed è anche quello dove un errore si nota meno.
2. **`core/sites/reconcile.py`** — da `config/sites/*.yml` a
   observatory/telescope/camera/setup. Piccolo, indipendente dal punto 1, e
   sblocca la pagina Osservatori.
3. **`core/orbits/positioner.py`** — il contratto `positions(target, jd)`.
   Serve *prima* del visibility engine, o il visibility engine nascerà
   assumendo che ogni target abbia un'anomalia media (regola 4).
4. **`core/visibility/`** — notte e Luna per sito, poi brillanza del cielo,
   `eff_vlim`, finestre.
5. **`core/radar/`** e il ranking, che sono i due che rendono la dashboard una
   console di decisione invece di una tabella.

Due cose da tenere d'occhio mentre si costruisce M1: il database sta già a
1 GB e `screening_track` lo farà crescere (voce nel memorandum), e il polling
NEOCP di M2 **conviene anticiparlo** se M1 si allunga — quella storia non si
recupera a posteriori.
