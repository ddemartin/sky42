# IDEA — sky42

Documento di partenza, 15 agosto 2026. Non si aggiorna nei contenuti: vale come
tale anche dove l'implementazione se ne discosterà. Gli scostamenti si
registrano in [MEMORANDUM.md](MEMORANDUM.md), non correggendo qui.

---

## Obiettivo generale

Applicazione web locale, eseguita 24/7 su Mac mini, dedicata al monitoraggio
osservativo di asteroidi e comete.

Deve funzionare come una **console personale di follow-up del Sistema Solare**,
capace di scaricare e mantenere aggiornati i dati orbitali, fare gran parte dei
calcoli localmente, monitorare nuovi candidati MPC e indicare automaticamente
**quali oggetti vale la pena osservare, da quale osservatorio remoto e in quale
finestra temporale**.

Interesse principale:

- astrometria e imaging di nuovi asteroidi;
- asteroidi su orbite cometarie, soprattutto con Tisserand rispetto a Giove Tj < 3;
- oggetti che tornano osservabili dopo mesi o anni fuori dalla portata degli strumenti;
- nuovi candidati MPC / NEOCP;
- candidati cometari / PCCP;
- comete note che stanno entrando in una buona finestra osservativa.

I telescopi utilizzati raggiungono tipicamente circa **V 20.5–21**, ma ogni
osservatorio e strumento ha caratteristiche differenti.

## Filosofia dell'architettura

Evitare migliaia di chiamate alle API JPL. Usare invece un catalogo orbitale
locale, idealmente **ASTORB.dat**, aggiornato periodicamente e importato in un
database locale.

```text
ASTORB / MPC
    ↓
database locale
    ↓
calcoli orbitali preliminari locali
    ↓
filtri scientifici e osservativi
    ↓
shortlist di oggetti interessanti
    ↓
eventuale interrogazione JPL Horizons/SBDB
solo per verifica o effemeridi finali
```

Il Mac mini può usare i tempi morti per precomputare osservabilità e finestre
future.

## Catalogo degli asteroidi

Database locale con almeno: designazione, numero, epoch, a, e, i, Ω, ω, M, H,
G quando disponibile, classe orbitale, data della soluzione, informazioni
sull'incertezza, data ultima osservazione, eventuali informazioni MPC
aggiuntive.

Calcolare localmente il Tisserand rispetto a Giove:

```text
Tj = aJ/a + 2 cos(i) sqrt[(a/aJ)(1-e²)]
```

Creare una popolazione privilegiata con Tj < 3.0, con possibilità di soglia
leggermente più larga (3.05).

## Returning-object radar

Una delle funzioni principali. Individuare automaticamente gli oggetti che:

- sono stati per lungo tempo più deboli del limite osservativo;
- stanno tornando sotto V≈21;
- hanno una buona geometria osservativa;
- sono interessanti per orbita, scarsità di osservazioni o natura comet-like.

Non solo «quali oggetti sono osservabili stasera?», ma soprattutto **quali
oggetti stanno rientrando nella mia portata** dopo essere stati fuori portata
per mesi o anni.

Stati: `OUT_OF_RANGE`, `APPROACHING`, `CROSSES_LIMIT`, `OBSERVABLE`, `PRIME`,
`FADING`. Registrare le transizioni.

Per ogni oggetto: `next_v21_date`, `next_v205_date`, `visibility_start`,
`visibility_end`, `peak_date`, `peak_magnitude`, `last_good_apparition`,
`time_since_last_good_apparition`.

Esempio di ciò che il sistema dovrebbe mostrare:

```text
2020 AB123
Tj = 2.63
ultima buona finestra: 2018
oggi V = 21.8
entra sotto V=21: 17 settembre
migliore magnitudine prevista: 19.7
```

## Precomputazione

Per gli oggetti interessanti, propagazione preliminare locale per i prossimi
12–24 mesi. La precisione non deve inizialmente essere quella di Horizons: lo
scopo è fare screening. È sufficiente distinguere bene V 19.5 da V 21 da V 24.
Modello fotometrico H-G o equivalente. Solo dopo lo screening interrogare
eventualmente Horizons per la shortlist.

## Nuovi candidati MPC

Watcher periodici per MPC NEOCP, MPC PCCP, Recent MPEC. Poll ogni 10–30 minuti
a seconda della fonte. Salvare ogni candidato in un database locale, inclusa la
sua evoluzione nel tempo: temporary designation, RA/Dec, magnitudine, motion,
arco osservativo, numero di osservazioni, eventuale soluzione orbitale
preliminare, incertezza, stato MPC, timestamp di prima e ultima apparizione
nella lista.

Seguire anche il destino del candidato — confermato, identificato con un
oggetto noto, confermato cometa, rimosso per osservazioni insufficienti — e
conservare la storia.

## Comete e candidati cometari

Radar dedicato a PCCP, nuove comete, comete periodiche, comete che emergono
dalla congiunzione solare, comete che si avvicinano al perielio, oggetti che
migliorano rapidamente di osservabilità.

Per le comete usare Horizons soprattutto per geometria ed effemeridi, senza
assumere che la magnitudine prevista sia precisa.

Visualizzare almeno: r, Delta, elongazione solare, altezza, trend geometrico,
perielio, finestra osservativa, magnitudine prevista/stimata.

## Osservatori multipli

Osservo da più osservatori remoti in località differenti: Cile, Namibia, Spagna
e potenzialmente altri. L'osservabilità è quindi una proprietà della coppia
`object + observing setup`, non del solo oggetto.

Ogni osservatorio ha un profilo configurabile: `name`, `latitude`, `longitude`,
`altitude`, `timezone`.

Ogni strumento: `telescope`, `aperture`, `camera`, `field_of_view_x`,
`field_of_view_y`, `pixel_scale`, `nominal_limiting_mag`,
`astrometric_limiting_mag`, `typical_exposure`, `minimum_altitude`,
`maximum_airmass`, `typical_seeing`, limitazioni di tracking/moto, twilight
limit.

Un osservatorio può avere più strumenti.

## Visibility engine

Per ogni `object × observatory × time`: RA/Dec, altezza, azimut, airmass,
rise/set, transito al meridiano, durata della finestra utile, elongazione
solare, altezza del Sole, crepuscolo, magnitudine prevista, motion, posizione
della Luna, fase, frazione illuminata, altezza della Luna, distanza angolare
Luna-target, eventualmente sky brightness stimata.

Il sistema deve confrontare automaticamente i vari osservatori:

```text
2026 XX

Chile     PRIME       V 20.1   max alt 67°   4.2 h utili
Namibia   POOR        max alt 24°, airmass elevata
Spain     NOT USEFUL  fuori portata / troppo bassa
```

## Disturbo lunare

Parte reale del calcolo, non informazione accessoria. Tenere conto di fase,
percentuale illuminata, altezza della Luna, distanza angolare Luna-target,
airmass della Luna e del target. Idealmente un modello fisico o semi-empirico
della luminosità del cielo dovuta alla Luna.

Una Luna quasi piena sotto l'orizzonte non deve penalizzare. Una Luna quasi
piena alta e vicina al target deve ridurre significativamente la qualità della
finestra.

Calcolare una `effective_limiting_magnitude` derivata dal limite nominale più
penalità per airmass, moonlight, twilight, motion/trailing, altre condizioni:

```text
nominal Vlim         21.2
airmass penalty      -0.15
moon penalty         -0.60
motion penalty       -0.10

effective Vlim       20.35
```

Distinguere chiaramente `GEOMETRICALLY OBSERVABLE` da `ACTUALLY USEFUL`.

## Best observing window

Non assumere che il transito sia il momento migliore. Campionare la notte ogni
5–10 minuti e trovare la finestra che massimizza la qualità osservativa
considerando altezza, airmass, Luna, sky brightness, magnitudine, motion,
oscurità.

La classifica dei siti può cambiare durante la notte: mostrare quindi
`BEST SITE NOW`, `BEST SITE TONIGHT` e il `best observing interval`.

## Moto apparente e trailing

Per nuovi NEO e oggetti veloci calcolare il trailing previsto in funzione di
motion, pixel scale ed esposizione:

```text
motion = 7"/min
exposure = 180 s
trail = 21"
```

Stimare l'esposizione massima consigliata per limitare il trailing. Lo
strumento più grande potrebbe essere favorito perché può usare esposizioni più
corte mantenendo S/N sufficiente.

## Positional uncertainty e FOV

Per nuovi candidati e recuperi confrontare l'incertezza della posizione con il
campo dello strumento:

```text
uncertainty = 18'   FOV = 40' × 40'  → good
uncertainty = 18'   FOV = 12' × 9'   → difficult recovery
```

Inserire questo elemento nello score osservativo. Eventualmente suggerire un
search pattern o mosaico.

## Ranking osservativo

Uno score per ogni coppia oggetto/setup, che combini: interesse scientifico,
Tj, rarità / tempo dall'ultima osservazione, incertezza orbitale, magnitudine
prevista, magnitudine limite efficace, altezza, airmass, durata della finestra
buia, disturbo lunare, motion, incertezza vs FOV.

Non necessariamente una formula sofisticata all'inizio: meglio un modello
trasparente e regolabile.

## Dashboard principale

Una vera decision console. Sezioni: `TONIGHT`, new candidates, comet
candidates, Tj < 3 returns, known comets, recovery targets, objects entering
range.

Ogni target mostra immediatamente il miglior sito:

```text
2020 AB123
Tj 2.63
returning after 7.4 years
V 19.8

BEST SITE: CHILE

Chile      ★★★★★ PRIME
Namibia    ★★★☆☆ POSSIBLE
Spain      —     NOT USEFUL
```

Entrando nell'oggetto: best window, magnitudine prevista, effective Vlim, curva
di altezza, altezza della Luna, separazione, fase, motion, esposizione
consigliata, uncertainty/FOV.

## Asteroidi comet-like

Per gli oggetti con Tj < 3 un ranking specifico per possibili Asteroids in
Cometary Orbits. A parità di altre condizioni privilegiare Tj basso, orbite
dinamicamente comet-like, lunghi periodi dall'ultima osservazione, ritorni
favorevoli, assenza di attività nota, buona geometria, magnitudine alla
portata.

In futuro il sistema potrebbe integrarsi con una pipeline di immagini: plate
solve → identifica target → moving stack → misura PSF → confronta PSF
asteroidale con stelle → radial profile → cerca possibile estensione/coma. Non
necessario per il primo MVP.

## Tecnologie

Soluzione semplice e robusta: Python, backend web leggero, SQLite inizialmente,
Docker, Mac mini always-on. Accessibile da browser.

Separare chiaramente: data ingestion, orbital engine, visibility engine,
ranking engine, scheduler/background workers, web UI.

## MVP consigliato

Prima versione:

1. download/update ASTORB;
2. parsing in SQLite;
3. calcolo locale Tj;
4. selezione Tj < 3;
5. configurazione di più osservatori/strumenti;
6. propagazione preliminare locale;
7. calcolo osservabilità, altezza, Luna e magnitudine;
8. ricerca degli oggetti che entreranno sotto Vlim nei prossimi 12 mesi;
9. confronto automatico dei siti;
10. dashboard: Tonight, Coming into range, Tj < 3.

Seconda fase: NEOCP, PCCP, MPEC watcher, comete, uncertainty/FOV, recommended
exposures, verifica Horizons, notifiche.

---

## Addendum del 15 agosto 2026

Due vincoli aggiunti lo stesso giorno, prima di scrivere codice.

**L'app deve scalare.** Siti osservativi, strumenti e CCD cambiano: se ne
aggiungono, se ne tolgono, si ricombinano. La configurazione non può essere
scritta nel codice né in una tabella da modificare a mano.

**Un domani, oggetti deep sky.** L'architettura non deve dare per scontato che
un target sia un corpo del Sistema Solare.

Documentazione di progetto sul modello di brain42: [README.md](README.md) dice
cosa c'è e come si avvia, [MEMORANDUM.md](MEMORANDUM.md) dice perché ogni cosa
è com'è, [CLAUDE.md](CLAUDE.md) dice come si lavora.
