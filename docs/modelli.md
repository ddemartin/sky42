# Modelli e formule

Tutto ciò che sky42 calcola da sé, con la fonte e la precisione attesa. Le
scelte (perché questo modello e non un altro) stanno in
[MEMORANDUM.md](../MEMORANDUM.md); qui c'è solo il *come*.

Convenzione: angoli in gradi ai confini delle funzioni, radianti dentro; tempi
in JD (TDB); distanze in AU.

---

## 1. Elementi derivati

```
q = a(1 - e)                      perielio
Q = a(1 + e)                      afelio
P = a^1.5                         periodo in anni (a in AU)
n = 0.9856076686 / a^1.5          moto medio, gradi/giorno
```

**Tisserand rispetto a Giove**, con a_J = 5.2038 AU:

```
Tj = a_J/a + 2 cos(i) sqrt[(a/a_J)(1 - e²)]
```

L'inclinazione è quella eclittica del catalogo, non quella rispetto al piano
orbitale di Giove: è la convenzione con cui sono pubblicate tutte le liste di
asteroidi in orbita cometaria, e cambiare riferimento renderebbe i nostri Tj
non confrontabili con la letteratura. La differenza è ≲ 0.01 per i > 1.3°.

Non definito per e ≥ 1 e per a ≤ 0: in quei casi resta NULL.

## 2. Propagazione a due corpi (screening)

Anomalia media all'istante t:

```
M(t) = M₀ + n (t - epoch)          (mod 360°)
```

Equazione di Keplero `M = E - e sin E`, risolta con Newton vettoriale su
`numpy`, innesco `E₀ = M + e sin M`, criterio `|ΔE| < 1e-10 rad`, tipicamente
4-5 iterazioni. Il ciclo è sulle *iterazioni*, mai sugli oggetti.

```
x_orb = a(cos E - e)
y_orb = a sqrt(1 - e²) sin E
r     = a(1 - e cos E)
```

Rotazione al riferimento eclittico J2000 con `Rz(-Ω) Rx(-i) Rz(-ω)`, poi
all'equatoriale con l'obliquità ε = 23.43929111°.

**Comete ed e→1.** Per `e > 0.98` Newton su E degenera: si usano le variabili
universali (formulazione di Stumpff), con `q` e `tp` invece di `a` e `M`. Il
ramo si sceglie sull'eccentricità, non sul tipo di oggetto: un asteroide con
e = 0.99 va nello stesso ramo di una cometa.

L'equazione universale è contata dal perielio, dove lo stato iniziale è noto
esatto (`r₀ = q P̂`, `v₀ = sqrt(GM(1+e)/q) Q̂`):

```
√GM (t - tp) = q x + e x³ S(z)        z = α x²,  α = (1 - e)/q
r            = q + e x² C(z)          ( = dF/dx )
f = 1 - (x²/q) C(z)                   g    = Δt - (x³/√GM) S(z)
ḟ = √GM x (z S(z) - 1)/(r q)          ġ    = 1 - (x²/r) C(z)
```

α > 0 ellisse, α = 0 parabola, α < 0 iperbole: un solo codice. F(x) è dispari e
crescente, quindi Newton lavora dentro un intervallo trovato per raddoppio e
bisseca quando il passo ne esce — senza rete, un'iperbolica lontana dal
perielio diverge. Le funzioni di Stumpff C e S si valutano in forma chiusa e,
per `|z| < 0.1` dove la forma chiusa si annulla per cancellazione, con lo
sviluppo in serie fino a `z⁴` (il raccordo fra i due rami vale 2e-14; con un
termine in meno era 3e-11).

**Perturbazioni: nessuna.** Vedi il memorandum del 2026-08-15 e il job di
validazione: l'errore atteso è lungo l'orbita, cresce con il tempo dall'epoca,
e su V è di ordine centesimi di magnitudine — irrilevante per distinguere
V 19.5 da V 21 da V 24, che è tutto ciò che allo screening serve. Per puntare
il telescopio si passa da Horizons.

## 3. Da eliocentrico a geocentrico

```
Δ⃗ = r⃗_ogg - r⃗_terra
```

con la posizione della Terra da DE440s (Skyfield), **eliocentrica** come i
nostri elementi: mescolare origine baricentrica ed eliocentrica sposta tutto di
~0.005 AU. **Tempo luce**: si ricalcola la posizione dell'oggetto a `t - Δ/c`
con `c = 173.1446 AU/giorno`. Una iterazione basta (residuo < 0.1" per Δ < 5
AU); toglierla del tutto sposta Faetonte di 1.9", misurato.

Il risultato è **astrometrico**: corretto per tempo luce, senza aberrazione
annua né rifrazione — la quantità 1 di Horizons e la convenzione
dell'astrometria MPC. L'aberrazione serve a puntare, e per puntare si passa da
Horizons.

Angolo di fase, con R distanza eliocentrica dell'osservatore:

```
cos α = (r² + Δ² - R²) / (2 r Δ)
```

Elongazione solare:

```
cos(elong) = (Δ² + R² - r²) / (2 Δ R)
```

Il **moto apparente** si ottiene per differenze finite su ±30 minuti dalla
stessa funzione di posizione — non con una formula chiusa, così vale identico
per asteroidi, comete e qualunque positioner futuro.

## 4. Fotometria

**Asteroidi, sistema H-G** (Bowell et al. 1989):

```
V = H + 5 log₁₀(r Δ) - 2.5 log₁₀[(1-G) Φ₁(α) + G Φ₂(α)]
Φᵢ(α) = exp(-Aᵢ (tan(α/2))^Bᵢ)
A₁ = 3.33  B₁ = 0.63
A₂ = 1.87  B₂ = 1.22
```

Con `G = 0.15` quando il catalogo non lo dà. Valido per α < 120°; oltre, la
formula si estrapola e il valore va marcato come inaffidabile invece che
mostrato come se fosse buono.

**Comete, magnitudine totale**:

```
m1 = M1 + 5 log₁₀(Δ) + K1 log₁₀(r)
```

dove `K1 = 2.5·k1` e `k1` è il parametro **dell'MPC** (colonna `orbit.k1`,
tipicamente 4). Attenzione: JPL chiama `k1` il coefficiente già moltiplicato per
2.5, cioè 10 dove l'MPC scrive 4. Scambiare le due convenzioni vale 2.4
magnitudini su una cometa a r = 2 AU, in silenzio. Con `k1 = 4` quando manca.

**Questa formula sbaglia regolarmente di 2-3 magnitudini** ed è un ordinamento,
non una previsione:
l'interfaccia la mostra sempre con la sua incertezza dichiarata, e le comete si
ordinano per geometria (r, Δ, elongazione, trend) prima che per magnitudine.
Le due fotometrie non si mescolano mai: un oggetto con `kind='comet'` non usa
H-G nemmeno se ha un H nel catalogo.

## 5. Geometria osservativa

**Airmass** (Kasten & Young 1989), con z distanza zenitale in gradi:

```
X = 1 / [cos z + 0.50572 (96.07995 - z)^(-1.6364)]
```

Valida fino all'orizzonte, a differenza di `sec z`. Sopra `X = 40` si tronca.

Alt/az, transito, sorgere e tramonto da Skyfield per Sole e Luna; per il target
si campiona la notte e si prendono i massimi e gli attraversamenti sulla
griglia (5 minuti), invece di risolvere equazioni: costa niente e vale per
qualunque positioner.

**Orizzonte locale**: se il sito dichiara un profilo, l'altezza minima è
l'interpolazione lineare in azimut di quel profilo, altrimenti
`min_altitude_deg`.

## 6. Brillanza del cielo

Modello di **Krisciunas & Schaefer (1991)**, PASP 103, 1033. Tutte le
luminanze in nanoLambert.

Conversione fra magnitudine per arcsec² e luminanza:

```
B = 34.08 exp(20.7233 - 0.92104 V)
V = [20.7233 - ln(B / 34.08)] / 0.92104
```

Contributo lunare, con α angolo di fase della Luna in gradi (0 = piena),
ρ separazione Luna-target, Z distanze zenitali, k coefficiente di estinzione:

```
I*   = 10^(-0.4 (3.84 + 0.026|α| + 4e-9 α⁴))
f(ρ) = 10^5.36 (1.06 + cos²ρ) + 10^(6.15 - ρ/40)
X(Z) = (1 - 0.96 sin²Z)^(-0.5)

B_luna = f(ρ) · I* · 10^(-0.4 k X(Z_luna)) · [1 - 10^(-0.4 k X(Z_target))]
```

Il fattore `10^(-0.4 k X(Z_luna))` è la ragione per cui **una Luna piena sotto
l'orizzonte non penalizza**: il termine va a zero da solo, senza bisogno di un
`if`. Sopra Z_luna = 90° si annulla esplicitamente.

Cielo scuro alla distanza zenitale del target, a partire dal valore allo zenit
dichiarato dal sito:

```
B_scuro(Z) = B_zenit · 10^(-0.4 k (X-1)) · X
```

**Crepuscolo** — qui non c'è un modello di riferimento altrettanto solido, e
questa è una formula empirica dichiarata tale, da tarare sulle misure di
`setup_calibration`:

```
ΔV_crep = 0.55 · (h_Sole + 18)     per h_Sole > -18°, altrimenti 0
```

cioè circa 1.7 mag di cielo più brillante a −15°. È il numero più debole del
sistema: va corretto con i dati, non difeso.

## 7. Magnitudine limite efficace

Il limite dichiarato `vlim_ref` vale a `vlim_ref_exposure_s`, allo zenit, con
cielo scuro e sorgente puntiforme. Tutto il resto sono penalità.

Regime sky-limited: S/N ∝ √t e S/N ∝ 1/√B, quindi ogni fattore sul fondo o sul
tempo entra come `1.25 log₁₀`.

```
eff_vlim = vlim_ref
         + 1.25 log₁₀(t_exp / t_ref)            esposizione
         - k (X_target - 1)                     estinzione
         - 1.25 log₁₀(B_tot / B_zenit_scuro)    fondo (airmass + Luna + crepuscolo)
         - 1.25 log₁₀(1 + L/θ)                  trailing
```

Le penalità si salvano separate perché servono a spiegare, e la separazione è
questa:

```
pen_airmass   = k (X-1) + 1.25 log₁₀(B_scuro(Z) / B_zenit)
pen_moon      = 1.25 log₁₀([B_scuro(Z) + B_luna] / B_scuro(Z))
pen_twilight  = 1.25 log₁₀([B_scuro(Z) + B_crep] / B_scuro(Z))
pen_trailing  = 1.25 log₁₀(1 + L/θ)
```

La somma delle quattro non è esattamente la penalità totale quando Luna e
crepuscolo agiscono insieme (i logaritmi non sono additivi sui termini
incrociati): il totale che vale è `eff_vlim`, e le quattro sono la
scomposizione leggibile. La differenza si registra e resta sotto 0.05 mag nei
casi realistici; se cresce, è un cielo in cui non si osserva comunque.

Per l'astrometria si usa `eff_vlim + vlim_astrometric_delta`: rivelare un
puntino e misurarne la posizione a 0.3" non sono la stessa soglia.

**Il giorno degli oggetti estesi** questa funzione diventa una strategia scelta
per `target.kind`: per una galassia il confronto giusto è fra brillanza
superficiale e brillanza del cielo, non fra magnitudine integrata e limite
puntiforme. La firma non cambia, cambia l'implementazione.

## 8. Trailing ed esposizione consigliata

Con μ in arcsec/minuto, t in secondi, θ = FWHM del seeing:

```
L = μ · t / 60                          lunghezza della traccia in arcsec
pen_trailing = 1.25 log₁₀(1 + L/θ)
```

Esposizione massima per non impastare (tolleranza = una FWHM):

```
t_trail_max = 60 · max(θ, 1.5 · pixel_scale) / μ
```

Esposizione necessaria a raggiungere l'oggetto, invertendo la scala in √t:

```
t_need = t_ref · 10^[(V - eff_vlim(t_ref)) / 1.25]
```

Da cui la raccomandazione:

```
t_sub  = min(t_trail_max, max_exposure_s)
n_subs = ceil(t_need / t_sub)
```

Se `n_subs · t_sub` supera la finestra utile, l'oggetto è fuori portata *per
quel setup* anche se `eff_vlim` da solo direbbe di sì — ed è esattamente il
caso in cui un'apertura più grande vince: accorcia `t_need` e quindi il numero
di pose, non il limite in sé. Lo stack su oggetto in moto richiede
shift-and-add, coerente con la crescita in √N.

## 9. Incertezza posizionale e campo

Incertezza propagata a oggi dalla CEU di ASTORB:

```
unc(t) = ceu + ceu_rate · (t - ceu_date)
```

È lineare e quindi una **stima per difetto** su tempi lunghi: oltre l'anno si
mostra come ordine di grandezza. Quando c'è, `peu` è il controllo di sanità.

```
fov_fit_ratio = 3 · unc / min(fov_x, fov_y)
needs_mosaic  = fov_fit_ratio > 0.5
```

Tre sigma perché un recupero fallito costa una notte, e mezzo campo perché
l'oggetto va inseguito, non solo inquadrato una volta.

## 10. Stati del radar

Riferimento per setup: `V_ref = eff_vlim` in condizioni tipiche (X = 1.5,
niente Luna, `typical_exposure_s`). Non è una condizione reale: è un metro
stabile, che non cambia con la fase lunare.

| stato | condizione |
|---|---|
| `PRIME` | V ≤ V_ref − 0.75 e finestra utile ≥ 2 h |
| `OBSERVABLE` | V ≤ V_ref e finestra utile ≥ 0.5 h |
| `CROSSES_LIMIT` | evento: V attraversa V_ref scendendo |
| `APPROACHING` | V_ref < V ≤ V_ref + 1.5 e dV/dt < 0 |
| `FADING` | V ≤ V_ref ma oltre il picco (dV/dt > 0) |
| `OUT_OF_RANGE` | V > V_ref + 1.5 |

**Isteresi 0.15 mag** su ogni soglia e conferma su due calcoli consecutivi: un
oggetto che oscilla attorno al limite non deve generare venti transizioni e
venti notifiche. Ogni cambio scrive una riga in `state_transition` con la
fotografia delle grandezze al momento.

`last_good_apparition` viene dalla propagazione all'indietro (15 anni, passo 10
giorni): l'ultimo intervallo in cui V ≤ V_ref. Su quindici anni la posizione a
due corpi ha derivato parecchio, ma **la data di un'apparizione sbaglia di
giorni, non di anni**, e il dato serve a dire «7.4 anni fa», non a puntare.
`orbit.last_obs_date` resta il riscontro osservativo indipendente: se le due
cose si contraddicono di molto, è la propagazione ad avere torto.

## 11. Score

Feature normalizzate in [0,1], combinazione lineare con pesi da
`scoring_profile`. Prima i **cancelli** (fuori da questi non c'è punteggio):

```
depth_margin ≥ 0.3      l'oggetto sta sotto il limite efficace con margine
useful_hours ≥ 0.5
alt ≥ min_altitude, X ≤ max_airmass
μ ≤ max_track_rate      se il setup dichiara un limite
```

Poi i termini, divisi in due gruppi che vanno tenuti separati perché rispondono
a domande diverse — *quanto mi interessa* e *quanto bene riesce*:

```
interesse   tisserand (più basso, più alto il punteggio, saturato a Tj≤2.0)
            rarità (anni dall'ultima osservazione, saturato a 10 anni)
            ritorno (anni dall'ultima buona apparizione)
            watchlist (bonus manuale)
            arco corto / poche osservazioni

fattibilità depth_margin (saturato a 2 mag: oltre non serve più)
            durata della finestra utile (saturato a 4 h)
            airmass al momento migliore
            fov_fit_ratio
            fattibilità dell'esposizione (n_subs · t_sub vs finestra)
```

La Luna **non compare** fra i termini: è già dentro `depth_margin` attraverso
`eff_vlim`. Contarla due volte è l'errore più facile da fare qui, e produce
classifiche che puniscono il plenilunio due volte.

Mappa in giudizio: `PRIME ≥ 0.75`, `GOOD ≥ 0.55`, `POSSIBLE ≥ 0.35`,
`POOR > 0`, `NOT_USEFUL` = fuori dai cancelli. Le soglie stanno nel profilo.

---

## Riferimenti

- Bowell E. et al. (1989), *Application of photometric models to asteroids*, in Asteroids II
- Krisciunas K. & Schaefer B. E. (1991), PASP 103, 1033 — brillanza del cielo con Luna
- Kasten F. & Young A. T. (1989), Applied Optics 28, 4735 — airmass
- Meeus J., *Astronomical Algorithms*, 2ª ed. — Keplero, tempo siderale, variabili universali
- ASTORB, Lowell Observatory — descrizione del formato nel file di documentazione che accompagna `astorb.dat`
- JPL Horizons API — https://ssd-api.jpl.nasa.gov/doc/horizons.html
