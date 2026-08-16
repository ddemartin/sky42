# Memorandum sky42 — il "perché" delle decisioni

README dice **cosa** c'è, CLAUDE.md dice **come** si lavora. Qui sta il
**perché**: ogni scelta con la sua data e il criterio che l'ha decisa, comprese
le ipotesi che i fatti smentiranno.

Una decisione senza il suo motivo, dopo tre mesi, è indistinguibile da un
capriccio: si rifà il giro, si cambia, e si riscopre il problema che l'aveva
motivata. Ogni voce riporta l'alternativa scartata, perché è quella che tornerà
a sembrare buona.

Il documento di partenza è [IDEA.md](IDEA.md), che resta com'è: qui si registra
cosa è stato effettivamente costruito e dove ci si è discostati. Le formule
stanno in [docs/modelli.md](docs/modelli.md), lo schema in
[docs/schema.sql](docs/schema.sql).

---

## 2026-08-15 — si progetta lo schema e i confini, non si scrive codice

Prima riga di questo progetto. Il motivo è che sky42 ha una sola decisione
davvero irreversibile, e non è tecnologica: **dove passa il confine fra ciò che
si calcola in casa e ciò che si chiede a JPL**. Tutto il resto — il framework
web, il formato dei file, il modo di disegnare la dashboard — si cambia in un
pomeriggio. Quel confine invece decide se il sistema regge un catalogo da un
milione di oggetti o muore al primo giro.

**Alternativa scartata:** partire dalla dashboard con dieci oggetti presi a
mano da Horizons. Sarebbe stato più veloce da vedere e avrebbe insegnato zero
sul problema vero, che è di scala.

## 2026-08-15 — ASTORB e non MPCORB come catalogo principale

IDEA.md lo suggeriva; il motivo per confermarlo è più preciso di «è un
catalogo». ASTORB porta due colonne che MPCORB non ha e che qui non sono
accessorie: la **CEU** (current ephemeris uncertainty, in arcsec, con la sua
derivata) e la **data dell'ultima osservazione**.

Sono esattamente i due assi su cui il progetto seleziona. La CEU risponde a
«ci sta nel campo o serve un mosaico», la data dell'ultima osservazione
risponde a «quanto è trascurato», e la rarità è metà dell'interesse
scientifico. MPCORB dà il parametro U, che è una scala 0-9 a gradini: dice se
un'orbita è buona, non quanti secondi d'arco di incertezza ha stanotte.

MPCORB resta come complemento (arriva prima sugli oggetti nuovi) e le due fonti
convivono in `orbit.source`, ma la CEU non si sostituisce.

**Alternativa scartata:** solo MPCORB, più diffuso e meglio documentato. Avrebbe
costretto a chiedere a JPL l'incertezza oggetto per oggetto — cioè a violare la
regola 2 per una colonna.

## 2026-08-15 — due corpi per lo screening, Horizons per puntare

**La decisione centrale del progetto.** Lo screening propaga le orbite con un
modello a due corpi puro, senza perturbazioni planetarie, senza relatività,
senza Yarkovsky.

Il criterio è nell'obiettivo dichiarato in IDEA.md: allo screening basta
distinguere V 19.5 da V 21 da V 24. La magnitudine dipende da `r` e `Δ`, che
sono grandezze *lente*: l'errore che il modello a due corpi accumula è
essenzialmente **lungo l'orbita**, cioè in anticipo o ritardo di fase. Un
oggetto che arriva tre giorni dopo la data prevista ha, alla data prevista, in
pratica la stessa magnitudine. Sulla posizione in cielo lo stesso errore è
invece letale — ed è esattamente lì che si chiama Horizons, sulla shortlist,
dove le chiamate sono decine e non un milione.

Questo separa in due il concetto di "effemeride" e va tenuto separato anche nel
codice: `orbits/propagate.py` fa screening, `external/horizons.py` fa
puntamento. Chi confonde i due usi otterrà un sistema che sbaglia in silenzio.

**Alternativa scartata:** un integratore n-body (REBOUND) per avere posizioni
buone in casa. Costa una dipendenza compilata, un ordine di grandezza di tempo
di calcolo, e la necessità di gestire le epoche di partenza — per una
precisione che serve a poche decine di oggetti al giorno, che Horizons dà
esatta e gratis.

**Ipotesi da verificare con numeri, non con ragionamenti:** un job di
validazione confronta ogni mese 50 oggetti campionati con Horizons a 1, 6, 12,
24 mesi e registra i residui in posizione e magnitudine. Se il residuo in
magnitudine supera 0.3 mag l'ipotesi qui sopra è falsa e va rivista.

## 2026-08-15 — motore orbitale a tre livelli, e il livello 0 è vettoriale

```
livello 0   numpy puro, tutti gli oggetti × tutte le epoche insieme    screening
livello 1   Skyfield, un oggetto per volta, topocentrico               notte e finestre
livello 2   Horizons                                                   verifica e puntamento
```

Il livello 0 non esiste per eleganza. Skyfield sa propagare un'orbita
kepleriana, ma lo fa con un oggetto Python per corpo: su centomila asteroidi ×
centocinquanta epoche il ciclo Python è la differenza fra quaranta secondi e
un'ora, e un'ora significa che lo screening non si rifà mai volentieri. Il
solutore di Keplero vettoriale è una funzione di trenta righe con un test di
verità: si scrive una volta.

Il livello 1 usa Skyfield perché rifare Sole, Luna, precessione, nutazione e
rifrazione a mano è come si sbaglia — lì gli oggetti sono pochi e il ciclo
Python non pesa.

**Alternativa scartata:** un solo livello, Skyfield ovunque. Più semplice da
scrivere, e lo screening completo diventa un lavoro notturno invece che un
lavoro di minuti.

## 2026-08-15 — le dipendenze: Skyfield, no astropy, no astroquery, no poliastro

`numpy`, `skyfield`, `httpx`, `fastapi`, `uvicorn`, `jinja2`, `apscheduler`,
`pydantic`, `pyyaml`, `pytest`. Nient'altro.

Skyfield tira dentro solo `jplephem` e `sgp4` e legge DE440s (~32 MB) senza
compilare niente. `astropy` sarebbe un'ottima libreria e qui servirebbe per
funzioni che Skyfield già copre, con un peso di installazione molto maggiore.
`astroquery` serve solo a parlare con Horizons, che ha un'API HTTP JSON
documentata: il client sono centoventi righe di `httpx` e in cambio si
controllano cache, budget e log delle chiamate, che con `astroquery` sarebbero
nascosti dietro la libreria — e la regola 2 dice che quelle chiamate vanno
contate. `poliastro` è archiviato.

**Alternativa scartata:** astropy + astroquery, la scelta ovvia e quella che
farebbe chiunque. Rivedibile senza costi: nessuna riga di sky42 dipende
dall'assenza di astropy.

## 2026-08-15 — SQLite, e le cinque tabelle che non sono rigenerabili

SQLite in WAL, un file, nessun servizio. Un milione di righe di catalogo con
qualche indice sta sotto il gigabyte e le query che servono sono selezioni su
colonne indicizzate.

La parte che conta è però un'altra: **quasi tutto il database è rigenerabile e
cinque tabelle no.** Rigenerabili sono catalogo, tracce, statistiche, notti e
finestre — si riscaricano e si ricalcolano. Non lo sono:

- `mpc_candidate` e `mpc_candidate_snapshot`, perché **l'MPC riscrive la lista
  NEOCP e non conserva niente**: la storia di un candidato — come si è mosso,
  quante osservazioni ha accumulato, che fine ha fatto — dopo la rimozione
  esiste solo qui. È il dato più prezioso del sistema ed è anche l'unico che
  non si può riscaricare;
- `state_transition`, per lo stesso motivo applicato al proprio archivio;
- `observation_log` e `watchlist`, che sono di chi osserva;
- `setup_calibration`, che sono misure fatte sul campo.

Da qui discendono due vincoli nello schema: il backup copia quelle cinque, e
nessuna di esse ha una chiave esterna distruttiva verso il gruppo rigenerabile
(`observation_log.setup_id` è senza CASCADE apposta).

**Alternativa scartata:** PostgreSQL, per non doverci pensare più. Aggiunge un
servizio da tenere in piedi 24/7 su un Mac mini per un carico che è a
scrittore singolo.

## 2026-08-15 — le tracce di screening in BLOB, non in righe

`screening_track` tiene le serie temporali (V, r, Δ, elongazione, RA, Dec) come
BLOB `float32` — una riga per oggetto invece di centottanta.

Il criterio è l'uso: su quei numeri non si fanno mai query relazionali. Si
leggono tutti insieme per estrarne eventi (quando scende sotto 21, quando è al
picco), e gli eventi finiscono in `target_stats`, che invece si interroga. Un
milione di righe per ventimila oggetti, con indici, per non interrogarle mai è
tutto costo e nessun beneficio: quattro kilobyte per oggetto si rileggono con
`numpy.frombuffer` senza copie.

**Alternativa scartata:** una riga per (oggetto, epoca), la forma normale. Più
ortodossa, e trasforma un ricalcolo dello screening in milioni di INSERT.

**Alternativa scartata 2:** file `.npz` fuori dal database. Perde
l'atomicità — una traccia e la statistica che ne deriva devono essere coerenti,
e nella stessa transazione lo sono per costruzione.

## 2026-08-15 — l'hardware si decompone: sito, telescopio, camera, setup

*(risposta al primo vincolo dell'addendum: siti, strumenti e CCD cambiano)*

IDEA.md prevedeva `Observatory` e `Instrument`. Un `Instrument` monolitico
funziona finché la configurazione è ferma: il giorno in cui la stessa camera
passa su un altro telescopio, o lo stesso telescopio prende un CCD nuovo, si
duplicano righe e i dati storici perdono senso.

Quindi quattro tabelle. **Sito** (dove), **telescopio** (apertura, focale,
limiti di montatura), **camera** (pixel, formato, rumore), e **setup**, che è la
combinazione telescopio × camera × binning × filtro. Il setup è ciò che l'`Instrument`
di IDEA.md descriveva, e resta l'unica cosa che il visibility engine conosce:
ha una scala, un campo, un limite di magnitudine.

Scala e campo **non si scrivono, si derivano** dalla focale e dai pixel. Un
campo scritto a mano diverge da quello vero delle immagini, e diverge in
silenzio.

Corollario, che è la regola 3: **niente si cancella mai.** Si scrive `valid_to`
e `active: false`. Un'osservazione fatta nel 2026 con un setup dismesso nel
2028 deve restare leggibile con il campo giusto.

**Alternativa scartata:** un solo `Instrument` con i campi ripetuti, più
semplice da leggere. Regge finché non cambia niente, cioè fino alla prima
volta che serve.

## 2026-08-15 — la configurazione dei siti sta in YAML, il database la indicizza

Un file per osservatorio in `config/sites/*.yml`, versionato in git, con
telescopi, camere e setup dentro. All'avvio un `reconcile()` allinea le
tabelle: crea il nuovo, aggiorna, e **disattiva** ciò che non c'è più.

È la stessa regola di brain42 sui file Markdown, applicata al dominio giusto:
la configurazione osservativa si scrive a mano, si legge a colpo d'occhio, e si
vuole poterla confrontare con quella di sei mesi fa con un `git diff`. Una
tabella SQL non ha nessuna di queste tre proprietà.

Il reconcile ha una sola eccezione dichiarata: **non sovrascrive `vlim_ref` se
esistono misure in `setup_calibration`.** Il file dice l'intenzione, le misure
dicono i fatti, e i fatti vincono. È anche il punto in cui il sistema migliora
da solo con l'uso invece di restare fermo alla stima iniziale.

**Alternativa scartata:** una pagina di amministrazione nell'interfaccia web.
Da scrivere e mantenere, per modificare cinque numeri due volte l'anno.

## 2026-08-15 — `target` non sa che cosa sia, e il positioner lo sa per lui

*(risposta al secondo vincolo dell'addendum: un domani, deep sky)*

`target` porta identità, `kind` e nome, e nient'altro. Gli elementi orbitali
stanno in `orbit`, le coordinate fisse in `fixed_target`. Chi sta a valle —
finestre, Luna, limiti, score, dashboard — punta a `target(id)` e riceve le
posizioni da un **positioner**, un contratto unico:

```
positions(target, jd_array) -> RA, Dec, Δ, r, V, motion
```

`KeplerianPositioner` per asteroidi e comete, `FixedPositioner` per un oggetto
a coordinate fisse (motion = 0, Δ e r non definiti), `HorizonsPositioner` per
la verifica. Il visibility engine non sa quale sia in uso, e questa è la regola
4.

Il costo di questa astrazione oggi è **una funzione e una tabella vuota**. Il
costo di non averla si paga il giorno in cui una galassia dovrebbe passare da
un motore che assume `a`, `e` e `i`. `fixed_target` sta nello schema fin da
subito proprio per questo: una generalizzazione che non ha mai avuto un secondo
caso d'uso è di solito sbagliata, e tenerla scritta la rende verificabile.

Resta un pezzo dichiaratamente non fatto: per un oggetto **esteso** il limite
giusto è fra brillanza superficiale e brillanza del cielo, non fra magnitudine
integrata e limite puntiforme. `visibility/limits.py` è scritto perché il
modello puntiforme sia *una* strategia scelta su `kind`, non l'unica possibile.

**Alternativa scartata:** un `asteroid` in cima e la generalizzazione «quando
servirà». Quando serve, il motore è già scritto assumendo che ogni target abbia
un'anomalia media, e la generalizzazione diventa una riscrittura.

## 2026-08-15 — il costo scala con i siti, non con gli strumenti

Sole, Luna, crepuscoli, alt/az e airmass dipendono dal **sito**. Il setup
aggiunge soltanto i propri limiti — altezza minima, airmass massima, limite di
magnitudine, scala — che sono aritmetica sugli stessi array.

Quindi `night` sta per osservatorio e `observation_window` per setup, e la
geometria si calcola una volta sola per sito e si riusa per tutti i suoi setup.
Con tre siti e otto setup la differenza è già un fattore due-tre sul lavoro
notturno; con dieci setup per sito è un ordine di grandezza.

È scritto qui perché la versione sbagliata è quella che viene naturale: un
ciclo su tutti i setup che dentro chiama il calcolo della geometria.

## 2026-08-15 — la magnitudine limite efficace è un modello fisico

IDEA.md chiedeva penalità per airmass, Luna, crepuscolo e trailing. La
tentazione è una tabella di numeri a mano («Luna piena: −0.6»). La scelta è
invece passare dalla **brillanza del cielo**: Krisciunas & Schaefer 1991 dà la
luminanza dovuta alla Luna in funzione di fase, separazione, altezza della Luna
e altezza del target, e da lì la penalità esce come `1.25 log₁₀(B_tot/B_scuro)`
perché in regime sky-limited S/N ∝ 1/√B.

Tre ragioni. Primo, i casi limite escono giusti da soli: **una Luna piena sotto
l'orizzonte non penalizza** perché il termine di estinzione lunare va a zero,
senza bisogno di un `if` che qualcuno prima o poi scriverà al contrario.
Secondo, il modello ha *un* parametro per sito (la brillanza allo zenit) invece
di una matrice di casi. Terzo, si taratura contro le misure vere.

La penalità di crepuscolo, invece, è una formula empirica lineare dichiarata
tale in docs/modelli.md: è il numero più debole del sistema e va corretto con i
dati, non difeso.

**Alternativa scartata:** tabella di penalità per fase lunare. Più veloce da
scrivere di mezza giornata, e sbaglia proprio nei casi che contano — Luna alta
vicino al target, Luna piena tramontata.

## 2026-08-15 — la Luna non entra nello score

Conseguenza della decisione precedente, e merita una voce sua perché è
l'errore che si rifà. Il disturbo lunare è **già dentro** `depth_margin`
attraverso `eff_vlim`. Aggiungere un termine "moon penalty" al punteggio la
conta due volte e produce classifiche che al plenilunio puniscono due volte gli
stessi oggetti — mentre un oggetto brillante a 90° dalla Luna, che sta benissimo,
verrebbe penalizzato per una condizione che non lo tocca.

Regola generale che ne discende: **ogni grandezza entra nello score una volta
sola**, e se è già dentro un'altra grandezza, non entra.

## 2026-08-15 — la finestra migliore si cerca campionando, non risolvendo

Cinque minuti di passo su tutta la notte, si valuta la qualità in ogni punto,
si prende il massimo e l'intervallo attorno.

Il transito non è l'ottimo quasi mai quando c'è la Luna: la funzione da
massimizzare ha dentro separazione lunare, altezza della Luna, crepuscolo e
magnitudine variabile, e non ha un massimo analitico decente. Il campionamento
costa: con 288 punti per notte per sito è aritmetica su array. In cambio la
stessa funzione vale per qualunque positioner e per qualunque criterio futuro,
e permette di rispondere a `BEST SITE NOW` oltre che a `BEST SITE TONIGHT`,
perché la classifica dei siti si ha in ogni istante e non solo in media.

**Alternativa scartata:** transito ± n ore. Semplice, e sbaglia esattamente
nelle notti in cui la scelta conta.

## 2026-08-15 — isteresi negli stati, o il radar diventa rumore

Soglie con margine di 0.15 mag e conferma su due calcoli consecutivi prima di
scrivere una transizione.

Senza, un oggetto che oscilla attorno al limite genera transizioni tutti i
giorni, e un radar che notifica tutti i giorni non lo guarda più nessuno — che
è il modo in cui questo tipo di strumento fallisce davvero, non sbagliando i
conti.

## 2026-08-15 — FastAPI + Jinja + htmx, nessun build step

Nessun `npm`, nessun bundler, nessun framework front-end. Le pagine sono
template Jinja, l'interattività è htmx (un file JavaScript da servire in
locale, dentro l'immagine come tutto il resto).

Il criterio è che questo progetto è fatto di calcoli e dati, e ha una
dashboard. Una catena di build JavaScript aggiungerebbe una seconda toolchain
da mantenere e da aggiornare per una console che si guarda da un browser di
casa. Se un giorno servirà una curva interattiva, si aggiunge una libreria di
grafici in un tag `<script>`.

**Alternativa scartata:** React + API JSON. Più bello da mostrare e il doppio
delle cose da tenere in piedi.

## 2026-08-15 — APScheduler dentro l'app, niente Celery

Uno scheduler nel processo dell'app, `max_instances=1` per job, i lavori pesanti
in un `ProcessPoolExecutor`. Nessun Redis, nessun worker separato.

Il carico è: un download al giorno, qualche polling ogni dieci minuti, e un
paio di calcoli numerici pesanti che possono durare minuti. Su una macchina
sola, con un unico scrittore, Celery aggiunge un broker da tenere vivo e un
secondo processo da osservare, in cambio di una robustezza che qui non serve —
se il Mac mini è spento, non c'è coda che tenga.

Il vincolo che questo impone, e che va rispettato: **il lavoro numerico non
gira mai nel loop async**, o la dashboard si blocca mentre lo screening macina.

**Alternativa scartata:** Celery + Redis. Da rivedere solo se i job diventeranno
tanti da doversi distribuire, che con un Mac mini non succede.

## 2026-08-15 — un job non ne chiama un altro

Ogni job pubblica il suo risultato nel database; il successivo lo trova alla
sua cadenza. `screening` non chiama `radar_states`, che non chiama `windows`.

Così ogni job si rilancia a mano senza effetti a cascata, un fallimento non
propaga, e la diagnosi è sempre la stessa domanda: *quale job ha girato per
ultimo e cosa ha scritto?* — che è la riga in `job_run`.

**Alternativa scartata:** una pipeline concatenata, più efficiente di qualche
minuto e molto peggiore da riparare alle sette di sera.

## 2026-08-15 — la magnitudine cometaria si mostra, non ci si ordina sopra

`m1 = M1 + 5 log Δ + K1 log r` sbaglia regolarmente di due o tre magnitudini, e
IDEA.md lo dice già. La conseguenza pratica è che le comete si ordinano per
**geometria** — r, Δ, elongazione, trend, distanza dal perielio — e la
magnitudine compare come stima dichiarata tale.

Le due fotometrie non si mescolano mai: un oggetto con `kind = 'comet'` non usa
H-G nemmeno se ha un H nel catalogo, perché una chioma non è un corpo solido e
il risultato sarebbe sbagliato con l'aria di essere giusto.

## 2026-08-15 — porta 8242, e il servizio non esce di casa

`localhost:8242` (brain42 sta su 8142). Nessuna autenticazione nell'MVP perché
il servizio non esce dalla macchina; il giorno in cui esce — tailnet o
funnel — l'autenticazione arriva prima, non dopo, come su brain42.

## 2026-08-15 — cosa resta fuori dall'MVP, e perché

L'MVP è quello di IDEA.md: ASTORB, Tj, siti, screening, finestre, dashboard con
Tonight / Coming into range / Tj < 3.

Restano fuori per scelta, non per dimenticanza:

- **NEOCP, PCCP, MPEC.** Sono la seconda fase in IDEA.md, ma con una riserva
  che vale la pena scrivere: la loro storia non è recuperabile a posteriori
  (voce sulle cinque tabelle). Ogni settimana di ritardo è storia persa per
  sempre. Se l'MVP dovesse allungarsi, il polling NEOCP va anticipato *anche
  se nessuno lo guarda ancora*: raccogliere costa poche righe, recuperare è
  impossibile.
- **La pipeline di immagini** (plate solve, moving stack, PSF, ricerca di coma).
  IDEA.md la mette già fuori. È un progetto suo, che riceverebbe da sky42 solo
  una lista di target.
- **Le notifiche.** Serve prima sapere quante transizioni al giorno genera il
  radar, o si progetta un canale per un volume che non si conosce. La domanda è
  aperta qui sotto.

## 2026-08-15 (più tardi) — l'interfaccia parte da tabelle, ma l'API nasce già separata

*(vincolo aggiunto: l'operatività completa passa dall'app web, che dovrà
scalare — oggi tabelle, domani curve di visibilità)*

La dashboard dell'MVP sono tabelle HTML. La regola che la rende estendibile non
è tecnologica ma di confine: **ogni pagina ha un endpoint JSON gemello che
restituisce gli stessi dati**, e il template Jinja consuma quello, non le query.
`GET /api/tonight` esiste dal primo giorno anche se lo legge solo il template.

Costa nulla adesso — la query si scrive comunque — e il giorno in cui serve una
curva di altezza interattiva c'è già la sorgente dati, senza dover sventrare
una vista che mescolava SQL e HTML. Le serie temporali per i grafici, poi, sono
già nel database: `screening_track` tiene le tracce e il campionamento notturno
produce array, quindi un endpoint `GET /api/target/{id}/curve` è una lettura,
non un calcolo nuovo.

**Alternativa scartata:** template che interrogano direttamente il database,
più diretti da scrivere. Rendono ogni grafico futuro una riscrittura della
pagina che lo contiene.

## 2026-08-15 (più tardi) — il lavoro di fondo è un ospite, non il padrone della macchina

*(vincolo aggiunto: il Mac mini fa già girare altri processi in background)*

Non basta dire "gira in background": un ciclo numpy su un milione di orbite
prende tutti i core e fa arrancare tutto il resto. Cinque misure concrete, in
ordine di efficacia:

1. **`OMP_NUM_THREADS=1` e `VECLIB_MAXIMUM_THREADS=1`** nei processi di calcolo.
   Su macOS numpy usa Accelerate, che di suo si prende tutti i core per una
   singola operazione su array. È il punto in cui si passa da "il Mac mini è
   inutilizzabile" a "non te ne accorgi", e costa una variabile d'ambiente.
   Il parallelismo lo decidiamo noi, non la libreria.
2. **`max_workers` piccolo e dichiarato** (default 2), mai `os.cpu_count()`.
3. **`os.nice(10)`** nell'inizializzatore del pool: i job di sky42 perdono
   sempre contro tutto il resto.
4. **Lavoro a blocchi con controllo fra un blocco e l'altro**: lo screening
   processa 20.000 oggetti per volta e fra un blocco e l'altro guarda
   `os.getloadavg()`. Sopra la soglia, dorme. Da stdlib, nessuna dipendenza.
   Un job interrompibile è anche un job che si può fermare a mano senza
   `kill -9`.
5. **Download condizionati e differenziali**: ETag e `If-Modified-Since` su
   tutto, e per ASTORB i file `.add`/`.del` (vedi la voce sotto).

Il criterio con cui si misura: mentre gira lo screening, la dashboard deve
restare reattiva. Se non lo è, il difetto è qui, non nell'algoritmo.

**Alternativa scartata:** lanciare i job pesanti solo di notte con un orario
fisso. Non funziona con osservatori su tre continenti — a Santiago è notte
quando qui si lavora — e non protegge dagli altri processi, che non hanno un
orario.

## 2026-08-15 (più tardi) — la fonte è MPCORB, ASTORB è uno strato di arricchimento

**Questa voce annulla la decisione «ASTORB e non MPCORB come catalogo
principale» presa qualche ora prima.** Resta scritta sopra perché il motivo per
cui era sbagliata è più utile della decisione giusta.

L'errore era aver scelto la fonte guardando *una* colonna (la CEU) invece
dell'insieme. Scaricati e confrontati i file interi il 15 agosto 2026:

| | MPCORB (extended) | ASTORB |
|---|---|---|
| oggetti | 1.556.465 | 1.556.977 |
| provenienza | l'MPC riceve le osservazioni e assegna le designazioni | orbite ricalcolate da Lowell **su osservazioni scaricate dall'MPC** |
| data ultima osservazione | `Last_obs`, esatta, sul 100% dei record | **assente** |
| numero di opposizioni | sì | no |
| residuo rms dell'orbita | sì | no |
| classe orbitale | `Orbit_type`, esplicita | sei codici interi che la documentazione stessa dichiara non sempre corretti |
| designazioni alternative | `Principal_desig` + `Other_desigs` | solo il nome corrente |
| incertezza | `U`, scala 0-9 a gradini | **CEU in arcsec, con derivata, prossimo picco e picchi a 10 anni** |
| dati fisici | no | B-V, diametro IRAS, classe tassonomica |
| epoca di osculazione | ogni ~200 giorni (oggi a 67 giorni) | ogni 100 giorni (oggi a −33) |

**Sulla copertura sono ridondanti, e va detto perché la prima versione di
questa voce diceva il contrario.** Avevo scritto «MPCORB ha 400.000 oggetti in
più» prendendo il conteggio dalla pagina di documentazione di Lowell, che
riporta 1.156.676 ed è ferma da anni. Contati i record veri, ASTORB ne ha
1.556.977. La sovrapposizione misurata:

```
numerati        895.910 in entrambi,  0 da una parte sola
non numerati    660.259 in entrambi,  808 solo ASTORB,  296 solo MPCORB
```

Cioè **il 99,93% della popolazione è la stessa**. Gli 808 solo-ASTORB sono
oggetti persi da decenni (1927 LA, 1935 UZ: arco di 4 giorni, CEU di 500 gradi)
che l'MPC ha smesso di pubblicare perché non se ne può fare una previsione
sensata; i 296 solo-MPCORB sono di questi giorni (2026 PV7, PW7, PX7…) e
diranno che **l'MPC arriva prima sui nuovi**, che è il pezzo che conta.

Lezione da non ripetere: **il conteggio si prende dal file, non dalla pagina che
lo descrive.**

Restano quindi due fatti a decidere, non tre:

- **ASTORB non contiene la data dell'ultima osservazione.** Il formato
  ufficiale ha 25 parametri e nessuno è quello: c'è solo l'arco in giorni.
  Metà della ragione per cui l'avevo scelto — «la rarità è metà
  dell'interesse scientifico» — riposava su un campo che quel file non ha.
- **ASTORB è un prodotto derivato**, e arriva un giorno dopo sui nuovi oggetti.
  Quando due fonti dicono cose diverse, quella a monte ha ragione per
  costruzione.

Regalo inatteso della verifica: **le chiavi combaciano senza normalizzare
nulla** — numero per i numerati, designazione testuale per gli altri, zero
discrepanze su 895.910 numerati. Il join che sembrava la parte rischiosa della
fusione è una `JOIN` e basta.

Resta però vero che la **CEU non ha equivalenti**: `U` è una scala a gradini
sull'orbita, non un numero di arcsec per stanotte, e la domanda «ci sta nel
campo o serve un mosaico» vuole arcsec. Quindi ASTORB resta, come strato.

Conseguenza sullo schema: `orbit` viene solo dall'MPC, e i campi ASTORB si
spostano in una tabella a parte, `astorb_extra`. Non è pignoleria di
normalizzazione: ASTORB è un file storico a manutenzione ristretta, e se un
giorno smette di aggiornarsi voglio **perdere una funzione, non avere metà di
`orbit` che invecchia in silenzio** mentre l'altra metà è fresca.

**Alternativa scartata:** solo MPCORB, rinunciando alla CEU e stimando
l'incertezza da `U` con una tabella di conversione. La conversione esiste in
letteratura ma dà un ordine di grandezza, e il criterio «ci sta nel campo» si
gioca su un fattore due.

**Alternativa scartata 2:** una riga sola in `orbit` con provenienza mista
dichiarata in due colonne. Più comoda da interrogare, e nasconde il caso in cui
metà riga è di ieri e metà di sei mesi fa.

## 2026-08-15 (più tardi) — `mpcorb_extended.json.gz`, non `MPCORB.DAT`

L'MPC pubblica gli stessi oggetti in due formati. Si usa il JSON.

Il file a colonne fisse costringe a decodificare designazioni ed epoche
impacchettate (`K2669` = 2026-06-09, `~0Uvq` = 738906) e a fidarsi di offset
che cambiano senza preavviso. Il JSON dà l'epoca già in JD (2461200.5), il
numero e la designazione in chiaro, **e in più** `Tp`, `Perihelion_dist`,
`Aphelion_dist`, `Orbital_period`, `Orbit_type`, `Other_desigs`. Pesa 181 MB
compressi contro 316 MB non compressi, e si legge in streaming senza tenerlo
tutto in memoria.

`Other_desigs` non è un dettaglio: è ciò che permette di riconoscere che un
candidato NEOCP è un oggetto già noto sotto un altro nome, che è una delle
transizioni da seguire secondo IDEA.md.

**Alternativa scartata:** MPCORB.DAT, il formato che usano tutti e per cui
esistono più esempi in giro. Un parser a colonne fisse in più da mantenere, per
avere meno dati.

## 2026-08-15 (più tardi) — ASTORB si aggiorna in differenziale

Lowell pubblica `yymmdd.add` e `yymmdd.del` accanto ad `astorb.dat.gz`, con le
orbite aggiunte o sostituite quel giorno, per gli ultimi trenta giorni circa.
Con quelli l'aggiornamento quotidiano costa qualche centinaio di kilobyte
invece di 113 MB.

Con un limite dichiarato, che sta nella documentazione di Lowell: **i `.add`
riportano solo i cambi di elementi orbitali, non gli aggiornamenti quotidiani
di CEU** — che sono esattamente ciò per cui teniamo ASTORB. Quindi: `.add`/`.del`
per gli elementi durante la settimana, e un giro completo settimanale per
riallineare le CEU. Chiude in parte la domanda aperta 8.

## 2026-08-15 (più tardi) — Tj < 3 da solo non seleziona quello che credevamo

Misurato sui file interi: **33.394 oggetti hanno Tj < 3.0** (il 2,1% del
catalogo). Ma incrociando con `Orbit_type` dell'MPC:

```
Jupiter Trojan   16.321   (il 100% della classe)
MBA              10.719
Hilda             2.425   (il 33% della classe)
Apollo            1.290
q < 1.665 AU      1.106
Amor                830
Distant Object      617
```

**Il 58% della popolazione Tj < 3 sono Troiani, Hilda e oggetti distanti**: tutti
i 16.321 Troiani di Giove stanno sotto 3 per costruzione, essendo in risonanza
1:1 con Giove. Sono dinamicamente stabilissimi ed è il contrario di ciò che
IDEA.md cerca — un asteroide su orbita cometaria è un oggetto che *scambia
energia* con Giove, non uno che ci gira insieme.

Quindi la popolazione privilegiata non è «Tj < 3» ma **«Tj < 3 escluse le
famiglie risonanti»**, e sono 13.945 oggetti: un numero che si propaga
comodamente due volte al giorno.

Questa è anche la dimostrazione più concreta del perché la fonte deve essere
l'MPC: il filtro di punta del progetto **non funziona senza una classificazione
orbitale affidabile**, e i codici interi di ASTORB sono dichiarati inaffidabili
dalla loro stessa documentazione.

L'esclusione è una riga in `setting`, non una costante nel codice: un domani
si potrebbe voler guardare proprio gli Hilda con Tj basso.

## 2026-08-15 (più tardi) — quanto vale davvero lo strato ASTORB, in percentuale

Distribuzione della CEU su tutti gli 1.556.977 oggetti:

```
CEU < 1"        1.280.250   82,2%     orbita ottima: si punta e si trova
CEU 1-10"          79.756    5,1%
CEU 10-60"         19.887    1,3%
CEU 1'-10'         44.060    2,8%     qui la CEU decide fra puntare e fare mosaico
CEU 10'-60'        42.617    2,7%
CEU > 1°           90.407    5,8%     di fatto persi
```

Per l'82% degli oggetti la CEU non serve a niente: sono orbite ottime e
qualunque strumento li trova. **Serve per il 5,5% nella fascia degli arcominuti**,
dove è letteralmente la differenza fra una posa e un mosaico, e per riconoscere
il 5,8% che è inutile inseguire.

Vale la pena tenere ASTORB per il 5,5% del catalogo? Sì, perché è **il 5,5% che
coincide con gli oggetti trascurati**, cioè con l'interesse dichiarato in
IDEA.md: un oggetto con orbita ottima e osservazioni recenti è, per definizione,
uno che seguono già tutti. La CEU alta *è* il segnale di rarità.

## 2026-08-15 (sera) — NiceGUI e lo schema di stock42

**Annulla la decisione «FastAPI + Jinja + htmx» presa in mattinata.**

Il criterio non è tecnico ma di continuità: stock42 gira già in NiceGUI su
questa macchina, con `core/` `services/` `gui/` `main.py`. Tenere due schemi
diversi in due progetti dello stesso autore costa a ogni ritorno sul codice
dopo due mesi.

La ragione che avevo scritto per Jinja+htmx — «nessuna catena di build
JavaScript» — vale identica per NiceGUI, che è Python puro. E in più risolve il
vincolo che è arrivato dopo: **i grafici di visibilità sono inclusi**, mentre
con htmx avrebbero richiesto comunque una libreria in un `<script>`.

Quindi: `core/` dominio, `services/` orchestrazione, `gui/pages/` una rotta per
funzione, porta 8242.

**Alternativa scartata:** restare su FastAPI+Jinja. Più leggera di qualche
megabyte e con un secondo schema mentale da mantenere.

## 2026-08-15 (sera) — un indice mancante: 14 secondi contro più di un'ora

Il primo import di ASTORB ha impiegato 14 secondi. Dopo aver aggiunto
`AND kind = 'asteroid'` alla ricerca di aggancio, lo stesso import girava da
oltre un quarto d'ora al 100% di CPU senza scrivere una riga.

Causa: c'erano due indici separati, uno su `number` e uno su `kind`. SQLite ne
sceglie **uno** per una ricerca con due uguaglianze, e senza statistiche
(`ANALYZE` non era mai stato eseguito) ha scelto quello su `kind` — che per
`kind='asteroid'` seleziona un milione e mezzo di righe invece di una. Per
20.000 record a blocco fa 3×10¹⁰ righe visitate.

Due correzioni, entrambe necessarie:

- indice **composito** `(number, kind)` e `(primary_desig, kind)`: il piano
  giusto non dipende più dalle statistiche. Diventa anche un covering index;
- **`ANALYZE` alla fine dell'import di MPCORB.** Non è manutenzione
  rimandabile: è ciò che dà al planner i numeri veri.

Verificato dopo: `SEARCH t USING COVERING INDEX idx_target_number_kind`, e
l'import è tornato a 15 secondi.

La lezione generale, che vale oltre questo caso: **una condizione in più in una
`WHERE` può cambiare il piano di esecuzione**, e un piano sbagliato non dà
errore — dà lo stesso risultato, molto più tardi. Il modo in cui l'ho trovato è
`sample <pid>`, che ha mostrato il processo fermo dentro una sola `execute`.

## 2026-08-15 (sera) — le comete hanno una numerazione loro

1P/Halley ha `number = 1`, esattamente come (1) Ceres. Al primo import
l'aggancio di ASTORB agli oggetti dell'MPC ha prodotto **461 righe più del
previsto**, cioè quante sono le comete periodiche numerate presenti: la CEU di
Ceres era finita anche su Halley.

Non è stato trovato da un test ma dal **confronto fra un numero atteso e un
numero ottenuto**: 1.556.630 agganci contro i 1.556.169 che l'analisi
preliminare aveva calcolato. Senza quel conto indipendente sarebbe passato.

Da qui una regola: ogni ricerca per numero porta con sé `kind`. E un test di
regressione che importa insieme (1) Ceres e 1P/Halley e verifica che la CEU
finisca su uno solo.

**Corollario dello stesso errore, trovato subito dopo:** il conteggio degli
«asteroidi su orbita cometaria» includeva 740 comete. Un oggetto con Tj < 3 che
*è già* una cometa non è un asteroide su orbita cometaria: è una cometa.

## 2026-08-15 (sera) — i numeri del primo import vero

Su Mac mini, dai file interi, con `nice 10`:

```
MPCORB extended   1.556.465 oggetti importati, 0 scartati      84 s
CometEls                954 comete                             < 1 s
ASTORB            1.556.977 letti, 1.556.169 agganciati        15 s
                        808 senza corrispondenza
```

Gli 808 senza corrispondenza sono **esattamente** quelli che l'analisi
preliminare aveva contato confrontando le chiavi dei due file, il che conferma
che l'aggancio non perde nulla per strada.

Il database occupa **1,0 GB**. È più di quanto stimato (~600 MB) e va tenuto
d'occhio quando arriveranno `screening_track` e le finestre: se diventa un
problema, la prima cosa da tagliare sono gli oggetti che non serviranno mai —
non le colonne.

Tempo totale di un aggiornamento completo: **circa 100 secondi di CPU**, più lo
scaricamento. Girando una volta al giorno con download condizionato all'ETag,
è un costo che la macchina non sente.

## 2026-08-15 (sera) — lo stato si legge dai dati, non dal registro degli scaricamenti

La pagina Catalogo diceva «mai importato» per MPCORB e ASTORB mentre il
database ne conteneva un milione e mezzo di righe. Il motivo: leggeva
`catalog_version`, che registra gli **scaricamenti**, e quei due erano stati
importati da file locale con `--file`.

Non è un difetto di visualizzazione ma di modello. `catalog_version` risponde a
«da dove è arrivato e quando l'abbiamo preso»; la domanda che si fa chi apre la
pagina è un'altra — «i dati ci sono, e di quando sono?» — e a quella rispondono
solo i dati. Un database ripristinato da backup avrebbe avuto lo stesso
problema, e in un caso ben peggiore: si guarda la pagina proprio quando si
vuole essere sicuri di aver recuperato tutto.

Quindi `source_status()` restituisce le due cose separate, e **il badge di
freschezza segue i dati**. Regola generale che ne discende: *lo stato di una
cosa si deriva dalla cosa, non dal registro di come ci è arrivata.*

Costo: un `GROUP BY source` su `orbit`, che a 1,5 milioni di righe sono 1,5
secondi a ogni caricamento di pagina — inaccettabile per un'intestazione.
Risolto con l'indice composito `(source, updated_at)`: 0,1 s. È la seconda
volta in un'ora che la risposta è un indice composito invece di uno semplice.

## 2026-08-15 (sera) — il pianificatore: si controlla spesso, non a orario fisso

APScheduler dentro il processo dell'app, come già deciso. Quattro scelte sopra
quella:

**Controllo ogni 6 ore invece che a un orario preciso.** Le sorgenti si
aggiornano una volta al giorno ma a orari che si spostano: la documentazione di
Lowell dice «gli aggiornamenti cominciano alle 08:00 UT e finiscono di solito
per le 10:00 — *nella data di Luna piena non prima delle 14:00*». Inseguire quel
calendario è un bug che aspetta di succedere, e il modo in cui fallisce è
silenzioso: si resta indietro di un giorno senza nessun errore. Siccome il
download è condizionato all'ETag, un controllo a vuoto costa una richiesta e
poche centinaia di byte: **si controlla spesso e si scarica quando serve**.
Quattro controlli al giorno per sorgente sono un carico trascurabile per l'MPC.

**Un solo lavoro pesante alla volta, in un processo separato**
(`ProcessPoolExecutor` con un posto). In un thread terrebbero il GIL e
l'interfaccia diventerebbe melmosa proprio mentre il catalogo si aggiorna.

**Recupero all'avvio.** APScheduler da solo si limita a saltare le esecuzioni
mancate mentre la macchina era spenta. All'accensione si guarda l'età dei
*dati* e, se superano le 12 ore, si parte subito — sfalsati di un minuto l'uno
dall'altro, perché l'accensione è il momento in cui la macchina ha più da fare.

**I tre sync sono su minuti diversi** (:05, :20, :35). Tre download nello stesso
minuto sono tre download nello stesso minuto, e c'è un test che lo verifica.

**Alternativa scartata:** cron di sistema o LaunchAgent separati per ogni job.
Aprirebbero il database mentre l'app gira: due scrittori su SQLite.

## 2026-08-15 (sera) — il backup serve, ma non ancora, e non di tutto

*(risposta alla domanda «valutare se serve un backup periodico»)*

**Oggi non serve.** Il database sta a 1 GB ed è al 100% rigenerabile: catalogo,
orbite e derivati si riscaricano dall'MPC e da Lowell in 100 secondi di CPU. Le
sei tabelle non rigenerabili sono tutte **vuote**, perché i watcher NEOCP non
esistono ancora e non c'è nessuna osservazione registrata.

**Servirà dal primo giorno di M2**, e in modo non negoziabile: la storia dei
candidati NEOCP non si recupera da nessuna parte, perché l'MPC riscrive la
lista e non conserva niente. Il giorno in cui quel watcher parte, ogni giorno
senza backup è storia a rischio.

Quindi il lavoro è già scritto, perché deve esistere **prima** dei dati che
protegge, e fa una cosa sola: copia le sei tabelle non rigenerabili in un file
SQLite a parte. Oggi pesa qualche kilobyte; anche fra dieci anni starà in pochi
megabyte.

**Alternativa scartata:** `VACUUM INTO` dell'intero database, che è quello che
fa brain42. Lì ha senso — il database di brain42 è piccolo. Qui sarebbe un giga
al giorno per proteggere qualche kilobyte di dati veri, e il resto si riscarica.

Due dettagli che rendono il backup davvero ripristinabile invece che
teoricamente ripristinabile: le clausole `REFERENCES` si tolgono dal DDL
copiato (altrimenti per rileggere il file bisognerebbe prima ricostruire tutto
il catalogo, cioè l'opposto di ciò che serve mentre si recupera), e c'è
`restore_counts()` che riapre il file e conta le righe. **Un backup che non si
è mai provato a leggere non è un backup.**

Il backup *fuori casa* resta un problema dell'host, come in brain42: qui si
produce solo un'istantanea coerente, piccola, che restic/rclone possono
prendere in mano senza fermare il servizio.

## 2026-08-15 (sera) — Docker: no per l'esercizio, sì come Dockerfile

*(risposta alla domanda «valutare di passare a Docker per il ripristino dopo il
riavvio»)*

Il bisogno dichiarato è **ripartire dopo un riavvio e dopo un crash**. Docker lo
risolve con `restart: unless-stopped`; macOS lo risolve nativamente con launchd
(`RunAtLoad` + `KeepAlive`). A parità di risultato decidono due differenze:

1. **Docker Desktop su macOS ha bisogno di una sessione utente attiva.** È
   un'applicazione: se il Mac mini si riavvia e nessuno fa login, il demone non
   parte e con lui non parte sky42 — cioè fallisce esattamente nello scenario
   per cui lo si stava adottando. Un LaunchDaemon parte prima del login.
2. **SQLite attraverso un bind mount vive dentro una VM.** Il locking di SQLite
   su filesystem virtualizzati è il caso che la documentazione di SQLite dice
   di evitare. brain42 se lo può permettere perché lì la verità sono i file
   Markdown e il database è un indice rigenerabile; **in sky42 le sei tabelle
   che non si riscaricano vivono dentro SQLite**, ed è il posto sbagliato dove
   correre un rischio di locking.

Quindi: **launchd per l'esercizio**, `Dockerfile` mantenuto per riproducibilità
e per poter spostare il servizio altrove.

Se un giorno si volesse comunque Docker per uniformità con brain42 e stock42,
la condizione è una sola: **il database in un volume nominato, non in un bind
mount**, così non attraversa il confine della VM. In quel caso il backup deve
saper uscire dal volume.

**Alternativa scartata:** Docker subito, per avere tre progetti uguali. La
coerenza fra progetti è un valore, ma non vale il caso in cui il servizio non
riparte proprio dopo il riavvio.

## 2026-08-15 (sera) — Tailscale: ci si lega all'indirizzo della tailnet, non a 0.0.0.0

*(risposta alla domanda «accesso via Tailscale da altre macchine»)*

sky42 ascolta su `127.0.0.1` e **non ha autenticazione**. La via breve per
raggiungerlo da un'altra macchina sarebbe `SKY42_HOST=0.0.0.0`, che però lo
espone anche a tutta la rete locale — a chiunque sia sul Wi-Fi di casa, ospiti
compresi.

La forma giusta è legarsi all'**indirizzo Tailscale della macchina**
(`SKY42_HOST=100.x.y.z`): il servizio esiste solo per i peer della tailnet, e
sulla LAN la porta non c'è proprio. `SKY42_HOST` è già una variabile
d'ambiente, quindi non serve codice.

Un vincolo che ne discende, e va scritto perché è il modo in cui si rompe: quel
indirizzo esiste solo dopo che `tailscaled` è partito. Se sky42 parte prima, il
bind fallisce. Con launchd `KeepAlive` riprova da solo; con Docker servirebbe
un `depends_on` che su macOS non esiste.

E la regola di brain42 vale identica: **il giorno in cui si usa
`tailscale funnel` — cioè si esce su Internet — l'autenticazione arriva prima,
non dopo.** Dentro la tailnet si può stare senza.

## 2026-08-15 (sera) — le date non si confrontano come stringhe

`close_orphaned_jobs` non chiudeva niente, e la query sembrava giusta:

```sql
WHERE status='running' AND started_at < datetime('now', '-6 hours')
```

I nostri timestamp sono `2026-08-15T07:46:00Z`; `datetime('now', ...)` produce
`2026-08-15 10:46:52`. Confrontati come testo, il carattere alla posizione 10 è
`'T'` contro `' '`, e `'T'` viene **dopo** lo spazio: **nessuna riga dello
stesso giorno risulta mai più vecchia della soglia.** Nessun errore, nessun
avviso, solo una query che non seleziona mai niente.

Corretto con `julianday(started_at) < julianday('now') - ore/24`, che interpreta
entrambi i formati. Lo stesso difetto era in tre query di `maintenance_service`,
dove si vedeva meno perché con 90 giorni di distanza cambia la parte della data.

**La parte che conta è perché il test non l'aveva preso.** Il test inseriva la
riga finta con `datetime('now','-9 hours')` — cioè nel formato di SQLite,
diverso da quello che l'applicazione scrive davvero. Il test verificava una
combinazione che in produzione non esiste.

Regola: **i dati finti dei test si scrivono nello stesso formato in cui li
scrive l'applicazione.** Se un test costruisce i dati in un modo suo, verifica
il codice contro un mondo che non c'è.

## 2026-08-15 (notte) — Docker sì: le due obiezioni non reggevano ai fatti

**Annulla la decisione «Docker: no per l'esercizio» presa un'ora prima.**

Avevo raccomandato launchd su due argomenti. Messi alla prova su *questa*
macchina, invece che in astratto:

1. «Docker Desktop pretende una sessione utente, quindi dopo un riavvio senza
   login il servizio non parte.» — `AutoStart: True` nelle impostazioni di
   Docker Desktop, e soprattutto **brain42 e stock42 ripartono già da soli su
   questa macchina**. L'obiezione descriveva una configurazione che qui non
   c'è.
2. «SQLite su un bind mount vive dentro una VM e il locking è rischioso.» —
   Docker Desktop 29.7.2 con kernel 6.12: VirtioFS, non il vecchio osxfs di
   cui parlavano gli avvisi che avevo in mente. E brain42 tiene un database
   SQLite su un bind mount ventiquattr'ore su ventiquattro, senza incidenti.

Due servizi che funzionano davvero battono un rischio teorico. In più avevo
sottopesato un valore concreto: **tre progetti con la stessa forma** —
`docker compose up -d --build`, stessa struttura di `docker-compose.yml`, stesso
posto dove guardare quando qualcosa non va alle sette di sera — vale più della
differenza fra due modi entrambi funzionanti di far ripartire un processo.

Lezione sul metodo, che è la parte che serve conservare: avevo costruito
l'argomento da principi generali senza controllare la macchina di cui si
parlava. La documentazione di SQLite sui filesystem di rete è giusta *in
generale*; il fatto che qui accanto giri già la stessa combinazione era
un'evidenza più forte, e stava a un comando di distanza.

**Cosa sopravvive della preoccupazione, ed è specifico di sky42.** brain42 non
ha una riga di comando che scriva sul database; sky42 sì (`cli.py`). Host e
container che scrivono insieme sullo stesso file SQLite attraverso un bind
mount è un caso diverso e davvero pericoloso: in WAL il coordinamento fra
scrittori passa da un file di memoria condivisa che **non attraversa il
confine della VM**. Quindi la regola, scritta in `docker-compose.yml` accanto
al volume:

```
docker compose exec sky42 python cli.py ingest all      # sì
.venv/bin/python cli.py ingest all                      # solo a servizio fermo
```

**Una cosa la cambio comunque rispetto a brain42:** la porta si pubblica su un
indirizzo esplicito, `${SKY42_BIND_IP:-127.0.0.1}:8242:8000`. Pubblicare senza
indirizzo lega la porta a tutte le interfacce, e sky42 non ha autenticazione:
mettendo l'indirizzo Tailscale in `.env` il servizio esiste per la tailnet e
non per il Wi-Fi di casa. Costa una variabile e toglie un'esposizione che non
serve a nessuno.

Il LaunchAgent resta in `scripts/` come alternativa documentata, per il giorno
in cui Docker desse fastidio.

---

## 2026-08-16 — il solutore: un ramo solo non basta, e la soglia è 0.98

`core/orbits/kepler.py` ha **due rami, scelti sull'eccentricità e non sul tipo
di oggetto**. Sotto e = 0.98 si risolve M = E − e sin E con Newton vettoriale;
sopra — e per tutte le paraboliche e iperboliche — si passa alle variabili
universali di Stumpff, che non usano `a` né M ma solo `q` e `tp` e propagano
dal perielio con le f e g. Il criterio è quello di `docs/modelli.md`: un
asteroide con e = 0.99 ha lo stesso problema numerico di una cometa, e
scegliere il ramo su `kind` invece che su `e` significherebbe mandare
l'asteroide nel ramo che non tiene.

**L'alternativa scartata è il ramo unico universale.** Sarebbe stato meno
codice, e sulla carta è sufficiente per tutte le coniche. Costa però una
radice da cercare numericamente anche per la fascia principale, dove Newton su
E converge in 4-5 iterazioni da un innesco eccellente: sui 14.000 oggetti dello
screening × 730 epoche, cioè dieci milioni di stati, la differenza non è
estetica. I due rami sono tenuti onesti da un test che alza artificialmente la
soglia a 0 e verifica che diano lo stesso punto entro 1e-10 AU.

**Newton universale è incastrato in un intervallo.** F(x) = q x + e x³ S(αx²)
è dispari e strettamente crescente (dF/dx = r > 0), quindi si parte da un
intervallo trovato per raddoppio e ogni passo di Newton che ne esce viene
sostituito da una bisezione. Newton nudo, su 'Oumuamua a sette anni dal
perielio, scappa. Con la rete la convergenza è garantita e non c'è nessun caso
patologico da temere quando arriverà l'oggetto che non abbiamo previsto.
L'innesco è la soluzione esatta del caso parabolico (una cubica in forma
chiusa): per le quasi-paraboliche è già quasi la risposta.

**Le funzioni di Stumpff si sviluppano in serie fino a z⁴, non a z³.** Sotto
|z| = 0.1 la forma chiusa (1 − cos√z)/z si annulla per cancellazione e si passa
alla serie; con i termini fino a z³ il raccordo fra i due rami ha un gradino di
**2,8e-11**, misurato, che con il termine in z⁴ scende a **2,1e-14**, cioè
sparisce nell'aritmetica in doppia precisione. Un termine in più costa una
moltiplicazione e toglie una discontinuità dalla propagazione delle comete, che
è esattamente il posto dove i gradini si notano.

**La verità è presa da Horizons a elementi osculatori.** Il test scarica —
una volta, e i numeri sono costanti nel file di test con la data — elementi e
vettore di stato **alla stessa epoca**, per quattro oggetti che coprono i due
rami e le tre coniche: Cerere (e = 0.079), Faetonte (0.890), C/2023 A3
(1.000110), 1I/'Oumuamua (1.204). Alla loro epoca gli elementi osculatori
*definiscono* lo stato, quindi il confronto misura il solutore e non le
perturbazioni: la tolleranza dichiarata è **1e-8 AU** all'epoca (≈ 1,5 km, il
livello a cui Horizons arrotonda gli elementi che pubblica) e **1e-6 AU** dopo
un giorno di propagazione, dove le perturbazioni vere cominciano a entrare.
Quanto sbagli la propagazione a due mesi o due anni resta la domanda aperta
n. 2 e si risponde con un lavoro di validazione, non con un test unitario:
confonderle avrebbe prodotto un test che fallisce quando cambia la fisica
invece di quando si rompe il codice.

**Misura di costo, che chiude a metà la domanda aperta n. 3:** 14.000 orbite ×
730 epoche giornaliere = 10,2 milioni di stati in **2,4 s** sul portatile, un
core solo (`OMP_NUM_THREADS=1`). La propagazione non è il collo di bottiglia
dello screening. Attenzione però alla **memoria**: quella griglia in una volta
sola sono ~490 MB fra posizioni e velocità, quindi lo screening dovrà lavorare
a blocchi di oggetti — non per velocità, ma perché il Mac mini fa girare altro.

---

## 2026-08-16 — il reconcile dei siti: verifica tutto, poi scrive, e non cancella

`core/sites/reconcile.py` porta `config/sites/*.yml` nelle quattro tabelle
dell'hardware. Tre scelte, tutte pagate da qualcosa che sarebbe andato storto.

**Si verificano tutti i file prima di scriverne uno.** Il reconcile legge e
valida l'intera cartella, e solo dopo apre una transazione. L'alternativa —
validare e scrivere file per file — sembra più semplice finché il secondo file
è rotto: allora il database resta con metà configurazione nuova e metà vecchia,
e non c'è nessun errore che lo dica dopo. Un test lo fissa: con un file
invalido nella cartella, `observatory` resta vuota.

**Si scrive solo ciò che è davvero cambiato.** Un `UPDATE ... WHERE code=?`
incondizionato riesce sempre, e il rendiconto direbbe «4 aggiornati» a ogni
giro anche senza che nessuno abbia toccato un file. Siccome il reconcile gira
**a ogni avvio** — i file sono la fonte di verità e un `git pull` non deve
dipendere da qualcuno che si ricorda di premere un pulsante — un rendiconto che
grida sempre non lo legge più nessuno. Ora il secondo reconcile di fila
restituisce tre liste vuote, e il confronto sui reali è tollerante (1e-12
relativo) perché un float riletto da SQLite dev'essere lo stesso numero.

**Chi sparisce dallo YAML viene disattivato, mai cancellato** (regola 3), e
`valid_to` si scrive **solo se è vuoto** (`COALESCE`): la data di dismissione è
quella della prima volta che ce ne siamo accorti, non quella dell'ultimo
riavvio. Senza il `COALESCE` ogni reconcile la sposterebbe a oggi, e fra due
anni «da quando quel setup non è più in uso» risponderebbe «da stamattina».
Il test verifica anche che l'`id` non cambi: `observation_log` punta lì.

**Un campo sconosciuto è un errore, non un campo ignorato.** `latitide: -30.47`
con l'YAML permissivo diventa un osservatorio all'equatore con `latitude` a
zero — cioè notti calcolate per il posto sbagliato, senza nessun errore da
nessuna parte. La validazione è una tabella dichiarativa per entità (nome,
tipo, default) e rifiuta ciò che non riconosce, come già fatto per il formato
FORTRAN di ASTORB: un posto solo da guardare quando il formato cambia.

**Il file non sovrascrive le misure.** Se un setup ha righe in
`setup_calibration`, il reconcile lascia il `vlim_ref` che c'è nel database e
lo dichiara nel rendiconto. `vlim_ref` nello YAML è una stima iniziale; la
calibrazione è il punto in cui il sistema smette di indovinare, e riportarla
indietro al primo `git pull` sarebbe buttare via una notte di lavoro.

**Un errore di configurazione non impedisce l'avvio.** Viene registrato nel log
e nella riga di `job_run`, e la pagina Osservatori lo mostra. Un servizio che
si rifiuta di partire per un campo storto, alle tre di notte, non risponde
nemmeno per dirti cos'ha.

**Scala e campo restano derivati, e la pagina li mostra accanto ai loro
ingredienti.** `pixel_scale = 206.265 · pixel_um · bin / (focale · riduttore)`,
`fov = scala · (pixel / bin) / 60`. Il binning compare due volte perché fa due
cose opposte — allarga il pixel e ne riduce il numero — e infatti il campo non
cambia: c'è un test apposta, perché è l'errore che si fa scrivendo la formula a
memoria. Verifica indipendente sul setup reale: 36,0 mm di sensore su 4540 mm
di focale sono 36/4540 rad = 27,3′, e il modulo dà 27,27′ × 18,19′ con
0,342″/px in bin 2.

---

## 2026-08-16 — il positioner: astrometrico, e con due convenzioni da non confondere

`core/orbits/positioner.py` è il contratto: `positions(body, jd)` restituisce
RA, Dec, Δ, r, V, elongazione, fase e moto, e chi sta a valle non sa quale
modello li ha prodotti. Sotto ci sono `core/ephemeris.py` (l'unico
modulo che apre DE440s) e `core/orbits/photometry.py`.

**Si restituisce la posizione astrometrica, non quella apparente.** Corretta
per tempo luce, senza aberrazione annua né rifrazione: è la quantità 1 di
Horizons ed è la convenzione dell'astrometria MPC. L'aberrazione (fino a 20″)
serve a puntare, e puntare non è il compito di sky42: per quello si passa da
Horizons sulla shortlist. Conseguenza misurata: i *tassi* di Horizons sono del
posto apparente e differiscono dai nostri di ~0.1″/ora — 0.002″ su una posa da
120 s, cioè niente per il trailing, che è l'unica cosa per cui il moto serve.
La tolleranza del test sul moto è 0.2″/ora **per questa ragione**, non per
debolezza del calcolo.

**Il moto si calcola per differenze finite su ±30 minuti**, dalla stessa
funzione di posizione (docs/modelli.md §3). Costa due valutazioni in più, e in
cambio vale identico per asteroidi, comete, iperboliche e per qualunque
positioner futuro: nessuno dovrà derivare a mano una nuova espressione il
giorno che cambia il modello. Con `with_motion=False` lo screening può
saltarlo dove non serve.

**Una sola iterazione di tempo luce.** Il residuo è sotto 0.1″ per Δ < 5 AU e
la correzione è quadratica nel piccolo spostamento. Misurato su Faetonte:
togliere del tutto il tempo luce sposta la posizione di **1.93″**, cioè quaranta
volte la tolleranza del test — c'è un test apposta perché fra un anno sembrerà
un dettaglio eliminabile.

**`k1` è due parametri diversi con lo stesso nome, e vale 2.5 magnitudini.**
MPC pubblica in CometEls il *k* (nei nostri dati va da 2 a 16, media 4.3); JPL
pubblica il coefficiente già moltiplicato per 2.5. La formula qui è
`m1 = M1 + 5log₁₀Δ + 2.5·k1·log₁₀r` con il k1 **dell'MPC**, che è quello che
sta in `orbit.k1`. Verificato su C/2023 A3: con i parametri di JPL (M1 = 8.9,
k1 = 5.5) e la conversione ÷2.5 la nostra formula dà 12.714 contro i 12.714 di
Horizons; senza conversione sbaglierebbe di 2.4 mag. Il test tiene ferma la
conversione proprio perché è il genere di «semplificazione» che sembra
innocua.

**DE440s passa da `core/ingest/http.py` come ogni altro dato esterno**, con
ETag, scrittura atomica e riga in `external_call`. Skyfield saprebbe scaricarlo
da sé, ma allora l'unico modulo che parla con l'esterno non sarebbe più uno
solo, e «quale kernel stiamo usando» non avrebbe una risposta nel database.
Sta in `data/ephem/`, ha una variabile d'ambiente sua (`SKY42_EPHEM_DIR`)
perché è **l'unico dato scaricato che i test riusano**: 32 MB immutabili e
uguali per tutti, che non ha senso riscaricare per ogni cartella temporanea.

**Residui misurati contro Horizons** (elementi osculatori e effemeride alla
stessa epoca, `TIME_TYPE=TT`, tre oggetti sui due rami del solutore):

| | Cerere | Faetonte | C/2023 A3 |
|---|---|---|---|
| posizione | 0.004″ | 0.008″ | 0.008″ |
| r, Δ | 1.6e-7 AU | 1.6e-8 AU | 8.7e-8 AU |
| V | 0.000 | 0.000 | 0.000 |
| elongazione, fase | < 0.008° | < 0.008° | < 0.004° |

La tolleranza dichiarata in posizione è 0.05″ e non 0.01″ per una ragione
precisa: i nostri elementi sono eclittici J2000, DE440s è ICRF, e fra i due c'è
il *frame bias* (~0.02″). Correggerlo sarebbe una rotazione in più per una
quantità che sta due ordini di grandezza sotto la CEU degli oggetti che ci
interessano.

---

## 2026-08-16 — i nostri JD erano UTC, gli elementi sono TT: 69 secondi

Trovato provando il positioner sul catalogo vero: `timeutil.now_jd()`
restituiva un JD sulla scala **UTC**, mentre le epoche di MPCORB e ASTORB — e
tutto il calcolo orbitale — stanno in TT/TDB. Fra le due ci sono
**69.184 secondi** (32.184 + 37 secondi intercalari), e nessuno se ne accorgeva
perché il numero è lo stesso a meno di 8e-4 giorni.

Quanto costa: su Faetonte in avvicinamento, che si muove a 4″/minuto, sono
**4.6 arcosecondi** — cento volte la tolleranza con cui abbiamo appena
verificato il positioner contro Horizons, e abbastanza da mancare un oggetto in
un campo stretto. Sulla fascia principale (0.5″/minuto) sarebbero 0.6″:
invisibile, che è esattamente il modo in cui questi errori sopravvivono.

Ora `timeutil` espone `now_jd_tdb()`, `jd_tdb_from_utc()` e `jd_utc_from_tdb()`,
e la conversione avviene **solo lì** (è già la regola per quel modulo). Le
griglie di calcolo sono in TDB, le etichette in interfaccia tornano in UTC.

La costante è scritta a mano e non presa da una libreria: `timeutil` non deve
dipendere da un pacchetto di effemeridi per dire che ora è. Il rischio — un
secondo intercalare annunciato dall'IERS e nessuno che se ne accorge — è coperto
da un test che confronta la costante con la tabella di Skyfield, che in casa c'è
già. Se cambia, il test lo dice.

**TDB − TT** oscilla di ±1.7 ms e resta ignorato di proposito: un JD moderno ha
~20 µs di risoluzione in doppia precisione, quindi inseguire i millisecondi
significherebbe misurare il float e non il cielo.

**Verifica di tutta la catena, sul catalogo vero** (ingest MPCORB → orbita →
positioner), (3200) Faetonte oggi contro Horizons, con elementi di epoca
2026-06: **0.30″** in posizione, 8e-6 AU in Δ, 0.000 mag in V. È anche il primo
dato della domanda aperta n. 2: due mesi di propagazione a due corpi su un NEO
costano tre decimi di arcosecondo.

---

## 2026-08-16 — la notte comincia a mezzogiorno, e le eccezioni sono risposte

`core/visibility/night.py` è il primo pezzo del visibility engine: crepuscoli,
Luna e ore di buio per (sito × notte). Anche `core/ephemeris.py` si è spostato
qui accanto — stava in `core/orbits/` ed era il posto sbagliato: lo usano il
positioner **e** il visibility engine, e lasciarlo sotto `orbits/` avrebbe
costretto `visibility/` a importare da lì, rompendo la regola 4 il primo
giorno. Sbagliato di una cartella, corretto prima che ci si appoggiasse
qualcosa.

**Una notte è ancorata al mezzogiorno locale**, non alla mezzanotte UTC. «La
notte del 15» comincia la sera del 15 anche se il grosso del buio cade il 16, e
la finestra di ricerca va da mezzogiorno a mezzogiorno. Con l'ancoraggio a
mezzanotte UTC, a Río Hurtado (UTC−4) il tramonto della notte del 15 cadrebbe
il 16 e l'ordine degli eventi si invertirebbe. C'è un test che verifica
soltanto che gli eventi siano in ordine crescente: sembra una banalità, ed è la
sentinella di questo errore.

**Gli eventi si distinguono dal verso, non dall'ora.** `find_discrete` dà gli
istanti in cui si entra in una fase, e ogni fase si attraversa due volte —
scendendo verso il buio e risalendo. Discriminarle confrontandole con la
mezzanotte funzionerebbe a Roma e fallirebbe esattamente nei casi estremi per
cui serve del codice: si guarda invece se la fase precedente era più chiara o
più scura.

**Il Sole che non tramonta è una risposta.** A Tromsø il 21 giugno non c'è
tramonto e le ore di buio sono zero; il 21 dicembre non c'è alba, ma il
crepuscolo astronomico finisce e comincia lo stesso, e le ore di buio sono
13.5. I campi mancanti restano `None` e non zero: uno zero non si distingue da
un calcolo andato male, un `None` sì. Le ore di buio quando mancano entrambe le
transizioni si decidono guardando che fase è a metà finestra — zero d'estate,
ventiquattro d'inverno polare.

**`moon_max_alt_deg` si campiona fra tramonto e alba**, non su tutta la
finestra. Nella notte del 2026-08-16 la Luna culmina a 69° — a mezzogiorno.
Registrare quel numero significherebbe scartare una notte che era buia: quello
che serve non è l'altezza massima della Luna, è quanto ha disturbato.

**La frazione illuminata è topocentrica.** La parallasse lunare arriva a 1° e
sposta la frazione di ~0.007 rispetto al valore geocentrico: irrilevante per
una brillanza di cielo, decisivo per poter *confrontare* il nostro numero con
Horizons (0.21236 contro 0.2124259). Un numero che non si può confrontare non
si può verificare.

**Verifica contro Horizons** (`CENTER='coord@399'` con le coordinate del sito,
elevazione **airless** come Skyfield, che non applica rifrazione): agli istanti
che chiamiamo tramonto e crepuscoli astronomici, Horizons dà −0.833132,
−17.999720 e −18.000184. Scarto massimo **0.0003°**, che a Río Hurtado — dove
il Sole scende di 0.2°/minuto — sono **0.1 secondi** di tempo. Per la Luna al
tramonto: −0.79977 contro il nostro −0.8. La tolleranza dichiarata nei test è
0.002°, sei volte il residuo misurato.

Il job `night_plan` gira **ogni sei ore** e non una volta al giorno: costa
millisecondi, e così la finestra di due settimane resta piena anche dopo un
giorno di spegnimento. Ha portato con sé una piccola aggiunta al pianificatore:
`JobSpec.freshness`, perché il recupero all'avvio finora misurava l'età dei
*dati scaricati* — che vale per i sync e per nessun altro. `night_plan` non ha
una sorgente: ha una tabella che riempie, e la sua freschezza è l'età di quella.

---

## Domande aperte

Si chiudono con numeri misurati, non con previsioni.

1. ~~**Quanti oggetti hanno davvero Tj < 3?**~~ **Chiusa il 2026-08-15:**
   33.394 su 1.556.977 (2,1%), che scendono a **13.945** togliendo Troiani,
   Hilda e oggetti distanti (voce sopra). Con H < 18 restano 29.098 prima
   dell'esclusione. Sono migliaia, non centinaia di migliaia: lo screening può
   permettersi una griglia fitta e due giri al giorno.
2. **Quanto sbaglia davvero la propagazione a due corpi?** **Primo dato,
   2026-08-16:** (3200) Faetonte, elementi MPCORB di epoca 2026-06 propagati a
   oggi (~2 mesi), contro Horizons: **0.30″** in posizione e **0.000 mag** in V.
   Un punto solo non è una risposta — serve il campione stratificato qui sotto —
   ma dice che l'ordine di grandezza è quello sperato. Residui contro
   Horizons a 1, 6, 12, 24 mesi, in posizione e in magnitudine, su un campione
   di 50 oggetti stratificato per classe orbitale. Se in magnitudine si resta
   sotto 0.3 mag, l'architettura regge come progettata; sopra, va rivista.
3. **Quanto ci mette lo screening completo sul Mac mini?** Se è sotto i cinque
   minuti si può rifare ogni giorno su tutto; se è un'ora, va diviso in una
   popolazione monitorata e un giro completo settimanale. **Metà risposta il
   2026-08-16:** la sola propagazione dei 14.000 su 730 epoche costa 2,4 s
   (voce sopra). Manca il resto della catena — Terra da Skyfield, tempo luce,
   fotometria, finestre — che è dove il tempo andrà davvero.
4. **Il coefficiente 0.55 mag/grado del crepuscolo.** Va misurato con
   `setup_calibration` e sostituito. Oggi è una stima.
5. **`vlim_ref` dichiarato contro misurato.** Di quanto sbaglia la stima
   iniziale su ciascun setup? È la taratura che rende sensato tutto il resto,
   perché ogni soglia del radar ci si appoggia.
6. **Tj < 3.0 o < 3.05?** Misurato il 2026-08-15: la soglia larga porta da
   33.394 a **54.651** oggetti, cioè **+64%** — molto più di quanto suggerisca
   un ritocco di 0.05. Resta aperto se quei 21.257 in più contengano qualcosa
   di interessante o solo coda della fascia principale: si risponde
   incrociandoli con la classe orbitale, come fatto per la soglia stretta.
7. **Quante transizioni di stato al giorno?** Decide se le notifiche sono un
   messaggio o un digest, e se l'isteresi a 0.15 mag è abbastanza.
8. **Ogni quanto cambia davvero `astorb.dat`?** Il download è condizionale su
   ETag; se il file cambia ogni giorno ma le orbite che ci interessano no,
   conviene un import differenziale (`.add`/`.del`) invece di un rifacimento.
   Con i controlli ogni 6 ore la risposta arriva da sola: basta contare i 304
   in `external_call` contro gli import in `job_run` dopo una settimana.
9. **Serve un guardiano per il container piantato?** `restart: unless-stopped`
   copre il processo che *muore*; **Docker non riavvia un container
   `unhealthy`**, quindi un processo che si pianta resta lì finché qualcuno
   guarda. Si risolve con poche righe (una sonda che esce quando `/health` non
   risponde), ma prima serve sapere se succede mai: la risposta è in quante
   volte, in un mese, `docker compose ps` mostra `unhealthy`.
