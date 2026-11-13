"""Tests de la surveillance continue (SecurityWatcher)."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cyberwatch import SecurityWatcher  # noqa: E402


def test_notifie_integrite_et_sentinelle():
    envoyes = []
    integrity = NS(verifier=lambda: [(True, "fichier du cœur MODIFIÉ hors circuit : brain.py")])
    sentinel = NS(check=lambda: [(False, "un appareil inconnu est apparu")])
    w = SecurityWatcher(envoyes.append, sentinel=sentinel, integrity=integrity)
    nouvelles = w.un_tour()
    assert len(nouvelles) == 2
    assert any("🚨" in m and "brain.py" in m for m in envoyes)      # cœur = critique
    assert any("🛡️" in m and "appareil" in m for m in envoyes)      # info = non critique


def test_ne_notifie_pas_deux_fois_la_meme_alerte():
    envoyes = []
    integrity = NS(verifier=lambda: [(True, "fichier du cœur MODIFIÉ hors circuit : drone.py")])
    w = SecurityWatcher(envoyes.append, integrity=integrity)
    w.un_tour()
    w.un_tour()                 # même alerte au 2e tour
    assert len(envoyes) == 1    # signalée une seule fois


def test_les_alertes_critiques_sont_consignees():
    preuves = []
    evidence = NS(consigner=lambda m: preuves.append(m))
    integrity = NS(verifier=lambda: [(True, "fichier du cœur MODIFIÉ : brain.py")])
    sentinel = NS(check=lambda: [(False, "info non critique")])
    w = SecurityWatcher(lambda m: None, sentinel=sentinel, integrity=integrity, evidence=evidence)
    w.un_tour()
    assert preuves == ["fichier du cœur MODIFIÉ : brain.py"]   # seulement le critique


def test_un_composant_qui_plante_ne_casse_pas_le_tour():
    envoyes = []
    def boom():
        raise RuntimeError("psutil indisponible")
    sentinel = NS(check=boom)
    integrity = NS(verifier=lambda: [(True, "alerte cœur")])
    w = SecurityWatcher(envoyes.append, sentinel=sentinel, integrity=integrity)
    nouvelles = w.un_tour()     # la sentinelle plante, l'intégrité passe quand même
    assert any("alerte cœur" in m for m in envoyes)
    assert len(nouvelles) == 1
