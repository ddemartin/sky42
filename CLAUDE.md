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
├── ingest/neocp.py     ✅ NEOCP e PCCP. Il **testo**, non il JSON: i due
│                       prodotti dell'MPC non concordano, e PCCP ha solo quello
├── ingest/mpec.py      ⏳ M2, il destino dei candidati
├── orbits/elements.py  derivati e **Tisserand**. L'unico posto dove Tj si calcola
├── orbits/kepler.py    ✅ il solutore vettoriale: array di elementi × array di
│                       epoche, nessun ciclo Python sugli oggetti
├── orbits/photometry.py ✅ H-G per gli asteroidi, m1/k1 per le comete. Le due
│                       non si mescolano: una cometa con H asteroidale è un bug
├── orbits/positioner.py ✅ il contratto verso il resto del mondo:
│                       `positions(target, jd) -> RA, Dec, Δ, r, V, motion`.
│                       Chi sta a valle non sa quale implementazione è in uso
├── visibility/         ✅ night, geometry, sky, limits, trailing, windows
├── ranking/            ✅ feature 0-1 in due gruppi (interesse, fattibilità),
│                       pesi da `scoring_profile`. Una feature che non si può
│                       calcolare è None e sparisce dalla media, non vale zero
├── radar/population.py ✅ chi si monitora, da regole dichiarative in `setting`.
│                       Vocabolario chiuso: mai SQL nella configurazione
├── radar/screening.py  ✅ le due griglie, i BLOB, la distillazione. Non tocca
│                       il database: riceve `Body` e restituisce array
├── radar/states.py     ✅ la macchina a stati. Legge quel che lo screening ha
│                       distillato e non ricalcola **nessuna** posizione
├── sites/reconcile.py  ✅ da config/sites/*.yml a observatory/telescope/
│                       camera/setup, con scala e campo derivati dalla focale
└── external/           ⏳ M2 confine verso JPL, con budget e cache
services/
├── jobs.py             registro dei job, blocchi, cortesia verso la macchina
├── ingest_service.py   scarica → analizza → scrive. Le uniche INSERT dei cataloghi
├── catalog_service.py  letture per l'interfaccia. Nessuna scrittura
├── backup_service.py   copia le sole tabelle non rigenerabili. Il catalogo no:
│                       quello si riscarica in 100 secondi
├── screening_service.py    la popolazione monitorata, i blocchi, le INSERT
│                       di `screening_track` e `target_stats`
├── candidate_service.py    il polling NEOCP/PCCP. **L'unico lavoro che perde
│                       dati se non gira**: l'MPC riscrive le liste
├── radar_service.py    V_ref per setup, stati, transizioni. Nessun calcolo
│                       di posizioni: se ne compare uno, sta nel posto sbagliato
├── ranking_service.py  il profilo attivo dal database e il contesto dell'oggetto
├── window_service.py   le finestre: un oggetto per la pagina, la popolazione
│                       monitorata per il job. **Lo stesso calcolo**, e la
│                       geometria una volta per sito — mai per setup
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
| `neocp_poll` | 10 min | lista NEOCP → candidati e snapshot |
| `pccp_poll` | 20 min | lista PCCP |
| `mpec_poll` | ⏳ M2, 30 min | circolari recenti, e il **destino** dei candidati |
| `screening` | 02:10 UTC | propagazione 24 mesi avanti + 15 anni indietro, `target_stats` |
| `radar_states` | 02:40 UTC | stati e transizioni per (target × setup), con isteresi |
| `night_plan` | ogni 6 h, :50 | crepuscoli e Luna, due settimane avanti per sito |
| `windows` | 02:20 UTC | finestre e score per (target × setup × notte), tre notti |
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
- **`conftest.py` protegge i test, non la riga di comando.** Punta
  `SKY42_DATA_DIR` a una cartella temporanea *solo sotto pytest*: qualunque
  script ad hoc lanciato dalla radice del progetto — anche solo per capire
  perché un test non passa — parla con `data/sky42.db`, quello vero. Il
  2026-08-17 è costato la cancellazione del database di produzione. Per provare
  qualcosa a mano si esporta `SKY42_DATA_DIR` a una cartella usa e getta, o si
  scrive un test.
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

**E dal 17 agosto è anche l'unica cosa possibile: il database del servizio sta
in un volume Docker** (`SKY42_DB_PATH=/var/lib/sky42/sky42.db`), non su `data/`.
Il bind mount di macOS passa da virtiofs e la WAL di SQLite non ci regge — il
COMMIT di un import moriva con `locking protocol` a servizio acceso e con
**SIGBUS** a servizio fermo, sempre su `core/db.py:79`. Su `data/` restano i
cataloghi scaricati, le effemeridi, i log e i backup: l'unico ponte fra il
volume e il mondo, e per questo il backup notturno conta più di prima.

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

M0 è chiuso. Di **M1** è fatta tutta la catena di calcolo, dal catalogo al
punteggio, ognuno dei pezzi con il suo test di verità contro Horizons dove una
verità esiste:

```
core/orbits/kepler.py       ✅ due rami (Newton su E, variabili universali)
core/sites/reconcile.py     ✅ YAML → hardware, idempotente, non cancella
core/ephemeris.py           ✅ DE440s, l'unico che apre il kernel
core/orbits/photometry.py   ✅ H-G e cometaria, che non si mescolano
core/orbits/positioner.py   ✅ positions(body, jd), astrometrico geocentrico
core/visibility/night.py    ✅ crepuscoli e Luna per sito
core/visibility/geometry.py ✅ alt/az, airmass, separazioni
core/visibility/sky.py      ✅ Krisciunas & Schaefer, somma in flusso
core/visibility/limits.py   ✅ eff_vlim con le quattro penalità che sommano,
                               e reference_limit: V_ref a X=1.5, il metro del radar
core/visibility/windows.py  ✅ finestra geometrica e finestra utile, separate;
                               sky_geometry per sito, observation_windows per
                               setup — un oggetto è il caso N = 1, non un ramo
core/radar/screening.py     ✅ due griglie (24 mesi avanti, 15 anni indietro),
                               tracce in BLOB float32, distillazione vettoriale
core/radar/states.py        ✅ sei stati, isteresi 0.15 mag, conferma su due giri
core/ranking/               ✅ dieci feature 0-1 in due gruppi, pesi dal profilo
```

Sul catalogo vero: **14.899 oggetti monitorati, screening in 18 s, radar in 1 s**.

Di **M2** è stato anticipato il pezzo che non si recupera a posteriori: il
polling **NEOCP e PCCP** (`core/ingest/neocp.py`, `services/candidate_service.py`,
pagina `/candidati`). Manca il watcher MPEC, cioè il *destino* dei candidati.

E la popolazione monitorata non è più cablata: `core/radar/population.py`
compila regole dichiarative da `setting.screening_selectors`. Tj < 3 è oggi la
regola principale, non l'unica possibile — e aggiungerne una è una impostazione.

E il job `windows` scrive `observation_window` in massa dalla sera del 17
agosto: 14.730 finestre in 5,7 s, ed è quello che ha acceso il criterio sulla
durata nel radar. Da lì in poi lo stato di un oggetto dice «alla portata
**stanotte, da un sito che ho**», non più solo «abbastanza brillante» — con la
stagionalità che ne segue (memorandum del 17 agosto sera).

Quel che resta di M1, nell'ordine:

1. **La dashboard Tonight / Coming into range / Tj < 3**, che adesso è una
   query su `observation_window` e non un calcolo.
2. **`BEST SITE TONIGHT`**, che è la stessa query ordinata per sito — e che
   vale quanto valgono i `vlim_ref` dichiarati (domanda aperta 5).

Due cose da tenere d'occhio: `screening_track` ha portato il database da 1,17 a
1,43 GB e cresce linearmente con la popolazione monitorata (voce nel
memorandum); e il polling NEOCP di M2 **conviene anticiparlo** — quella storia
non si recupera a posteriori.
