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

> **Stato al 17 agosto 2026 (sera): M0 e M1 chiusi, M2 cominciato.** Dal
> catalogo alla riga sullo schermo il giro è completo — catalogo → Keplero →
> positioner → sito → notte → cielo → limite → finestra → punteggio →
> dashboard → **proposito osservativo** — e gira su tutti gli oggetti insieme.
> I quattro lavori pesanti della notte stanno insieme in mezzo minuto:
> screening 13 s, finestre 12 s, radar 2 s, propositi < 1 s.
>
> ```
> 1.558.058 oggetti     1.557.104 asteroidi + 954 comete
> 1.557.088 con CEU     lo strato ASTORB agganciato all'MPC
>    14.900 monitorati  ACO con Tj < 3, comete, watchlist
>    14.730 finestre    (target × setup × notte) per i 4.910 entro portata
>       104 candidati   NEOCP/PCCP, 351 istantanee, e il destino di chi è uscito
> ```
>
> Ciò che sa dire, dal container — ed è la domanda del progetto:
>
> ```
> C/2019 E3 (ATLAS)   V 18.3, limite 21.2, margine 2.8 mag
>   utile 7.6 h dalle 02:28 alle 10:03 UTC · alt 76° · Luna a 122°
>   468 s × 1 posa · PRIME (0.881) · BEST SITE: cile-rio-hurtado
>   → in programma, e FADING: ultima occasione
>
> 2020 TY99   Tj 2.94, V 21.1 e in miglioramento
>   nessuna buona apparizione nei 15 anni guardati  →  OBSERVABLE
>
> P22pq2q → 2026 PN9   candidato NEOCP visto alle 07:50, designato alle 11:52
>   con la circolare MPEC 2026-Q11
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
| oggetti nuovi in catalogo (24 h, 7 giorni, 30 giorni) | ✅ | da `target.created_at`, l'unica data di primo avvistamento che esista: né MPCORB né ASTORB pubblicano la data di scoperta. Una finestra più lunga dell'archivio è marcata come tale — `target` è rigenerabile |
| riga di comando (`ingest`, `stato`, `siti`, `effemeride`, `screening`, `radar`, `finestre`, `candidati`) | ✅ | gli stessi moduli dell'interfaccia |
| pianificatore dei lavori automatici | ✅ | `/pianificatore`: cadenze, prossimo giro, esito, esegui-ora |
| popolazione monitorata configurabile | ✅ | regole dichiarative in `setting.screening_selectors`: Tj, H, q, classe, CEU, watchlist, liste a mano. Aggiungerne una non è una modifica al codice |
| pagina Candidati | ✅ | `/candidati`: chi è in lista, chi sta per essere perso, chi è sparito |
| recupero dopo un riavvio | ✅ | all'avvio guarda l'età dei dati, non l'orario mancato |
| aggiornamento automatico dei cataloghi | ✅ | risolto il 17 ago spostando il database in un **volume Docker**: la WAL di SQLite non regge virtiofs. 1.557.104 oggetti importati dentro il container, a servizio acceso, in 140 s |
| backup delle tabelle non rigenerabili | ✅ | kilobyte, non il gigabyte di catalogo che si riscarica |
| manutenzione settimanale | ✅ | pota i registri, riallinea le statistiche degli indici |
| reconcile dei siti (sito/telescopio/camera/setup) | ✅ | dagli YAML al database, idempotente; scala e campo derivati dalla focale, mai scritti a mano |
| rename dichiarato dell'hardware (`previous_codes:`) | ✅ | correggere un `code` rinomina la riga sul posto invece di dismetterla e ricrearla: l'`id` resta, e con lui `setup_calibration`, `observation_log` e `state_transition`. Senza, un rename riportava il `vlim_ref` dichiarato sopra quello misurato, in silenzio |
| pagina Osservatori | ✅ | `/osservatori`: hardware, derivati ottici e limiti, con riallineamento dai file |
| rete iTelescope (10 telescopi, 4 siti) | ✅ | T11/T21/T25 a Utah, T17/T30/T32/T59 a Siding Spring, T24 ad Auberry, T72/T73 in Cile. Ottica e camere dalle **schede di supporto** per singolo telescopio, che portano la data di modifica: il foglio di rete è del 2022 e il listino è indietro sulle camere. La scala derivata coincide con quella pubblicata su ogni telescopio |
| età delle specifiche hardware (`specs_checked_at`) | ✅ | badge in `/osservatori`: da quanto non si rilegge la scheda del fornitore, scala in mesi. `NULL` = mai verificata, che è diverso da vecchia |
| link alle pagine nell'intestazione | ✅ | come in stock42: le funzioni già costruite raggiungibili da ogni pagina, senza ripassare dalla home. Le voci `route=None` restano fuori |
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
| filtri e ricerca in tempo reale su Stanotte | ✅ | tipo, classe orbitale, giudizio, Tj, incertezza, «non osservato da», altezza, V, margine, durata — vocabolario **chiuso**, mai SQL dalla pagina. I filtri scelgono anche *quale setup* vince, ma il confronto fra siti resta intero (regola 5). Gli stessi nomi in `/api/stanotte` |
| elenchi a scorrimento ("mostra altri 20") | ✅ | tutte e tre le sezioni di `/stanotte`: il migliore per oggetto lo fa `row_number()` in SQL, quindi `OFFSET` è esatto e non salta né ripete righe |
| propositi osservativi e sessioni | ✅ | `/programma`: dal suggerimento alla decisione, e il registro di cosa si è ripreso. Un proposito scade da solo quando l'occasione passa, **con il motivo**: sceso sotto il limite, o niente finestra da quel sito |
| trailing ed esposizione consigliata | ✅ | `n × t`, con la posa massima dettata da traccia e pixel |
| incertezza posizionale vs campo, mosaico | ✅ | 3σ di CEU contro il lato corto del campo; CEU propagata a oggi in `target_stats.ceu_now_arcsec` |
| watcher NEOCP | ✅ | `neocp_poll` ogni 10 min: candidati, evoluzione, sparizioni. La storia che l'MPC non conserva |
| watcher PCCP | ✅ | `pccp_poll` ogni 20 min, stesso formato e stessa storia |
| destino dei candidati | ✅ | `destiny_poll` ogni 30 min: da candidato a NEO confermato con la sua circolare, pianetino designato, perso o inesistente. La fonte non è il testo delle MPEC ma la tabella dei trksub usciti di lista, che l'MPC pubblica già risolta |
| comete: elementi MPC e radar dedicato | ⏳ M2 | ordinate per geometria, non per magnitudine |
| verifica con Horizons sulla shortlist | ⏳ M2 | con budget giornaliero e cache; ogni chiamata a log |
| validazione due corpi contro Horizons | ⏳ M2 | 50 oggetti/mese a 1, 6, 12, 24 mesi (domanda aperta 2) |
| calibrazione di `vlim_ref` dalle misure | ⏳ M2 | i fatti battono il file di configurazione. **Da stasera la fonte di dati c'è**: `observation_log.limiting_mag` registra la magnitudine limite raggiunta in ogni sessione |
| notifiche | ⏳ M3 | prima serve sapere quante transizioni al giorno genera il radar |
| oggetti deep sky | — un domani | lo schema e il positioner sono già pronti a riceverli |
| pipeline di immagini (PSF, ricerca di coma) | — fuori | progetto separato: da sky42 riceverebbe solo la lista di target |

## Milestone

**M0 — il catalogo esiste.** ✅ *fatto il 15 agosto 2026.* Le tre sorgenti si
scaricano e si importano, il Tisserand è calcolato e indicizzato, la pagina
Catalogo mostra quanti e da quando. `SELECT count(*) FROM orbit WHERE
tisserand_j < 3` risponde: 34.048, che diventano 14.685 togliendo comete e
famiglie risonanti.

**M1 — l'MVP di IDEA.md.** ✅ *chiuso il 17 agosto 2026.* La domanda «cosa
entra sotto V 21 nei prossimi dodici mesi, e da dove si vede meglio» ha una
risposta sullo schermo senza aver chiamato JPL nemmeno una volta.

In ordine, tutto con il suo test di verità contro Horizons dove una verità
esiste: solutore di Keplero, reconcile dei siti, positioner con fotometria,
notte e Luna per sito, geometria e airmass, brillanza del cielo, magnitudine
limite scomposta, finestre osservative; poi **screening** (14.900 oggetti
propagati 24 mesi avanti e 15 anni indietro in 13 s), **finestre in massa**
(14.730 righe in 12 s, che hanno acceso il criterio sulla durata nel radar),
**radar** (stati e transizioni con isteresi), **ranking** (feature 0-1, pesi da
`scoring_profile`) e la **dashboard** `/stanotte` con `BEST SITE TONIGHT`.

**M2 — i radar MPC e le comete.** Più la validazione contro Horizons e la
calibrazione dei limiti, che è ciò che rende affidabile M1.

*Fatto:* il **watcher NEOCP/PCCP** (anticipato a M1, perché quella storia non si
recupera a posteriori) e il **destino dei candidati** — da candidato a NEO
confermato con la sua circolare, pianetino designato, perso o inesistente.

*Fuori programma ma indispensabile, dalla sera del 17 agosto:* i **propositi
osservativi** e il registro delle **sessioni**. Le altre pagine suggeriscono,
`/programma` registra le decisioni — e dice quando un'occasione è passata, con
il motivo: sceso sotto il limite, o niente finestra da quel sito.

*Resta:* il confine verso JPL con budget e cache, il radar dedicato alle comete,
le misure astrometriche (ADES) e la calibrazione di `vlim_ref` dalle sessioni.

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

### Dalle altre macchine

**<https://sky42.tail1a68b4.ts.net/>** — dentro la tailnet, niente esposto su
Internet. È l'indirizzo di un **servizio Tailscale**, come per brain42, stock42
e meteo42: il nome appartiene al servizio, non alla macchina, e l'host che lo
ospita si dichiara con

```bash
tailscale serve --service=svc:sky42 --bg --yes http://127.0.0.1:8242
```

La porta resta legata al solo loopback del Mac: `serve` inoltra lì il traffico
HTTPS del tailnet, e sulla LAN la porta non c'è proprio — sky42 non ha
autenticazione, e il giorno di `tailscale funnel` l'autenticazione arriva
prima. `SKY42_BIND_IP` resta nel `.env` come via alternativa (pubblicare la
porta direttamente sull'indirizzo Tailscale della macchina), ma col servizio
non serve: si lascia a `127.0.0.1`.

**L'ordine conta, ed è il primo passo quello che manca in genere.** Il
servizio va *creato* nella console (<https://login.tailscale.com/admin/services>,
nome `sky42` senza il prefisso `svc:`): è la creazione che assegna il VIP, e
finché il VIP non c'è l'`autoApprovers` non ha niente da approvare — l'host
annuncia nel vuoto e la console dice «0 hosts» senza nemmeno un candidato in
attesa. Quindi: **1.** crea il servizio in console, **2.** metti in policy
grant e autoApprover, **3.** `tailscale serve` qui, **4.** `drain` +
`advertise`. L'approvazione arriva da sola in circa un minuto.

Nella policy del tailnet servono due cose distinte — il **grant** decide chi
può *raggiungere* il servizio (la regola generica `dst: ["*"]` non copre i
servizi), gli **autoApprovers** chi può *ospitarlo*:

```json
"autoApprovers": {"services": {"svc:sky42": ["tag:brain42-host"]}},
"grants": [
	{"src": ["autogroup:member", "tag:brain42-host"],
	 "dst": ["svc:sky42"], "ip": ["tcp:443"]},
],
```

| sintomo | causa | rimedio |
|---|---|---|
| dominio inesistente | il servizio non esiste nel tailnet: senza VIP il nome non ha nulla dietro | crealo in console, poi `drain` + `advertise` |
| il nome risolve ma il TCP va in timeout | il VIP c'è, l'host non è approvato | gli `autoApprovers` qui sopra, poi `tailscale serve drain svc:sky42 && tailscale serve advertise svc:sky42` |
| `502` dal nome del servizio | il servizio c'è, l'app no | `docker compose up -d` |
| `serve status --json` non elenca `svc:sky42` | la configurazione è sparita | rieseguire il comando qui sopra |

`tailscale serve status` che dice `No serve config` **non è un guasto**: quel
comando guarda la configurazione del *nodo*, e `svc:sky42` è un *servizio* —
si vede solo con `--json`. E `tailscale` non è nel PATH di macOS: sul Mac mini
c'è un involucro in `/usr/local/bin/tailscale` (non un symlink, che non
funziona).

In alternativa a Docker c'è un LaunchAgent pronto in
[scripts/](scripts/com.ddemartin.sky42.plist).

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
