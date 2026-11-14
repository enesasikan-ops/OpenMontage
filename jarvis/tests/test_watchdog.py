"""Tests du mode Sentinelle (réaction active anti-intrusion)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills import JsonStore  # noqa: E402
from watchdog import MESSAGE_DEFAUT, Watchdog, build_watchdog_tools  # noqa: E402


class FauxHome:
    def __init__(self):
        self.appels = []

    def call(self, domaine, service, entity_id, **data):
        self.appels.append((domaine, service, entity_id, data))


def _wd(tmp_path, settings=None, notify=None):
    return Watchdog(FauxHome(), notify or (lambda m: None),
                    JsonStore(tmp_path / "s.json", {}), settings or {})


REGLAGES = {
    "lumieres": ["light.exterieur"],
    "serrures": ["lock.porte"], "verrouiller": True,
    "haut_parleur": "media_player.jardin",
    "enregistrement_service": "switch.turn_on", "enregistrement_entite": "switch.rec",
}


# --- Armement ---

def test_armer_desarmer_persiste(tmp_path):
    wd = _wd(tmp_path)
    assert not wd.arme
    wd.armer()
    assert wd.arme
    # relu du disque
    wd2 = Watchdog(FauxHome(), lambda m: None, JsonStore(tmp_path / "s.json", {}), {})
    assert wd2.arme
    wd.desarmer()
    assert not wd.arme


# --- La réaction ne part que si armé ET inconnu ---

def test_pas_de_reaction_si_desarme(tmp_path):
    wd = _wd(tmp_path, REGLAGES)
    assert wd.sur_intrusion(None, "jardin", False) == []   # désarmé
    assert wd.home.appels == []


def test_pas_de_reaction_sur_personne_connue(tmp_path):
    wd = _wd(tmp_path, REGLAGES)
    wd.armer()
    assert wd.sur_intrusion("carlos", "jardin", True) == []  # connu
    assert wd.home.appels == []


def test_reaction_complete_sur_inconnu(tmp_path):
    alertes = []
    wd = _wd(tmp_path, REGLAGES, notify=alertes.append)
    wd.armer()
    faites = wd.sur_intrusion(None, "portail", False)
    services = [(d, s) for d, s, _, _ in wd.home.appels]
    assert ("light", "turn_on") in services        # lumières
    assert ("lock", "lock") in services            # verrouillage
    assert ("switch", "turn_on") in services        # enregistrement
    assert ("tts", "google_translate_say") in services  # sommation
    assert "lumières extérieures" in faites and "sommation vocale" in faites
    assert alertes and "INTRUSION" in alertes[0] and "portail" in alertes[0]
    # La sommation ne prétend PAS que la police est prévenue, et l'alerte conseille d'appeler
    tts = next(data for d, s, e, data in wd.home.appels if d == "tts")
    assert "police" not in tts["message"].lower()
    assert "police" in alertes[0].lower()           # l'alerte, elle, te dit d'appeler la police


def test_verrouillage_optionnel(tmp_path):
    reglages = dict(REGLAGES, verrouiller=False)
    wd = _wd(tmp_path, reglages)
    wd.armer()
    wd.sur_intrusion(None, "jardin", False)
    assert not any(d == "lock" for d, _, _, _ in wd.home.appels)   # pas de verrouillage


def test_message_personnalise(tmp_path):
    reglages = dict(REGLAGES, message="Partez immédiatement.")
    wd = _wd(tmp_path, reglages)
    wd.armer()
    wd.sur_intrusion(None, "jardin", False)
    tts = next(data for d, s, e, data in wd.home.appels if d == "tts")
    assert tts["message"] == "Partez immédiatement."


def test_message_defaut_dissuasif(tmp_path):
    wd = _wd(tmp_path, {"haut_parleur": "media_player.x"})
    wd.armer()
    wd.sur_intrusion(None, "jardin", False)
    tts = next(data for d, s, e, data in wd.home.appels if d == "tts")
    assert tts["message"] == MESSAGE_DEFAUT


# --- Outils ---

def test_outils():
    wd = Watchdog(FauxHome(), lambda m: None, JsonStore(Path("/tmp/none.json"), {}), {})
    noms = {t.name for t in build_watchdog_tools(wd)}
    assert noms == {"armer_surveillance", "desarmer_surveillance", "etat_surveillance"}


def test_sur_son_declenche_si_arme(tmp_path):
    alertes = []
    wd = _wd(tmp_path, REGLAGES, notify=alertes.append)
    assert wd.sur_son("bris de glace") == []        # désarmé : rien
    wd.armer()
    faites = wd.sur_son("bris de glace")
    assert "lumières extérieures" in faites
    assert alertes and "Bris de glace" in alertes[-1] and "police" in alertes[-1].lower()
