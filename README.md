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

> **Stato al 16 agosto 2026: M0 fatto, M1 a metà.** La catena di calcolo è
> completa da un capo all'altro — catalogo → Keplero → positioner → sito →
> notte → cielo → limite → finestra — e per un oggetto qualsiasi risponde in
> millisecondi, senza chiamare JPL. Manca il pezzo che la fa girare **su tutti
> gli oggetti insieme**: screening, radar degli stati e ranking. Oggi si
> interroga un oggetto alla volta dalla pagina Oggetto; la dashboard «Stanotte»
> arriva con lo screening, che è ciò che produrrà la lista dei candidati.
>
> ```
> 1.557.419 oggetti     1.556.465 asteroidi + 954 comete
> 1.556.169 con CEU     lo strato ASTORB agganciato all'MPC
>    14.685 ACO         Tj < 3 tolte le famiglie risonanti
> ```
>
> Un esempio di ciò che sa dire, dal container:
>
> ```
> (4) Vesta — RC700 + QHY600 bin2 L (cile-rio-hurtado), notte del 2026-08-16
>   geometrica 01:23-06:03 (4.7 h)   utile 01:23-06:03 (4.7 h)
>   meglio alle 04:58 a 58° (X 1.18); transito 04:53 a 58°
>   V 7.5 contro 21.1 — margine +13.6
>   penalità: airmass 0.10, Luna 0.00, crepuscolo 0.00, moto 0.13
>   cielo 21.7 mag/arcsec², Luna 24% a 166°, consigliate 1 x 438 s
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
| riga di comando (`ingest`, `stato`, `siti`, `effemeride`) | ✅ | gli stessi moduli dell'interfaccia |
| pianificatore dei lavori automatici | ✅ | `/pianificatore`: cadenze, prossimo giro, esito, esegui-ora |
| recupero dopo un riavvio | ✅ | all'avvio guarda l'età dei dati, non l'orario mancato |
| aggiornamento automatico dei cataloghi | ⚠️ | i job partono, ma il COMMIT fallisce con `locking protocol` sul bind mount di macOS (memorandum 16 ago, domanda aperta 9). Nel frattempo: `cli.py ingest` dentro il container |
| backup delle tabelle non rigenerabili | ✅ | kilobyte, non il gigabyte di catalogo che si riscarica |
| manutenzione settimanale | ✅ | pota i registri, riallinea le statistiche degli indici |
| reconcile dei siti (sito/telescopio/camera/setup) | ✅ | dagli YAML al database, idempotente; scala e campo derivati dalla focale, mai scritti a mano |
| pagina Osservatori | ✅ | `/osservatori`: hardware, derivati ottici e limiti, con riallineamento dai file |
| solutore di Keplero vettoriale | ✅ | `core/orbits/kepler.py`: 14.000 orbite × 730 giorni in 2,4 s; verità contro Horizons su quattro coniche |
| fotometria H-G e cometaria | ✅ | `core/orbits/photometry.py`: V di Cerere e Faetonte a 0.00 mag da Horizons |
| positioner: RA/Dec/Δ/r/V/moto | ✅ | `core/orbits/positioner.py`: astrometrico geocentrico, tempo luce, residuo 0.008″ |
| effemeridi planetarie DE440s | ✅ | 32 MB scaricati una volta in `data/ephem/`, Skyfield li legge |
| pagina Oggetto (effemeride e finestre) | ✅ | `/oggetto`: scheda, effemeride, e «stanotte da quale setup». Nessuna chiamata a JPL |
| screening 24 mesi + back-propagation 15 anni | ⏳ M1 | tracce in BLOB, statistiche in `target_stats` |
| notte, Sole, Luna, crepuscoli | ✅ | `core/visibility/night.py`: crepuscoli a 0.5 s da Horizons, poli compresi |
| piano delle notti (job `night_plan`) | ✅ | due settimane avanti per ogni sito attivo, ogni 6 h e all'avvio |
| alt/az, airmass, separazione dalla Luna | ✅ | `core/visibility/geometry.py`: 1.7 M punti in 0.18 s, 11″ da Horizons |
| brillanza del cielo con Luna | ✅ | `core/visibility/sky.py`: K&S 1991, contributi sommati in flusso, scomposti in uscita |
| magnitudine limite efficace scomposta | ✅ | `core/visibility/limits.py`: quattro penalità che sommano esatte al totale |
| ricerca della finestra migliore | ✅ | `core/visibility/windows.py`: geometrica e utile separate, campionamento a 5 min |
| returning-object radar (stati e transizioni) | ⏳ M1 | isteresi 0.15 mag, conferma su due giri |
| confronto automatico dei siti | ⏳ M1 | `BEST SITE TONIGHT` e `BEST SITE NOW` |
| ranking a pesi trasparenti | ⏳ M1 | pesi in `scoring_profile`, breakdown salvato |
| dashboard: Tonight / Coming into range / Tj < 3 | ⏳ M1 | NiceGUI, come stock42: nessuna catena di build |
| trailing ed esposizione consigliata | ✅ | `n × t`, con la posa massima dettata da traccia e pixel |
| incertezza posizionale vs campo, mosaico | ✅ | 3σ di CEU contro il lato corto del campo (propagazione a oggi: ⏳) |
| watcher NEOCP | ⏳ M2 | **da anticipare se M1 si allunga**: la storia persa non si recupera |
| watcher PCCP | ⏳ M2 | |
| watcher MPEC e destino dei candidati | ⏳ M2 | da candidato a oggetto confermato, o a niente |
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

*A metà, il 16 agosto 2026.* Fatti: solutore di Keplero, reconcile dei siti,
positioner con fotometria, notte e Luna per sito, geometria e airmass,
brillanza del cielo, magnitudine limite scomposta, finestre osservative — ognuno
con il suo test di verità contro Horizons dove una verità esiste. Mancano
**screening** (propagare tutto il catalogo e distillare `target_stats`),
**radar** (stati e transizioni) e **ranking**, cioè i tre pezzi che
trasformano una scheda per oggetto in una lista di stanotte.

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
| `backup` | ogni giorno 03:00 UTC | le sei tabelle non rigenerabili |
| `night_plan` | ogni 6 h | crepuscoli e Luna, due settimane avanti per sito |
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
