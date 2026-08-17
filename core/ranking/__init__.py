"""Dal «si vede» al «vale la pena»: feature 0-1, pesi dal profilo, e il perché.

Due moduli e nessuna sorpresa: `features.py` traduce una finestra osservativa
in numeri fra 0 e 1, `score.py` li combina con i pesi di `scoring_profile` e ne
tiene la scomposizione. Il punteggio non esce mai da solo (regola 5).
"""
from core.ranking.score import Profile, grade_of, score_window  # noqa: F401
