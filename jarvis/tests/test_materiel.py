"""Tests de la surveillance matérielle et des initiatives d'auto-protection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import config  # noqa: E402
import materiel  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_protection():
    yield
    materiel._PROTECTION.maj("ok", False)   # ne pas laisser « sous pression » fuiter aux autres tests
    materiel._MON = None
from materiel import (  # noqa: E402
    HardwareWatcher,
    MaterielMonitor,
    build_materiel_tools,
    evaluer,
    make_materiel_watcher,
    parse_meminfo,
    sous_pression,
)

SEUILS = {"temp_warn": 75.0, "temp_crit": 85.0, "disque_warn": 85.0,
          "disque_crit": 95.0, "ram_warn": 15.0, "ram_crit": 7.0}

MEMINFO = """MemTotal:       16384000 kB
MemFree:         1000000 kB
MemAvailable:    8192000 kB
SwapTotal:       2000000 kB
SwapFree:        1500000 kB
"""


# --- parsing ---

def test_parse_meminfo():
    ram, swap = parse_meminfo(MEMINFO)
    assert ram == 50.0 and swap == 25.0


def test_parse_meminfo_sans_swap():
    ram, swap = parse_meminfo("MemTotal: 1000 kB\nMemAvailable: 500 kB\n")
    assert ram == 50.0 and swap == 0.0


# --- évaluation ---

def test_tout_va_bien():
    niveau, alertes, pression = evaluer({"cpu_temp": 40, "disques": {"/": 50}, "ram_dispo": 60}, **SEUILS)
    assert niveau == "ok" and alertes == [] and pression is False


def test_surchauffe_critique():
    niveau, alertes, pression = evaluer({"cpu_temp": 90}, **SEUILS)
    assert niveau == "critique" and pression and alertes[0][0] is True and "CRITIQUE" in alertes[0][1]


def test_temperature_elevee_est_une_pression():
    niveau, alertes, pression = evaluer({"cpu_temp": 78}, **SEUILS)
    assert niveau == "attention" and pression and alertes[0][0] is False


def test_disque_presque_plein():
    niveau, alertes, _ = evaluer({"disques": {"/": 97}}, **SEUILS)
    assert niveau == "critique" and alertes[0][0] is True


def test_ram_epuisee():
    niveau, _, pression = evaluer({"ram_dispo": 5}, **SEUILS)
    assert niveau == "critique" and pression


def test_smart_defaillant():
    niveau, alertes, pression = evaluer({"smart": "FAILED"}, **SEUILS)
    assert niveau == "critique" and pression and "SMART" in alertes[0][1]


def test_niveau_est_le_pire():
    # température élevée (attention) + disque plein (critique) -> critique
    niveau, _, _ = evaluer({"cpu_temp": 78, "disques": {"/": 99}}, **SEUILS)
    assert niveau == "critique"


# --- Monitor : alerte, mémoire de protection, dédup ---

def test_check_alerte_et_met_a_jour_la_protection():
    materiel._PROTECTION.maj("ok", False)
    mon = MaterielMonitor(lambda: {"cpu_temp": 90, "disques": {}, "ram_dispo": 50}, SEUILS)
    out = mon.check()
    assert out and out[0][0] is True
    assert materiel._PROTECTION.sous_pression and sous_pression() is True
    assert mon.check() == []                   # déjà vu : pas de spam


def test_etat_lisible():
    mon = MaterielMonitor(lambda: {"cpu_temp": 42, "disques": {"/": 50},
                                   "ram_dispo": 60, "charge": 0.5, "smart": "PASSED"}, SEUILS)
    s = mon.etat()
    assert "CPU 42" in s and "tout va bien" in s


# --- Initiative d'auto-protection ---

def test_sous_pression_declenche_le_delestage():
    materiel._PROTECTION.maj("ok", False)
    MaterielMonitor(lambda: {"cpu_temp": 90}, SEUILS).check()
    assert sous_pression() is True             # les tâches lourdes (nuit) vont se reporter
    materiel._PROTECTION.maj("ok", False)      # retour au calme
    assert sous_pression() is False


def test_arret_de_protection_opt_in_sur_surchauffe():
    appels, annonces = [], []
    mon = MaterielMonitor(lambda: {"cpu_temp": 95}, SEUILS,
                          arreter=lambda d: appels.append(d), arret_actif=True,
                          arret_delai=30.0, annoncer=annonces.append)
    mon.check()
    assert appels == [30.0] and annonces and "Arrêt de protection" in annonces[0]
    mon.check()                                 # une seule fois, pas en boucle
    assert appels == [30.0]


def test_pas_d_arret_si_non_active():
    appels = []
    mon = MaterielMonitor(lambda: {"cpu_temp": 95}, SEUILS,
                          arreter=lambda d: appels.append(d), arret_actif=False)
    mon.check()
    assert appels == []                         # sans opt-in : on alerte, on n'éteint pas


# --- câblage ---

def test_outils_et_watcher_gates(monkeypatch):
    monkeypatch.setattr(config, "MATERIEL", False)
    materiel._MON = None
    assert build_materiel_tools() == []
    assert make_materiel_watcher(lambda m: None) is None


def test_outil_present_et_watcher(monkeypatch):
    monkeypatch.setattr(config, "MATERIEL", True)
    monkeypatch.setattr(config, "MAT_SMART_DEV", "")
    monkeypatch.setattr(config, "MAT_ARRET", False)
    monkeypatch.setattr(config, "MAT_ARRET_DELAI", 60.0)
    monkeypatch.setattr(config, "MATERIEL_INTERVALLE", 30.0)
    monkeypatch.setattr(config, "MAT_DISQUE_CHEMINS", ("/",))
    materiel._MON = None
    assert {t.name for t in build_materiel_tools()} == {"etat_materiel"}
    w = make_materiel_watcher(lambda m: None)
    assert isinstance(w, HardwareWatcher) and w.interval_s == 30.0
