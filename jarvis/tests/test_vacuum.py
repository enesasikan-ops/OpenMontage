"""Tests du contrôle de l'aspirateur robot (Valetudo via Home Assistant)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vacuum import VacuumControl, build_vacuum_tools  # noqa: E402

SEGMENTS = {"salon": "16", "cuisine": "17"}


class FauxHome:
    def __init__(self, avec_aspi=True):
        self.appels = []
        self._states = ([{"entity_id": "vacuum.robot",
                          "state": "docked",
                          "attributes": {"friendly_name": "Robot", "battery_level": 95}}]
                        if avec_aspi else [{"entity_id": "light.salon", "state": "on", "attributes": {}}])

    def states(self):
        return self._states

    def call(self, domaine, service, entity_id, **data):
        self.appels.append((domaine, service, entity_id, data))


def test_menage_complet():
    h = FauxHome()
    out = VacuumControl(h, SEGMENTS).aspirer()
    assert ("vacuum", "start", "vacuum.robot", {}) in h.appels
    assert "ménage" in out


def test_nettoyage_d_une_piece():
    h = FauxHome()
    out = VacuumControl(h, SEGMENTS).aspirer("salon")
    appel = next(a for a in h.appels if a[1] == "send_command")
    assert appel[3]["params"] == {"segment_ids": ["16"]}
    assert "salon" in out


def test_piece_approximative():
    h = FauxHome()
    # « le canapé du salon » -> doit retrouver le segment du salon
    VacuumControl(h, SEGMENTS).aspirer("canapé du salon")
    appel = next(a for a in h.appels if a[1] == "send_command")
    assert appel[3]["params"] == {"segment_ids": ["16"]}


def test_piece_inconnue():
    h = FauxHome()
    out = VacuumControl(h, SEGMENTS).aspirer("grenier")
    assert "grenier" in out and "salon" in out   # propose les pièces connues
    assert not any(a[1] == "send_command" for a in h.appels)   # rien envoyé


def test_retour_base_et_arret():
    h = FauxHome()
    v = VacuumControl(h, SEGMENTS)
    v.retour_base()
    v.arreter()
    services = [a[1] for a in h.appels]
    assert "return_to_base" in services and "stop" in services


def test_etat():
    assert "95%" in VacuumControl(FauxHome(), SEGMENTS).etat()


def test_sans_aspirateur():
    h = FauxHome(avec_aspi=False)
    assert "trouve pas d'aspirateur" in VacuumControl(h, SEGMENTS).aspirer("salon")
    assert h.appels == []


def test_outils():
    noms = {t.name for t in build_vacuum_tools(FauxHome(), SEGMENTS)}
    assert noms == {"aspirer", "arreter_aspirateur", "renvoyer_aspirateur", "etat_aspirateur"}


# --- Plusieurs aspirateurs ---

class FauxMaisonMulti:
    def __init__(self):
        self.appels = []
        self._states = [
            {"entity_id": "vacuum.rdc", "state": "docked",
             "attributes": {"friendly_name": "Robot du bas", "battery_level": 80}},
            {"entity_id": "vacuum.etage", "state": "cleaning",
             "attributes": {"friendly_name": "Robot du haut", "battery_level": 40}},
        ]

    def states(self):
        return self._states

    def call(self, domaine, service, entity_id, **data):
        self.appels.append((domaine, service, entity_id, data))


def test_menage_complet_lance_tous_les_aspirateurs():
    h = FauxMaisonMulti()
    out = VacuumControl(h, SEGMENTS).aspirer()
    lances = {a[2] for a in h.appels if a[1] == "start"}
    assert lances == {"vacuum.rdc", "vacuum.etage"} and "2 aspirateurs" in out


def test_cibler_un_aspirateur_par_nom():
    h = FauxMaisonMulti()
    VacuumControl(h, SEGMENTS).arreter(nom="haut")
    stops = [a for a in h.appels if a[1] == "stop"]
    assert len(stops) == 1 and stops[0][2] == "vacuum.etage"


def test_aspirateur_nomme_introuvable():
    h = FauxMaisonMulti()
    out = VacuumControl(h, SEGMENTS).aspirer(nom="garage")
    assert "garage" in out and not any(a[1] == "start" for a in h.appels)


def test_etat_liste_tous_les_aspirateurs():
    out = VacuumControl(FauxMaisonMulti(), SEGMENTS).etat()
    assert "Robot du bas" in out and "Robot du haut" in out and "40%" in out
