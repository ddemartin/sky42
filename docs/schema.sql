-- sky42 — schema SQLite (v1)
--
-- Convenzioni:
--   * tutti i tempi sono UTC; i timestamp "wall clock" sono TEXT ISO-8601 ('2026-08-15T21:30:00Z')
--   * gli istanti dei calcoli sono REAL = Julian Date TDB (colonne *_jd)
--   * angoli in gradi, distanze in AU, aperture e focali in mm, campi in arcmin
--   * i BLOB "array" sono float32 little-endian, rileggibili con numpy.frombuffer
--
-- Due regole strutturali che spiegano quasi tutto lo schema:
--
--   1. L'hardware non si cancella mai. Un sito che chiude, una camera che si
--      rompe, un setup che cambia: si mette `active = 0` e `valid_to`. Le righe
--      di observation_log e observation_window puntano a setup_id e devono
--      restare leggibili fra tre anni. Cancellare un setup falsifica la storia.
--
--   2. Tutto ciò che sta a valle punta a target(id) e non sa che cosa sia
--      l'oggetto. Il modo di calcolarne la posizione lo decide target.kind
--      tramite un positioner (vedi CLAUDE.md). Il giorno in cui entrano gli
--      oggetti deep sky, il visibility engine non cambia di una riga.
--
-- PRAGMA applicati all'apertura (sky42/db.py):
--   journal_mode=WAL, synchronous=NORMAL, foreign_keys=ON, busy_timeout=10000

-- ---------------------------------------------------------------------------
-- 1. Hardware osservativo
--
--    Sito → telescopio → camera → setup. Il setup è la combinazione che
--    osserva davvero, ed è l'unica cosa che il visibility engine conosce:
--    ha un campo, una scala, un limite di magnitudine. Telescopi e camere si
--    ricombinano senza toccare il resto.
--
--    La fonte di verità è YAML in config/sites/*.yml; queste tabelle sono un
--    indice rigenerabile (reconcile all'avvio). La chiave naturale è `code`,
--    mai l'id autoincrementale, o rigenerare il database sposterebbe la storia
--    da un setup all'altro.
-- ---------------------------------------------------------------------------

CREATE TABLE observatory (
    id              INTEGER PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,       -- slug stabile: 'cile-rio-hurtado'
    name            TEXT NOT NULL,
    mpc_code        TEXT,
    latitude        REAL NOT NULL,              -- gradi, nord positivo
    longitude       REAL NOT NULL,              -- gradi, est positivo
    altitude_m      REAL NOT NULL DEFAULT 0,
    timezone        TEXT NOT NULL,              -- IANA: 'America/Santiago'
    -- qualità del cielo: entra nel modello di brillanza, non è decorazione
    sky_zenith_mag  REAL NOT NULL DEFAULT 21.6, -- V mag/arcsec² in notte scura senza Luna
    extinction_k    REAL NOT NULL DEFAULT 0.16, -- mag/airmass in V
    horizon_json    TEXT,                       -- opzionale [[az,alt],...]: alberi, muri, cupola
    valid_from      TEXT,
    valid_to        TEXT,                       -- NULL = ancora in uso
    active          INTEGER NOT NULL DEFAULT 1,
    notes           TEXT
);

CREATE TABLE telescope (
    id                  INTEGER PRIMARY KEY,
    code                TEXT NOT NULL UNIQUE,
    observatory_id      INTEGER NOT NULL REFERENCES observatory(id),
    name                TEXT NOT NULL,
    aperture_mm         REAL NOT NULL,
    focal_length_mm     REAL NOT NULL,          -- nativa, senza riduttore
    design              TEXT,                   -- 'RC','Newton','astrografo',...
    -- limiti della montatura: servono al calcolo delle finestre, non all'inventario
    min_altitude_deg    REAL NOT NULL DEFAULT 20,
    max_track_rate_arcsec_min REAL,             -- NULL = nessun limite noto
    meridian_flip       INTEGER NOT NULL DEFAULT 0,
    valid_from          TEXT,
    valid_to            TEXT,
    active              INTEGER NOT NULL DEFAULT 1,
    notes               TEXT
);

CREATE TABLE camera (
    id                  INTEGER PRIMARY KEY,
    code                TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    sensor              TEXT,                   -- 'IMX455','KAF-16803',...
    pixel_um            REAL NOT NULL,
    pixels_x            INTEGER NOT NULL,
    pixels_y            INTEGER NOT NULL,
    read_noise_e        REAL,
    dark_e_s            REAL,
    full_well_e         REAL,
    -- una camera può spostarsi da un telescopio all'altro: non lega al sito
    valid_from          TEXT,
    valid_to            TEXT,
    active              INTEGER NOT NULL DEFAULT 1,
    notes               TEXT
);

-- La combinazione che osserva. Scala e campo sono *derivati* e ricalcolati dal
-- reconcile: scriverli a mano è il modo più facile per avere un campo che non
-- corrisponde a quello delle immagini.
CREATE TABLE setup (
    id                      INTEGER PRIMARY KEY,
    code                    TEXT NOT NULL UNIQUE,   -- 'cile-rc700-imx455-bin2'
    name                    TEXT NOT NULL,
    observatory_id          INTEGER NOT NULL REFERENCES observatory(id),
    telescope_id            INTEGER NOT NULL REFERENCES telescope(id),
    camera_id               INTEGER NOT NULL REFERENCES camera(id),
    binning                 INTEGER NOT NULL DEFAULT 1,
    filter                  TEXT,                   -- 'L','V','clear','Sloan r'
    focal_reducer           REAL NOT NULL DEFAULT 1.0,
    -- derivati (reconcile): pixel_scale = 206.265 * pixel_um * bin / focale_effettiva
    pixel_scale_arcsec      REAL NOT NULL,
    fov_x_arcmin            REAL NOT NULL,
    fov_y_arcmin            REAL NOT NULL,
    -- fotometria: il limite è definito a un'esposizione di riferimento e scalato
    -- come vlim(t) = vlim_ref + 1.25*log10(t/t_ref) (regime sky-limited)
    vlim_ref                REAL NOT NULL,          -- rivelazione, S/N≈5
    vlim_ref_exposure_s     REAL NOT NULL DEFAULT 120,
    vlim_astrometric_delta  REAL NOT NULL DEFAULT -0.5,  -- quanto togliere per astrometria affidabile
    typical_exposure_s      REAL NOT NULL DEFAULT 120,
    max_exposure_s          REAL NOT NULL DEFAULT 600,
    max_airmass             REAL NOT NULL DEFAULT 2.2,
    min_altitude_deg        REAL,                   -- NULL = eredita dal telescopio
    typical_seeing_arcsec   REAL NOT NULL DEFAULT 2.0,
    sun_alt_max_deg         REAL NOT NULL DEFAULT -15,  -- crepuscolo accettato
    valid_from              TEXT,
    valid_to                TEXT,
    active                  INTEGER NOT NULL DEFAULT 1,
    notes                   TEXT
);

CREATE INDEX idx_setup_active ON setup(active, observatory_id);

-- Il limite dichiarato è una stima; questa tabella lo corregge con i fatti.
-- Una misura per notte e per setup basta a far convergere vlim_ref.
CREATE TABLE setup_calibration (
    id              INTEGER PRIMARY KEY,
    setup_id        INTEGER NOT NULL REFERENCES setup(id) ON DELETE CASCADE,
    measured_at     TEXT NOT NULL,
    exposure_s      REAL NOT NULL,
    airmass         REAL,
    sky_mag         REAL,                       -- brillanza misurata, V mag/arcsec²
    seeing_arcsec   REAL,
    faintest_mag    REAL NOT NULL,              -- magnitudine più debole misurata con S/N≈5
    note            TEXT
);

CREATE INDEX idx_calib_setup ON setup_calibration(setup_id, measured_at DESC);

-- ---------------------------------------------------------------------------
-- 2. Oggetti
--
--    `target` è l'identità stabile e non sa nulla di orbite. Gli elementi
--    stanno in `orbit`, le coordinate fisse in `fixed_target`: un target ha
--    l'una o l'altra a seconda di `kind`, e il positioner giusto lo sceglie
--    sky42/orbits/positioner.py.
-- ---------------------------------------------------------------------------

CREATE TABLE target (
    id                  INTEGER PRIMARY KEY,
    kind                TEXT NOT NULL CHECK (kind IN (
                            'asteroid','comet','candidate','fixed','planet','satellite')),
    primary_desig       TEXT NOT NULL UNIQUE,   -- '2020 AB123', '1P', 'C/2025 K1', 'NGC 7331'
    packed_desig        TEXT,
    number              INTEGER,
    name                TEXT,
    display_name        TEXT NOT NULL,
    orbit_class         TEXT,                   -- 'MBA','APO','ATE','JFC','HTC',... o tipo DSO
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- L'indice è su (number, kind) e non sul solo `number` per una ragione che è
-- costata un'ora di CPU: la numerazione delle comete è distinta da quella degli
-- asteroidi, quindi ogni ricerca per numero porta con sé `kind`. Con due indici
-- separati SQLite, senza statistiche, sceglieva quello su `kind` — che seleziona
-- un milione e mezzo di righe invece di una. Vedi MEMORANDUM 2026-08-15.
CREATE INDEX idx_target_number_kind ON target(number, kind);
CREATE INDEX idx_target_desig_kind  ON target(primary_desig, kind);
CREATE INDEX idx_target_kind        ON target(kind);

-- Elementi osculatori correnti, uno per target. Copre asteroidi (a, M) e
-- comete (q, tp): i campi non pertinenti restano NULL.
CREATE TABLE orbit (
    target_id       INTEGER PRIMARY KEY REFERENCES target(id) ON DELETE CASCADE,
    source          TEXT NOT NULL,              -- 'astorb','mpcorb','cometels','neocp','horizons'
    epoch_jd        REAL NOT NULL,              -- TDB
    a_au            REAL,
    q_au            REAL,
    e               REAL NOT NULL,
    i_deg           REAL NOT NULL,
    node_deg        REAL NOT NULL,              -- Ω, eclittica J2000
    argp_deg        REAL NOT NULL,              -- ω
    m_deg           REAL,                       -- anomalia media all'epoca
    tp_jd           REAL,                       -- passaggio al perielio (comete)
    n_deg_day       REAL,                       -- moto medio, derivato
    -- fotometria
    h_mag           REAL,
    g_slope         REAL DEFAULT 0.15,
    m1 REAL, k1 REAL,                           -- magnitudine totale cometaria
    m2 REAL, k2 REAL,                           -- magnitudine nucleare
    -- qualità dell'orbita, tutta dall'MPC (vedi memorandum: la fonte è una sola)
    arc_days        REAL,
    arc_years       TEXT,                       -- '1801-2026' com'è pubblicata
    n_obs           INTEGER,
    n_oppositions   INTEGER,
    first_obs_date  TEXT,
    last_obs_date   TEXT,                       -- 'YYYY-MM-DD'. Solo MPC ce l'ha
    rms_arcsec      REAL,                       -- residuo della soluzione
    u_param         REAL,                       -- U 0-9; grossolano, la CEU sta in astorb_extra
    hex_flags       TEXT,
    computer        TEXT,
    reference       TEXT,
    computed_date   TEXT,                       -- data della soluzione orbitale
    -- derivati all'import: costano una volta e si indicizzano
    q_derived_au    REAL,
    aphelion_au     REAL,
    period_yr       REAL,
    tisserand_j     REAL,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- (source, updated_at) e non il solo `source`: la pagina Catalogo chiede a ogni
-- caricamento quante orbite vengono da ciascuna fonte e quando sono state
-- scritte. Senza l'indice composito è una scansione da 1,5 milioni di righe,
-- cioè un secondo e mezzo per un'informazione di intestazione.
CREATE INDEX idx_orbit_source    ON orbit(source, updated_at);
CREATE INDEX idx_orbit_tisserand ON orbit(tisserand_j) WHERE tisserand_j IS NOT NULL;
CREATE INDEX idx_orbit_h         ON orbit(h_mag);
CREATE INDEX idx_orbit_lastobs   ON orbit(last_obs_date);
CREATE INDEX idx_orbit_q         ON orbit(q_derived_au);

-- Lo strato ASTORB. Tabella separata e non colonne in `orbit` per una ragione
-- precisa: ASTORB è un prodotto derivato a manutenzione ristretta. Se un giorno
-- smette di aggiornarsi voglio perdere *una funzione* — l'incertezza in arcsec —
-- e accorgermene da `updated_at`, invece di avere metà di `orbit` fresca e metà
-- vecchia di sei mesi senza che si veda.
--
-- Vale per il 5,5% del catalogo (CEU fra 1' e 1°), che è però esattamente la
-- fascia degli oggetti trascurati: la CEU alta *è* il segnale di rarità.
CREATE TABLE astorb_extra (
    target_id       INTEGER PRIMARY KEY REFERENCES target(id) ON DELETE CASCADE,
    -- incertezza: l'unica cosa che l'MPC non pubblica in arcsec
    ceu_arcsec      REAL,                       -- current ephemeris uncertainty
    ceu_rate        REAL,                       -- arcsec/giorno
    ceu_date        TEXT,
    peu_arcsec      REAL,                       -- prossimo picco
    peu_date        TEXT,
    peu10_arcsec    REAL,                       -- massimo nei 10 anni dalla data CEU
    peu10_date      TEXT,
    -- dati fisici: pochi e spesso vuoti, ma gratis
    bv_color        REAL,
    diameter_km     REAL,                       -- IRAS
    taxon_class     TEXT,                       -- IRAS
    -- elementi ASTORB: NON si usano per propagare (quelli stanno in `orbit`).
    -- Servono solo a due cose: accorgersi se le due fonti divergono, e coprire
    -- gli ~800 oggetti persi che l'MPC non pubblica più.
    astorb_epoch_jd REAL,
    astorb_a_au     REAL,
    astorb_e        REAL,
    astorb_i_deg    REAL,
    arc_days        REAL,
    n_obs           INTEGER,
    computed_date   TEXT,
    updated_at      TEXT NOT NULL
);

CREATE INDEX idx_astorb_ceu ON astorb_extra(ceu_arcsec);

-- Non popolata nell'MVP. Sta qui perché è il contratto che rende vera la
-- generalizzazione di `target`: se il visibility engine riesce a lavorare su
-- una riga di questa tabella senza modifiche, gli oggetti deep sky sono un
-- ingestore e un positioner, non una riscrittura.
CREATE TABLE fixed_target (
    target_id           INTEGER PRIMARY KEY REFERENCES target(id) ON DELETE CASCADE,
    ra_deg              REAL NOT NULL,          -- ICRS J2000
    dec_deg             REAL NOT NULL,
    pm_ra_mas_yr        REAL DEFAULT 0,
    pm_dec_mas_yr       REAL DEFAULT 0,
    mag                 REAL,                   -- magnitudine integrata
    surface_brightness  REAL,                   -- mag/arcsec²: per gli estesi è questo che conta
    size_major_arcmin   REAL,
    size_minor_arcmin   REAL,
    position_angle_deg  REAL,
    object_type         TEXT,                   -- 'galaxy','pn','oc','gc','nebula',...
    catalog_ids         TEXT,                   -- JSON: {"ngc":7331,"ugc":12113}
    source              TEXT
);

CREATE TABLE catalog_version (
    id              INTEGER PRIMARY KEY,
    source          TEXT NOT NULL,
    url             TEXT NOT NULL,
    etag            TEXT,
    last_modified   TEXT,
    sha256          TEXT NOT NULL,
    size_bytes      INTEGER,
    n_records       INTEGER,
    downloaded_at   TEXT NOT NULL,
    imported_at     TEXT,
    local_path      TEXT
);

CREATE INDEX idx_catver_source ON catalog_version(source, downloaded_at DESC);

-- ---------------------------------------------------------------------------
-- 3. Screening: tracce geocentriche precomputate
--
--    Una riga per target monitorato, serie temporali in BLOB float32 invece che
--    in righe: ~4 kB per oggetto invece di ~180 righe, e si rilegge in una
--    query sola. Su questi dati non servono query relazionali — ciò che va
--    interrogato è già distillato in target_stats.
-- ---------------------------------------------------------------------------

CREATE TABLE screening_track (
    target_id   INTEGER PRIMARY KEY REFERENCES target(id) ON DELETE CASCADE,
    run_id      INTEGER REFERENCES job_run(id) ON DELETE SET NULL,
    jd_start    REAL NOT NULL,
    step_days   REAL NOT NULL,
    n_samples   INTEGER NOT NULL,
    v_mag       BLOB NOT NULL,      -- float32[n], magnitudine geocentrica prevista
    r_au        BLOB NOT NULL,
    delta_au    BLOB NOT NULL,
    elong_deg   BLOB NOT NULL,
    ra_deg      BLOB NOT NULL,
    dec_deg     BLOB NOT NULL,
    computed_at TEXT NOT NULL
);

CREATE TABLE target_stats (
    target_id                   INTEGER PRIMARY KEY REFERENCES target(id) ON DELETE CASCADE,
    v_now                       REAL,
    v_trend_mag_month           REAL,           -- negativo = sta migliorando
    peak_v                      REAL,           -- minimo di V nella finestra di screening
    peak_jd                     REAL,
    next_v21_jd                 REAL,
    next_v205_jd                REAL,
    visibility_start_jd         REAL,
    visibility_end_jd           REAL,
    last_good_apparition_jd     REAL,           -- da back-propagation
    years_since_good_apparition REAL,
    years_since_last_obs        REAL,           -- da orbit.last_obs_date
    ceu_now_arcsec              REAL,           -- CEU propagata a oggi
    computed_at                 TEXT NOT NULL
);

CREATE INDEX idx_stats_next21 ON target_stats(next_v21_jd);
CREATE INDEX idx_stats_peak   ON target_stats(peak_v);

-- ---------------------------------------------------------------------------
-- 4. Returning-object radar
-- ---------------------------------------------------------------------------

-- Stato per coppia (target, setup). setup_id NULL = rollup "migliore fra tutti
-- i setup attivi", che è quello che legge la dashboard.
CREATE TABLE target_state (
    target_id       INTEGER NOT NULL REFERENCES target(id) ON DELETE CASCADE,
    setup_id        INTEGER REFERENCES setup(id) ON DELETE CASCADE,
    state           TEXT NOT NULL CHECK (state IN (
                        'OUT_OF_RANGE','APPROACHING','CROSSES_LIMIT',
                        'OBSERVABLE','PRIME','FADING')),
    since           TEXT NOT NULL,
    v_pred          REAL,
    eff_vlim_ref    REAL,                       -- limite efficace di riferimento usato
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (target_id, setup_id)
);

CREATE INDEX idx_state_state ON target_state(state, updated_at DESC);

CREATE TABLE state_transition (
    id              INTEGER PRIMARY KEY,
    target_id       INTEGER NOT NULL REFERENCES target(id) ON DELETE CASCADE,
    setup_id        INTEGER REFERENCES setup(id) ON DELETE CASCADE,
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    at              TEXT NOT NULL,
    v_pred          REAL,
    context_json    TEXT,                       -- fotografia delle grandezze al momento
    notified        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_transition_at  ON state_transition(at DESC);
CREATE INDEX idx_transition_tgt ON state_transition(target_id, at DESC);

-- ---------------------------------------------------------------------------
-- 5. Notte e finestre osservative
--
--    `night` sta per osservatorio (Sole, Luna e crepuscolo dipendono dal sito,
--    non dallo strumento); `observation_window` sta per setup. È la ragione per
--    cui aggiungere una camera costa poco e aggiungere un sito costa: il lavoro
--    pesante scala con i siti.
-- ---------------------------------------------------------------------------

CREATE TABLE night (
    id                  INTEGER PRIMARY KEY,
    observatory_id      INTEGER NOT NULL REFERENCES observatory(id) ON DELETE CASCADE,
    night_date          TEXT NOT NULL,          -- data locale della sera, '2026-08-15'
    sunset_jd           REAL,
    sunrise_jd          REAL,
    twilight_end_jd     REAL,                   -- fine crepuscolo astronomico (sera)
    twilight_start_jd   REAL,                   -- inizio crepuscolo astronomico (mattina)
    dark_hours          REAL,
    moon_illum          REAL,                   -- frazione illuminata 0-1
    moon_rise_jd        REAL,
    moon_set_jd         REAL,
    moon_max_alt_deg    REAL,
    computed_at         TEXT NOT NULL,
    UNIQUE (observatory_id, night_date)
);

CREATE TABLE observation_window (
    id                      INTEGER PRIMARY KEY,
    night_id                INTEGER NOT NULL REFERENCES night(id) ON DELETE CASCADE,
    target_id               INTEGER NOT NULL REFERENCES target(id) ON DELETE CASCADE,
    setup_id                INTEGER NOT NULL REFERENCES setup(id) ON DELETE CASCADE,
    -- finestra geometricamente valida (altezza, airmass, crepuscolo)
    geo_start_jd            REAL,
    geo_end_jd              REAL,
    -- finestra effettivamente utile (V ≤ eff_vlim con margine)
    useful_start_jd         REAL,
    useful_end_jd           REAL,
    useful_hours            REAL,
    -- istante ottimo: non si assume che sia il transito
    best_jd                 REAL,
    best_alt_deg            REAL,
    best_az_deg             REAL,
    best_airmass            REAL,
    transit_jd              REAL,
    max_alt_deg             REAL,
    v_pred                  REAL,
    elong_deg               REAL,
    -- Luna
    moon_sep_deg            REAL,
    moon_alt_deg            REAL,
    moon_illum              REAL,
    sky_brightness_mag      REAL,               -- V mag/arcsec² al best_jd
    -- magnitudine limite efficace, scomposta: senza la scomposizione non si
    -- capisce perché un sito ha perso, e non si tara nulla
    eff_vlim                REAL,
    pen_airmass             REAL,
    pen_moon                REAL,
    pen_twilight            REAL,
    pen_trailing            REAL,
    depth_margin            REAL,               -- eff_vlim - v_pred
    -- moto ed esposizione
    motion_arcsec_min       REAL,
    motion_pa_deg           REAL,
    trail_arcsec            REAL,
    rec_exposure_s          REAL,
    rec_n_subs              INTEGER,
    -- quanto l'oggetto "sta" nel campo: incertezza per gli asteroidi,
    -- dimensione apparente il giorno in cui entreranno gli oggetti estesi
    fov_fit_arcsec          REAL,
    fov_fit_ratio           REAL,               -- fov_fit_arcsec / min(fov_x, fov_y)
    needs_mosaic            INTEGER NOT NULL DEFAULT 0,
    -- ranking
    score                   REAL,
    score_json              TEXT,               -- breakdown per feature
    grade                   TEXT CHECK (grade IN ('PRIME','GOOD','POSSIBLE','POOR','NOT_USEFUL')),
    computed_at             TEXT NOT NULL,
    UNIQUE (night_id, target_id, setup_id)
);

CREATE INDEX idx_window_rank   ON observation_window(night_id, score DESC);
CREATE INDEX idx_window_target ON observation_window(target_id, night_id);
CREATE INDEX idx_window_grade  ON observation_window(grade, score DESC);

-- ---------------------------------------------------------------------------
-- 6. Candidati MPC e circolari
-- ---------------------------------------------------------------------------

CREATE TABLE mpc_candidate (
    id                  INTEGER PRIMARY KEY,
    list                TEXT NOT NULL CHECK (list IN ('NEOCP','PCCP')),
    temp_desig          TEXT NOT NULL,
    first_seen          TEXT NOT NULL,
    last_seen           TEXT NOT NULL,
    still_listed        INTEGER NOT NULL DEFAULT 1,
    -- ultimi valori noti; lo storico completo sta negli snapshot
    score               REAL,                   -- NEO score MPC
    ra_deg              REAL,
    dec_deg             REAL,
    v_mag               REAL,
    motion_arcmin_hr    REAL,
    motion_pa_deg       REAL,
    n_obs               INTEGER,
    arc_hours           REAL,
    unc_arcsec          REAL,
    updated_at          TEXT NOT NULL,
    -- il destino del candidato: è la parte che nessuno conserva e che serve
    resolution          TEXT CHECK (resolution IN (
                            'confirmed_neo','confirmed_comet','known_object',
                            'not_confirmed','removed','unknown')),
    resolved_at         TEXT,
    resolved_desig      TEXT,
    resolved_target_id  INTEGER REFERENCES target(id) ON DELETE SET NULL,
    resolution_source   TEXT,                   -- 'mpec:2026-Q12', 'inferenza', ...
    UNIQUE (list, temp_desig, first_seen)
);

CREATE INDEX idx_cand_open ON mpc_candidate(list, still_listed, updated_at DESC);

CREATE TABLE mpc_candidate_snapshot (
    id                  INTEGER PRIMARY KEY,
    candidate_id        INTEGER NOT NULL REFERENCES mpc_candidate(id) ON DELETE CASCADE,
    observed_at         TEXT NOT NULL,          -- quando l'abbiamo letto noi
    ra_deg REAL, dec_deg REAL, v_mag REAL,
    motion_arcmin_hr REAL, motion_pa_deg REAL,
    n_obs INTEGER, arc_hours REAL, score REAL, unc_arcsec REAL,
    raw                 TEXT                    -- record originale, per rileggere dopo
);

CREATE INDEX idx_snap_cand ON mpc_candidate_snapshot(candidate_id, observed_at);

CREATE TABLE mpec (
    id              INTEGER PRIMARY KEY,
    mpec_id         TEXT NOT NULL UNIQUE,       -- '2026-Q12'
    title           TEXT,
    url             TEXT,
    published_at    TEXT,
    kind            TEXT,                       -- 'neo','comet','daily-orbit-update',...
    fetched_at      TEXT NOT NULL,
    body_hash       TEXT
);

CREATE TABLE mpec_object (
    mpec_id_ref     INTEGER NOT NULL REFERENCES mpec(id) ON DELETE CASCADE,
    designation     TEXT NOT NULL,
    target_id       INTEGER REFERENCES target(id) ON DELETE SET NULL,
    candidate_id    INTEGER REFERENCES mpc_candidate(id) ON DELETE SET NULL,
    PRIMARY KEY (mpec_id_ref, designation)
);

-- ---------------------------------------------------------------------------
-- 7. Quello che decide l'utente
-- ---------------------------------------------------------------------------

CREATE TABLE watchlist (
    target_id   INTEGER PRIMARY KEY REFERENCES target(id) ON DELETE CASCADE,
    priority    INTEGER NOT NULL DEFAULT 0,     -- bonus manuale allo score
    tag         TEXT,
    note        TEXT,
    added_at    TEXT NOT NULL
);

CREATE TABLE observation_log (
    id              INTEGER PRIMARY KEY,
    target_id       INTEGER NOT NULL REFERENCES target(id) ON DELETE CASCADE,
    setup_id        INTEGER REFERENCES setup(id),   -- niente CASCADE: la storia resta
    obs_start       TEXT NOT NULL,
    exposure_s      REAL,
    n_frames        INTEGER,
    outcome         TEXT,                       -- 'detected','not_detected','clouded',...
    measured_mag    REAL,
    note            TEXT
);

CREATE INDEX idx_obslog_target ON observation_log(target_id, obs_start DESC);

-- ---------------------------------------------------------------------------
-- 8. Configurazione e operations
-- ---------------------------------------------------------------------------

CREATE TABLE setting (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,                  -- JSON
    updated_at  TEXT NOT NULL
);

CREATE TABLE scoring_profile (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    target_kind TEXT,                           -- NULL = vale per tutti
    weights     TEXT NOT NULL,                  -- JSON {"feature": peso}
    gates       TEXT NOT NULL,                  -- JSON, soglie di esclusione
    active      INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

CREATE TABLE job_run (
    id              INTEGER PRIMARY KEY,
    job_name        TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL CHECK (status IN ('running','ok','failed','skipped')),
    n_processed     INTEGER,
    duration_s      REAL,
    detail_json     TEXT,
    error           TEXT
);

CREATE INDEX idx_jobrun_name ON job_run(job_name, started_at DESC);

-- Serve a restare educati con MPC e JPL, e ad accorgersene prima che se ne
-- accorgano loro.
CREATE TABLE external_call (
    id          INTEGER PRIMARY KEY,
    service     TEXT NOT NULL,                  -- 'horizons','sbdb','mpc','lowell'
    endpoint    TEXT,
    target_id   INTEGER REFERENCES target(id) ON DELETE SET NULL,
    called_at   TEXT NOT NULL,
    status      INTEGER,
    duration_ms REAL,
    cached      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_extcall_service ON external_call(service, called_at DESC);
