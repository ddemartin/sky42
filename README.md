# sky42

Console personale di follow-up del Sistema Solare. Gira 24/7 su un Mac mini,
tiene aggiornato un catalogo orbitale locale, usa i tempi morti per precalcolare
chi sta tornando alla portata dei telescopi, e risponde a una domanda sola:
**cosa osservo stanotte, da quale sito e in quale finestra.**

Il grosso dei conti si fa in casa. JPL Horizons si chiama alla fine, su una
manciata di oggetti, per confermare — mai per cercare.

Progetto e ragionamento iniziale: [IDEA.md](IDEA.md). Perché ogni cosa è com'è:
[MEMORANDUM.md](MEMORANDUM.md). Come si lavora: [CLAUDE.md](CLAUDE.md).
Formule: [docs/modelli.md](docs/modelli.md). Schema: [docs/schema.sql](docs/schema.sql).

> **Stato al 17 agosto 2026 (sera): M0 fatto, M1 chiuso.** Dal catalogo alla
> riga sullo schermo il giro è completo — catalogo → Keplero → positioner →
> sito → notte → cielo → limite → finestra → punteggio → dashboard — e gira
> **su tutti gli oggetti insieme**: lo screening propaga la popolazione
> monitorata 24 mesi avanti e 15 anni indietro in 18 s, il job delle finestre
> scrive 14.730 righe in 5,7 s, il radar ne ricava gli stati e `/stanotte` è
> una query.
>
> ```
> 1.557.419 oggetti     1.556.465 asteroidi + 954 comete
> 1.556.169 con CEU     lo strato ASTORB agganciato all'MPC
>    14.899 monitorati  ACO con Tj < 3, comete, watchlist
>     4.910 con finestre entro 1,5 mag dal limite del setup migliore
>       647 utili stanotte  finestra utile non nulla, di cui 10 PRIME e 84 GOOD
> ```
>
> Ciò che sa dire, dal container — ed è la domanda del progetto:
>
> ```
> C/2019 E3 (ATLAS)   V 18.3, limite 21.2, margine 2.8 mag
>   utile 7.6 h dalle 02:28 alle 10:03 UTC · alt 76° · Luna a 122°
>   468 s × 1 posa · PRIME (0.881) · BEST SITE: cile-rio-hurtado
>
> 2020 TY99   Tj 2.94, V 21.1 e in miglioramento
>   nessuna buona apparizione nei 15 anni guardati  →  OBSERVABLE
> ```

---

## Come funziona

```
ASTORB / MPC
    ↓  ingest, una volta al giorno, condizionato all'ETag
database locale (SQLite)
    ↓  Tisserand, classi, incertezza — al momento dell'import
screening: propagazione a due corpi, 24 mesi avanti e 15 indietro
    ↓  chi entra sotto il limite, chi torna dopo anni, chi è al picco
radar: stati e transizioni per (oggetto × setup)
    ↓
visibility engine: notte, Luna, brillanza del cielo, finestre
    ↓  magnitudine limite efficace, trailing, esposizioni
ranking trasparente a pesi
    ↓
dashboard  →  shortlist  →  Horizons, solo per verifica
```

La differenza fra `GEOMETRICALLY OBSERVABLE` e `ACTUALLY USEFUL` è il punto di
tutto il sistema: un oggetto alto 70° e sotto una Luna piena a 15° non è
osservabile, e il numero che lo dice è la **magnitudine limite efficace**,
salvata sempre con la sua scomposizione (airmass, Luna, crepuscolo, trailing).

## Stato delle funzioni

| funzione | stato | note |
|---|---|---|
| schema del database | ✅ | [docs/schema.sql](docs/schema.sql), commentato |
| modelli e formule | ✅ | [docs/modelli.md](docs/modelli.md), con le fonti |
| configurazione dei siti in YAML | ✅ | un file per osservatorio, [esempio](config/sites/cile-rio-hurtado.yml): è la fonte di verità, il database la indicizza |
| download condizionato (ETag, scrittura atomica) | ✅ | 280 MB non si riscaricano per scoprire che non sono cambiati |
| import MPCORB extended | ✅ | la fonte: 1.556.465 oggetti in 84 s, JSON in streaming |
| import ASTORB | ✅ | lo strato CEU: 1.556.169 agganciati in 15 s, 808 fuori catalogo MPC |
| import CometEls | ✅ | 954 comete, con le iperboliche trattate come tali |
| Tisserand e derivati orbitali | ✅ | calcolati all'import, indicizzati |
| pagina Catalogo (quanti, quando, distribuzioni) | ✅ | `/catalogo`, con aggiornamento in un processo separato |
| riga di comando (`ingest`, `stato`, `siti`, `effemeride`, `screening`, `radar`, `finestre`, `candidati`) | ✅ | gli stessi moduli dell'interfaccia |
| pianificatore dei lavori automatici | ✅ | `/pianificatore`: cadenze, prossimo giro, esito, esegui-ora |
| popolazione monitorata configurabile | ✅ | regole dichiarative in `setting.screening_selectors`: Tj, H, q, classe, CEU, watchlist, liste a mano. Aggiungerne una non è una modifica al codice |
| pagina Candidati | ✅ | `/candidati`: chi è in lista, chi sta per essere perso, chi è sparito |
| recupero dopo un riavvio | ✅ | all'avvio guarda l'età dei dati, non l'orario mancato |
| aggiornamento automatico dei cataloghi | ✅ | risolto il 17 ago spostando il database in un **volume Docker**: la WAL di SQLite non regge virtiofs. 1.557.104 oggetti importati dentro il container, a servizio acceso, in 140 s |
| backup delle tabelle non rigenerabili | ✅ | kilobyte, non il gigabyte di catalogo che si riscarica |
| manutenzione settimanale | ✅ | pota i registri, riallinea le statistiche degli indici |
| reconcile dei siti (sito/telescopio/camera/setup) | ✅ | dagli YAML al database, idempotente; scala e campo derivati dalla focale, mai scritti a mano |
| pagina Osservatori | ✅ | `/osservatori`: hardware, derivati ottici e limiti, con riallineamento dai file |
| solutore di Keplero vettoriale | ✅ | `core/orbits/kepler.py`: 14.000 orbite × 730 giorni in 2,4 s; verità contro Horizons su quattro coniche |
| fotometria H-G e cometaria | ✅ | `core/orbits/photometry.py`: V di Cerere e Faetonte a 0.00 mag da Horizons |
| positioner: RA/Dec/Δ/r/V/moto | ✅ | `core/orbits/positioner.py`: astrometrico geocentrico, tempo luce, residuo 0.008″ |
| effemeridi planetarie DE440s | ✅ | 32 MB scaricati una volta in `data/ephem/`, Skyfield li legge |
| pagina Oggetto (effemeride, radar e finestre) | ✅ | `/oggetto`: scheda, stato del radar, finestra dei 24 mesi, «stanotte da quale setup» e punteggio scomposto. Nessuna chiamata a JPL |
| screening 24 mesi + back-propagation 15 anni | ✅ | `core/radar/screening.py`: 14.899 oggetti in **18 s**, tracce in BLOB (261 MB), statistiche in `target_stats` |
| notte, Sole, Luna, crepuscoli | ✅ | `core/visibility/night.py`: crepuscoli a 0.5 s da Horizons, poli compresi |
| piano delle notti (job `night_plan`) | ✅ | due settimane avanti per ogni sito attivo, ogni 6 h e all'avvio |
| alt/az, airmass, separazione dalla Luna | ✅ | `core/visibility/geometry.py`: 1.7 M punti in 0.18 s, 11″ da Horizons |
| brillanza del cielo con Luna | ✅ | `core/visibility/sky.py`: K&S 1991, contributi sommati in flusso, scomposti in uscita |
| magnitudine limite efficace scomposta | ✅ | `core/visibility/limits.py`: quattro penalità che sommano esatte al totale |
| ricerca della finestra migliore | ✅ | `core/visibility/windows.py`: geometrica e utile separate, campionamento a 5 min |
| finestre in massa (job `windows`) | ✅ | 4.910 oggetti × 3 notti = **14.730 finestre in 5,7 s**: la geometria una volta per sito, i limiti per setup. È lo stesso calcolo della pagina Oggetto, con N ≠ 1 |
| returning-object radar (stati e transizioni) | ✅ | `core/radar/states.py`: isteresi 0.15 mag e conferma su due giri, 15.000 oggetti × 2 riferimenti in 1 s. Dal 17 ago giudica anche sulla **durata** della finestra, non solo sulla magnitudine |
| confronto automatico dei siti | ✅ | `BEST SITE TONIGHT` in `/stanotte`, e il confronto per oggetto dentro la riga — compresi i setup da cui **non** si vede. `BEST SITE NOW` resta di M2 |
| ranking a pesi trasparenti | ✅ | `core/ranking/`: dieci feature 0-1 in due gruppi, pesi da `scoring_profile`, `score_json` sempre accanto allo score |
| dashboard: Tonight / Coming into range / Tj < 3 | ✅ | `/stanotte`: tre sezioni per tre orizzonti (stanotte, le settimane, gli anni). È una query, non un calcolo, e ha il suo gemello JSON in `/api/stanotte` |
| propositi osservativi e sessioni | ✅ | `/programma`: dal suggerimento alla decisione, e il registro di cosa si è ripreso. Un proposito scade da solo quando l'occasione passa, **con il motivo**: sceso sotto il limite, o niente finestra da quel sito |
| trailing ed esposizione consigliata | ✅ | `n × t`, con la posa massima dettata da traccia e pixel |
| incertezza posizionale vs campo, mosaico | ✅ | 3σ di CEU contro il lato corto del campo; CEU propagata a oggi in `target_stats.ceu_now_arcsec` |
| watcher NEOCP | ✅ | `neocp_poll` ogni 10 min: candidati, evoluzione, sparizioni. La storia che l'MPC non conserva |
| watcher PCCP | ✅ | `pccp_poll` ogni 20 min, stesso formato e stessa storia |
| destino dei candidati | ✅ | `destiny_poll` ogni 30 min: da candidato a NEO confermato con la sua circolare, pianetino designato, perso o inesistente. La fonte non è il testo delle MPEC ma la tabella dei trksub usciti di lista, che l'MPC pubblica già risolta |
| comete: elementi MPC e radar dedicato | ⏳ M2 | ordinate per geometria, non per magnitudine |
| verifica con Horizons sulla shortlist | ⏳ M2 | con budget giornaliero e cache; ogni chiamata a log |
| validazione due corpi contro Horizons | ⏳ M2 | 50 oggetti/mese a 1, 6, 12, 24 mesi (domanda aperta 2) |
| calibrazione di `vlim_ref` dalle misure | ⏳ M2 | i fatti battono il file di configurazione |
| notifiche | ⏳ M3 | prima serve sapere quante transizioni al giorno genera il radar |
| oggetti deep sky | — un domani | lo schema e il positioner sono già pronti a riceverli |
| pipeline di immagini (PSF, ricerca di coma) | — fuori | progetto separato: da sky42 riceverebbe solo la lista di target |

## Milestone

**M0 — il catalogo esiste.** ✅ *fatto il 15 agosto 2026.* Le tre sorgenti si
scaricano e si importano, il Tisserand è calcolato e indicizzato, la pagina
Catalogo mostra quanti e da quando. `SELECT count(*) FROM orbit WHERE
tisserand_j < 3` risponde: 34.048, che diventano 14.685 togliendo comete e
famiglie risonanti.

**M1 — l'MVP di IDEA.md.** Screening, notte, Luna, finestre, radar, ranking,
dashboard a tre sezioni. Criterio di uscita: la domanda «cosa entra sotto V 21
nei prossimi dodici mesi, e da dove si vede meglio» ha una risposta sullo
schermo senza aver chiamato JPL nemmeno una volta.

*La catena di calcolo è chiusa, il 17 agosto 2026.* Solutore di Keplero,
reconcile dei siti, positioner con fotometria, notte e Luna per sito, geometria
e airmass, brillanza del cielo, magnitudine limite scomposta, finestre
osservative — ognuno con il suo test di verità contro Horizons dove una verità
esiste — e adesso anche **screening** (14.899 oggetti propagati su 24 mesi
avanti e 15 anni indietro in 18 s), **radar** (stati e transizioni con isteresi)
e **ranking** (feature 0-1, pesi da `scoring_profile`, scomposizione salvata).

*Il job delle finestre c'è, dalla sera del 17 agosto 2026:* `observation_window`
si riempie ogni notte per (target × setup × notte), ed è quello che ha acceso il
criterio sulla durata nel radar — fino a ieri inerte. Manca la **dashboard a tre
sezioni**, che a questo punto è una query e non un calcolo.

*E la dashboard c'è, dalla sera del 17 agosto 2026:* `/stanotte` con le tre
sezioni e `BEST SITE TONIGHT`. **M1 è chiuso**: la domanda «cosa entra sotto
V 21, e da dove si vede meglio» ha una risposta sullo schermo senza aver
chiamato JPL nemmeno una volta.

**M2 — i radar MPC e le comete.** Più la validazione contro Horizons e la
calibrazione dei limiti, che è ciò che rende affidabile M1.

**M3 — le notifiche**, quando si saprà quanto rumore fa il radar.

## Avvio

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python main.py            # interfaccia su http://127.0.0.1:8242
```

`python3.13`, non `python3`: su macOS quello di sistema è il 3.9.

Il primo riempimento del catalogo (circa 280 MB da scaricare, 100 s di CPU):

```bash
.venv/bin/python cli.py ingest all     # oppure il pulsante nella pagina Catalogo
.venv/bin/python cli.py stato          # cosa c'è nel database
.venv/bin/python cli.py siti           # riallinea l'hardware dagli YAML e lo mostra
.venv/bin/python cli.py effemeride 3200 --giorni 30
.venv/bin/python cli.py screening --solo-popolazione   # chi verrebbe propagato
.venv/bin/python cli.py screening                      # 15.000 oggetti, ~20 s
.venv/bin/python cli.py radar                          # stati e transizioni
.venv/bin/python cli.py candidati                      # NEOCP e PCCP, e chi è sparito
```

Test: `.venv/bin/python -m pytest` — girano su una cartella dati temporanea,
mai su quella vera.

### Sempre acceso

In esercizio gira in Docker, come brain42 e stock42:

```bash
docker compose up -d --build
curl -s localhost:8242/health          # 'ok', età del catalogo e da quanto non parte un sync
```

`restart: unless-stopped` lo rimette in piedi dopo un riavvio e dopo un crash.

**La riga di comando si esegue dentro il container**, non dall'host:

```bash
docker compose exec sky42 python cli.py ingest all
docker compose exec sky42 python cli.py stato
docker compose exec sky42 python cli.py siti
docker compose exec sky42 python cli.py screening
docker compose exec sky42 python cli.py radar
docker compose exec sky42 python cli.py candidati
```

**Il database del servizio sta in un volume Docker, non su `data/`.** Il bind
mount di macOS passa da virtiofs e la WAL di SQLite non ci regge: il COMMIT di
un import moriva con `locking protocol` a servizio acceso e con SIGBUS a
servizio fermo (memorandum del 17 agosto). Dentro un volume il filesystem è
ext4 nella VM, e l'import di 1.557.104 oggetti passa in 140 s con il servizio
acceso.

Su `data/` resta ciò che ha senso vedere e copiare: i cataloghi scaricati, le
effemeridi, i log e i **backup** delle sette tabelle non rigenerabili — che sono
l'unico ponte fra il volume e il mondo, e per questo contano più di prima.

Ne segue che dall'host il database del servizio non è raggiungibile, ed è un
bene: la regola «`cli.py` si esegue dentro il container» non è più una
disciplina da ricordare, è l'unica cosa possibile.

Per ricostruire tutto da zero — è progettato per costare poco:

```bash
docker compose exec sky42 python cli.py ingest all    # ~100 s
docker compose exec sky42 python cli.py screening     # ~20 s
docker compose exec sky42 python cli.py radar
```

Host e container che scrivono insieme sullo stesso file SQLite attraverso il
bind mount è il modo documentato di corrompere un database: in WAL il
coordinamento fra scrittori passa da un file di memoria condivisa che non
attraversa il confine della VM. Dall'host si usa `cli.py` solo a servizio
fermo.

Per raggiungerlo da un'altra macchina si mette in `.env` l'indirizzo Tailscale
**di questa** macchina:

```
SKY42_BIND_IP=100.x.y.z
```

Non `0.0.0.0`, che lo esporrebbe anche alla rete locale: sky42 non ha
autenticazione. Dentro la tailnet va bene; il giorno di `tailscale funnel`
l'autenticazione arriva prima. In alternativa a Docker c'è un LaunchAgent
pronto in [scripts/](scripts/com.ddemartin.sky42.plist).

## Cosa gira da solo

| lavoro | cadenza | fa |
|---|---|---|
| `mpcorb_sync` | ogni 6 h | scarica se l'ETag è cambiato, importa, `ANALYZE` |
| `astorb_sync` | ogni 6 h | lo strato dell'incertezza |
| `cometels_sync` | ogni 6 h | le comete |
| `backup` | ogni giorno 03:00 UTC | le sette tabelle non rigenerabili |
| `night_plan` | ogni 6 h | crepuscoli e Luna, due settimane avanti per sito |
| `screening` | ogni giorno 02:10 UTC | propaga la popolazione monitorata, scrive tracce e `target_stats` |
| `windows` | ogni giorno 02:20 UTC | finestre e punteggio per (target × setup × notte), tre notti avanti |
| `radar_states` | ogni giorno 02:40 UTC | stati e transizioni per (target × setup) |
| `intents_refresh` | ogni giorno 02:50 UTC | chiude i propositi la cui occasione è passata, con il motivo |
| `neocp_poll` | ogni 10 min | candidati NEOCP: nuovi, evoluzione, sparizioni |
| `pccp_poll` | ogni 20 min | candidati cometari PCCP |
| `destiny_poll` | ogni 30 min | che fine ha fatto ogni candidato uscito dalla NEOCP |
| `housekeeping` | domenica 04:00 UTC | pota i registri, riallinea le statistiche |

Ogni 6 ore e non a un orario fisso perché le sorgenti pubblicano a orari che si
spostano (Lowell slitta di ore nella data di Luna piena) e con l'ETag un
controllo a vuoto costa poche centinaia di byte. Al riavvio si guarda l'età dei
dati, non l'orario mancato.

Stato, esito e pulsante "esegui ora" in `/pianificatore`.

## Il Mac mini fa girare altro

sky42 è un ospite, e sono cinque misure concrete, non una buona intenzione:
`OMP_NUM_THREADS=1` prima di importare numpy (su macOS Accelerate si prende
tutti i core da sola), al massimo 2 processi di calcolo, `nice 10`, lavoro a
blocchi di 20.000 con controllo del carico fra un blocco e l'altro, e download
condizionati. Le soglie stanno in [core/config.py](core/config.py) e si
cambiano da variabile d'ambiente.

## Configurare un osservatorio

Un file in `config/sites/`, versionato in git. Il database lo indicizza e si
rifà da solo; scala del pixel e campo si calcolano da focale, pixel e binning,
non si scrivono. Per dismettere qualcosa si mette `valid_to` e `active: false`
— **non si cancella**, o le osservazioni già fatte con quel setup perdono il
loro significato.

Esempio commentato: [config/sites/cile-rio-hurtado.yml](config/sites/cile-rio-hurtado.yml).

## Dati

Tutto sotto `data/`, unico bind mount del container:

```
data/sky42.db          il database
data/catalogs/         astorb.dat.gz e gli altri file scaricati, con il loro hash
data/ephem/            DE440s (~32 MB), scaricato una volta
data/cache/horizons/   le risposte JPL, per non richiederle
```

Il backup deve prendere almeno **`mpc_candidate`, `mpc_candidate_snapshot`,
`state_transition`, `observation_log`, `watchlist`, `setup_calibration`**: il
resto si riscarica e si ricalcola, quelle no. Il perché sta nel
[memorandum](MEMORANDUM.md).
