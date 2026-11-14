"""Tests de la corrélation anti-force-brute."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bruteforce  # noqa: E402
from bruteforce import BruteForceDetector, build_bruteforce_tools, detecteur  # noqa: E402


def test_sous_le_seuil_pas_d_alerte():
    t = [0.0]
    d = BruteForceDetector(seuil=3, fenetre_s=60, horloge=lambda: t[0])
    assert d.enregistrer("1.2.3.4") is None
    assert d.enregistrer("1.2.3.4") is None


def test_seuil_atteint_declenche_et_notifie():
    t, vus = [0.0], []
    d = BruteForceDetector(notify=vus.append, seuil=3, fenetre_s=60, horloge=lambda: t[0])
    d.enregistrer("1.2.3.4")
    d.enregistrer("1.2.3.4")
    msg = d.enregistrer("1.2.3.4")
    assert msg and "Force brute" in msg
    assert vus and vus[0].startswith("🚨")
    assert "bloque 1.2.3.4" in msg          # source IP → on propose le blocage


def test_fenetre_glissante_oublie_les_vieux_echecs():
    t = [0.0]
    d = BruteForceDetector(seuil=3, fenetre_s=10, horloge=lambda: t[0])
    d.enregistrer("x"); t[0] = 5; d.enregistrer("x")
    t[0] = 20
    assert d.enregistrer("x") is None        # les deux premiers sont hors fenêtre


def test_cooldown_evite_le_spam_puis_re_alerte():
    t = [0.0]
    d = BruteForceDetector(seuil=2, fenetre_s=600, cooldown_s=100, horloge=lambda: t[0])
    d.enregistrer("x")
    assert d.enregistrer("x")                 # alerte à t=0
    t[0] = 2
    assert d.enregistrer("x") is None         # encore en cooldown
    t[0] = 150
    assert d.enregistrer("x")                 # cooldown passé → ré-alerte


def test_source_non_ip_sans_proposition_de_blocage():
    d = BruteForceDetector(seuil=1, horloge=lambda: 0.0)
    msg = d.enregistrer("aa:bb:cc:dd:ee:ff")   # une MAC (RADIUS), pas une IP
    assert "Force brute" in msg and "bloque" not in msg


def test_rapport_et_actifs():
    t = [0.0]
    d = BruteForceDetector(seuil=99, horloge=lambda: t[0])
    for _ in range(4):
        d.enregistrer("9.9.9.9")
    assert d.actifs(minimum=3) == [(4, "9.9.9.9")]
    assert "9.9.9.9" in d.rapport()


def test_singleton_fixe_notify_une_fois():
    bruteforce._DET = None
    f = lambda m: None  # noqa: E731
    d1 = detecteur(notify=f)
    d2 = detecteur()
    assert d1 is d2 and d1.notify is f


def test_outil_present():
    bruteforce._DET = None
    tools = {t.name: t for t in build_bruteforce_tools()}
    assert "point_force_brute" in tools
    assert "Aucune" in tools["point_force_brute"].run()
