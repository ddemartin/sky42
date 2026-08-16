"""Il visibility engine: notte, geometria, cielo, limiti, finestre.

Non sa che cosa sia un asteroide (regola 4). Riceve un **sito** e array di
RA/Dec/Δ/V da un positioner qualunque, e restituisce quando e quanto bene
quella cosa si vede. Se qui compare la parola `orbit`, `tisserand` o `astorb`,
la stratificazione è rotta.
"""
