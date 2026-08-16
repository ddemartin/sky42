"""Il solutore a due corpi, vettoriale.

Riceve *array* di elementi e *array* di epoche e restituisce posizione e
velocità eliocentriche nel riferimento eclittico J2000, in AU e AU/giorno. Il
ciclo Python è sempre e solo sulle iterazioni di Newton: sugli oggetti non si
itera mai, o lo screening di 14.000 orbite su una griglia di 24 mesi diventa
qualche milione di chiamate di funzione (docs/modelli.md §2).

Tutti gli argomenti si combinano con le regole di broadcasting di numpy: per
la griglia «N oggetti × M epoche» si passano gli elementi con forma (N, 1) e
le epoche con forma (M,), e si riceve (N, M, 3).

Due rami, scelti sull'**eccentricità e non sul tipo di oggetto**:

* `e < 0.98` e `a > 0`: equazione di Keplero classica, Newton su E.
* tutto il resto (quasi-paraboliche, paraboliche, iperboliche): variabili
  universali con le funzioni di Stumpff, che non conoscono `a` e lavorano su
  `q` e `tp`. Un asteroide con e = 0.99 passa di qui esattamente come una
  cometa.

Nessuna perturbazione: vedi il memorandum: l'errore è lungo l'orbita e cresce
con il tempo dall'epoca. Per puntare il telescopio si passa da Horizons, qui
si decide *chi guardare*.
"""
from __future__ import annotations

import numpy as np

# Costante di Gauss e parametro gravitazionale solare, in AU^3/giorno^2.
# GM = k^2 è la definizione: è lo stesso valore che usa Horizons (DE440,
# 2.9591220828559e-4), e usarne un altro sposterebbe le posizioni di qualche
# decimillesimo di AU sui tempi lunghi dello screening.
K_GAUSS = 0.01720209895
GM_SUN = K_GAUSS * K_GAUSS
SQRT_GM = K_GAUSS

# Sopra questa eccentricità Newton su E degenera (E e M quasi non si
# distinguono vicino al perielio) e si passa alle variabili universali.
E_UNIVERSAL = 0.98

# Criteri di convergenza. Sono soglie assolute in radianti / AU^(1/2): a
# 1e-12 rad l'errore di posizione è sotto il micro-arcosecondo, cioè molto
# sotto qualunque cosa ci interessi, e si raggiunge in 4-5 iterazioni.
_TOL_ELLIPTIC = 1e-12
_MAX_ITER_ELLIPTIC = 60
_TOL_UNIVERSAL = 1e-11
_MAX_ITER_UNIVERSAL = 80

# Sotto questo |z| le formule chiuse di Stumpff si annullano per cancellazione
# (0/0) e si usa lo sviluppo in serie. Con i termini fino a z^4 il primo
# trascurato vale z^5/479001600: a |z| = 0.1 è 1e-14 relativo, cioè il raccordo
# fra i due rami è al livello dell'aritmetica in doppia precisione. Con un
# termine in meno il gradino era 2e-11, misurabile da un test.
_Z_SMALL = 0.1


# --------------------------------------------------------------------------
# Funzioni di Stumpff
# --------------------------------------------------------------------------

def stumpff_c(z):
    """C(z) = (1 - cos√z)/z, con i prolungamenti per z < 0 e z → 0."""
    z = np.asarray(z, dtype=float)
    out = np.empty_like(z)

    small = np.abs(z) < _Z_SMALL
    pos = (z >= _Z_SMALL)
    neg = (z <= -_Z_SMALL)

    zs = np.where(small, z, 0.0)
    out = np.where(
        small,
        0.5
        - zs / 24.0
        + zs**2 / 720.0
        - zs**3 / 40320.0
        + zs**4 / 3628800.0,
        0.0,
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        sz = np.sqrt(np.where(pos, z, 1.0))
        out = np.where(pos, (1.0 - np.cos(sz)) / np.where(pos, z, 1.0), out)
        sz = np.sqrt(np.where(neg, -z, 1.0))
        out = np.where(neg, (np.cosh(sz) - 1.0) / np.where(neg, -z, 1.0), out)
    return out


def stumpff_s(z):
    """S(z) = (√z - sin√z)/z^(3/2), con i prolungamenti per z < 0 e z → 0."""
    z = np.asarray(z, dtype=float)

    small = np.abs(z) < _Z_SMALL
    pos = (z >= _Z_SMALL)
    neg = (z <= -_Z_SMALL)

    zs = np.where(small, z, 0.0)
    out = np.where(
        small,
        1.0 / 6.0
        - zs / 120.0
        + zs**2 / 5040.0
        - zs**3 / 362880.0
        + zs**4 / 39916800.0,
        0.0,
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        sz = np.sqrt(np.where(pos, z, 1.0))
        out = np.where(pos, (sz - np.sin(sz)) / sz**3, out)
        sz = np.sqrt(np.where(neg, -z, 1.0))
        out = np.where(neg, (np.sinh(sz) - sz) / sz**3, out)
    return out


# --------------------------------------------------------------------------
# Ramo ellittico
# --------------------------------------------------------------------------

def solve_elliptic(m_rad, e):
    """Risolve M = E - e sin E per array di M ed e (0 <= e < 1).

    Newton con innesco `E0 = M + e sin M`, M riportata in [-π, π) perché la
    convergenza vicino al perielio dipende da quanto è buono l'innesco. Il
    ciclo è sulle iterazioni: a ogni passo si aggiorna *tutto* l'array e ci si
    ferma quando la correzione massima è sotto la tolleranza.
    """
    m = np.asarray(m_rad, dtype=float)
    e = np.asarray(e, dtype=float)
    m, e = np.broadcast_arrays(m, e)

    m = np.mod(m + np.pi, 2.0 * np.pi) - np.pi
    ecc_anom = m + e * np.sin(m)

    for _ in range(_MAX_ITER_ELLIPTIC):
        f = ecc_anom - e * np.sin(ecc_anom) - m
        fp = 1.0 - e * np.cos(ecc_anom)
        step = f / fp
        ecc_anom = ecc_anom - step
        if np.all(np.abs(step) < _TOL_ELLIPTIC):
            break
    return ecc_anom


def _state_elliptic(a, e, m_rad, i_rad, node_rad, argp_rad):
    ecc = solve_elliptic(m_rad, e)
    cos_e = np.cos(ecc)
    sin_e = np.sin(ecc)
    beta = np.sqrt(1.0 - e * e)

    x = a * (cos_e - e)
    y = a * beta * sin_e
    r = a * (1.0 - e * cos_e)

    fac = np.sqrt(GM_SUN * a) / r
    vx = -fac * sin_e
    vy = fac * beta * cos_e

    return _perifocal_to_ecliptic(x, y, vx, vy, i_rad, node_rad, argp_rad)


# --------------------------------------------------------------------------
# Ramo universale (Stumpff)
# --------------------------------------------------------------------------

def solve_universal(dt_days, q_au, e):
    """Anomalia universale x che risolve, contata dal perielio,

        √GM · Δt = q x + e x³ S(αx²)        con α = (1 - e)/q

    valida per qualunque conica: α > 0 ellisse, α = 0 parabola, α < 0 iperbole.
    Newton *incastrato in un intervallo*: F(x) è dispari e strettamente
    crescente (dF/dx = r > 0), quindi un intervallo che contiene la radice si
    trova raddoppiando, e quando il passo di Newton esce dall'intervallo si
    bisseca. Senza questa rete, per le iperboliche lontane dal perielio Newton
    scappa: qui la convergenza è garantita e non serve fidarsi.
    """
    dt = np.asarray(dt_days, dtype=float)
    q = np.asarray(q_au, dtype=float)
    e = np.asarray(e, dtype=float)
    dt, q, e = np.broadcast_arrays(dt, q, e)

    alpha = (1.0 - e) / q
    sign = np.where(dt < 0.0, -1.0, 1.0)
    target = np.abs(SQRT_GM * dt)          # F è dispari: si risolve in x > 0

    def f_of(x):
        z = alpha * x * x
        return q * x + e * x * x * x * stumpff_s(z) - target

    def r_of(x):
        z = alpha * x * x
        return q + e * x * x * stumpff_c(z)     # = dF/dx

    # Innesco: la soluzione esatta del caso parabolico (z = 0), che è una
    # cubica con radice reale in forma chiusa. Per e vicino a 1 è già quasi la
    # risposta; altrove serve solo a dare un ordine di grandezza al raddoppio.
    disc = np.sqrt(9.0 * target * target + 8.0 * q**3)
    x = np.cbrt(3.0 * target + disc) + np.cbrt(3.0 * target - disc)
    x = np.where(x > 0.0, x, np.maximum(target / np.maximum(q, 1e-12), 1e-12))

    lo = np.zeros_like(x)
    hi = np.array(x, dtype=float, copy=True)
    for _ in range(200):
        need = f_of(hi) < 0.0
        if not np.any(need):
            break
        hi = np.where(need, hi * 2.0, hi)

    x = 0.5 * (lo + hi)
    for _ in range(_MAX_ITER_UNIVERSAL):
        fx = f_of(x)
        lo = np.where(fx < 0.0, x, lo)
        hi = np.where(fx >= 0.0, x, hi)

        step = fx / r_of(x)
        nxt = x - step
        outside = (nxt <= lo) | (nxt >= hi)
        nxt = np.where(outside, 0.5 * (lo + hi), nxt)

        delta = np.abs(nxt - x)
        x = nxt
        if np.all(delta < _TOL_UNIVERSAL * np.maximum(1.0, np.abs(x))):
            break

    return sign * x


def _state_universal(q, e, dt_days, i_rad, node_rad, argp_rad):
    """Propaga dal perielio con f e g, dove lo stato iniziale è noto esatto.

    Al perielio la posizione è q lungo P̂ e la velocità è tutta lungo Q̂: non
    servono né `a` né l'anomalia media, che è precisamente il motivo per cui
    questo ramo sopravvive a e = 1.
    """
    alpha = (1.0 - e) / q
    x = solve_universal(dt_days, q, e)
    z = alpha * x * x
    c = stumpff_c(z)
    s = stumpff_s(z)

    r = q + e * x * x * c
    f = 1.0 - (x * x / q) * c
    g = dt_days - (x**3 / SQRT_GM) * s
    fdot = (SQRT_GM / (r * q)) * x * (z * s - 1.0)
    gdot = 1.0 - (x * x / r) * c

    v_peri = np.sqrt(GM_SUN * (1.0 + e) / q)   # modulo della velocità al perielio

    # Componenti nel piano orbitale: r0 = (q, 0), v0 = (0, v_peri).
    px = f * q
    py = g * v_peri
    vx = fdot * q
    vy = gdot * v_peri

    return _perifocal_to_ecliptic(px, py, vx, vy, i_rad, node_rad, argp_rad)


# --------------------------------------------------------------------------
# Rotazione al riferimento eclittico
# --------------------------------------------------------------------------

def _perifocal_to_ecliptic(px, py, vx, vy, i_rad, node_rad, argp_rad):
    """Rz(-Ω) Rx(-i) Rz(-ω) applicata come combinazione dei versori P̂ e Q̂.

    Si costruiscono i due versori invece delle tre matrici perché la componente
    z del piano orbitale è nulla per definizione: due prodotti invece di nove.
    """
    cos_o, sin_o = np.cos(node_rad), np.sin(node_rad)
    cos_w, sin_w = np.cos(argp_rad), np.sin(argp_rad)
    cos_i, sin_i = np.cos(i_rad), np.sin(i_rad)

    p_hat = np.stack(
        [
            cos_o * cos_w - sin_o * sin_w * cos_i,
            sin_o * cos_w + cos_o * sin_w * cos_i,
            sin_w * sin_i,
        ],
        axis=-1,
    )
    q_hat = np.stack(
        [
            -cos_o * sin_w - sin_o * cos_w * cos_i,
            -sin_o * sin_w + cos_o * cos_w * cos_i,
            cos_w * sin_i,
        ],
        axis=-1,
    )

    pos = px[..., None] * p_hat + py[..., None] * q_hat
    vel = vx[..., None] * p_hat + vy[..., None] * q_hat
    return pos, vel


# --------------------------------------------------------------------------
# Il punto d'ingresso
# --------------------------------------------------------------------------

def heliocentric_state(
    jd,
    *,
    epoch_jd,
    e,
    i_deg,
    node_deg,
    argp_deg,
    a_au=None,
    m_deg=None,
    q_au=None,
    tp_jd=None,
):
    """Posizione e velocità eliocentriche eclittiche J2000, in AU e AU/giorno.

    Accetta indifferentemente la parametrizzazione asteroidale `(a, M₀)` e
    quella cometaria `(q, tp)`: quella mancante si deriva, e il ramo di calcolo
    si sceglie *dopo*, sulla sola eccentricità. Chi chiama non deve sapere che
    esistono due rami.

    Restituisce due array di forma `(..., 3)`, dove `...` è il broadcast di
    tutti gli argomenti fra loro. Dove gli elementi non hanno senso (e < 0,
    q <= 0, e = 1 senza tp) escono NaN: un numero sbagliato è peggio di un
    buco, perché lo screening lo ordinerebbe insieme agli altri.
    """
    if (a_au is None or m_deg is None) and (q_au is None or tp_jd is None):
        raise ValueError("servono (a_au, m_deg) oppure (q_au, tp_jd)")

    jd = np.asarray(jd, dtype=float)
    epoch = np.asarray(epoch_jd, dtype=float)
    e = np.asarray(e, dtype=float)
    i_rad = np.radians(np.asarray(i_deg, dtype=float))
    node_rad = np.radians(np.asarray(node_deg, dtype=float))
    argp_rad = np.radians(np.asarray(argp_deg, dtype=float))

    nan = np.full((), np.nan)
    a = nan if a_au is None else np.asarray(a_au, dtype=float)
    m0 = nan if m_deg is None else np.asarray(m_deg, dtype=float)
    q = nan if q_au is None else np.asarray(q_au, dtype=float)
    tp = nan if tp_jd is None else np.asarray(tp_jd, dtype=float)

    jd, epoch, e, i_rad, node_rad, argp_rad, a, m0, q, tp = (
        np.broadcast_arrays(jd, epoch, e, i_rad, node_rad, argp_rad, a, m0, q, tp)
    )

    with np.errstate(invalid="ignore", divide="ignore"):
        # Riempimento incrociato: q dagli elementi asteroidali, a da quelli
        # cometari (che per e >= 1 resta NaN, e va bene: là non serve).
        q = np.where(np.isfinite(q), q, a * (1.0 - e))
        a = np.where(np.isfinite(a), a, np.where(e < 1.0, q / (1.0 - e), np.nan))

        n_rad = np.sqrt(GM_SUN / np.abs(a) ** 3)      # moto medio, rad/giorno
        m_at_epoch = np.radians(m0)

        # tp mancante: si conta dal perielio più vicino all'epoca, riportando
        # M in [-π, π). Serve solo al ramo universale con elementi asteroidali.
        tp = np.where(
            np.isfinite(tp),
            tp,
            epoch - (np.mod(m_at_epoch + np.pi, 2.0 * np.pi) - np.pi) / n_rad,
        )

        # M mancante: dalla distanza temporale dal perielio (comete ellittiche).
        m_now = np.where(
            np.isfinite(m_at_epoch),
            m_at_epoch + n_rad * (jd - epoch),
            n_rad * (jd - tp),
        )

        valid = (e >= 0.0) & (q > 0.0) & np.isfinite(q) & np.isfinite(jd)
        use_elliptic = valid & (e < E_UNIVERSAL) & (a > 0.0) & np.isfinite(m_now)
        use_universal = valid & ~use_elliptic & np.isfinite(tp)

        pos = np.full(jd.shape + (3,), np.nan)
        vel = np.full(jd.shape + (3,), np.nan)

        if np.any(use_elliptic):
            k = use_elliptic
            p, v = _state_elliptic(
                a[k], e[k], m_now[k], i_rad[k], node_rad[k], argp_rad[k]
            )
            pos[k], vel[k] = p, v

        if np.any(use_universal):
            k = use_universal
            p, v = _state_universal(
                q[k], e[k], jd[k] - tp[k], i_rad[k], node_rad[k], argp_rad[k]
            )
            pos[k], vel[k] = p, v

    return pos, vel
