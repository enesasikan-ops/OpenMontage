"""Tests de la simulation de présence « organique » (mode vacances).

On vérifie l'invariant central : une simulation de présence ne fait JAMAIS d'action
dangereuse (serrure/portail), elle ne bouge que si TU l'as armée, et elle introduit de
la variation pour ne pas trahir sa régularité mécanique.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import presence_sim  # noqa: E402
from presence_sim import (  # noqa: E402
    _SERVICES,
    PresenceSimulator,
    PresenceWatcher,
    build_simulation_tools,
    make_presence_watcher,
    zones_config,
)

SOIR = datetime(2026, 1, 1, 20, 0)    # moment "soir"
NUIT = datetime(2026, 1, 1, 3, 0)     # moment "nuit"
SANS_SAUT = lambda: 0.9               # > _SAUT : on n'esquive jamais  # noqa: E731
TOUJOURS_SAUT = lambda: 0.0           # < _SAUT : on esquive toujours  # noqa: E731


class FakeHome:
    def __init__(self, boum=False):
        self.appels = []
        self.boum = boum

    def call(self, domaine, service, entity_id, **data):
        if self.boum:
            raise OSError("home assistant injoignable")
        self.appels.append((domaine, service, entity_id))


class FakeStore:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def save(self):
        pass


def _sim(zones, arme=True, horloge=lambda: SOIR, hasard=SANS_SAUT, home=None):
    home = home or FakeHome()
    return PresenceSimulator(home, zones, FakeStore({"vacances": arme}),
                             horloge=horloge, hasard=hasard), home


_SALON = [{"nom": "salon", "entite": "light.salon", "domaine": "light", "moments": {"soir"}}]


# --- Comportement de base ---

def test_soir_allume():
    sim, home = _sim(_SALON)
    assert sim.tic() == {"salon": "on"}
    assert ("light", "turn_on", "light.salon") in home.appels


def test_nuit_eteint():
    sim, home = _sim(_SALON, horloge=lambda: NUIT)
    assert sim.tic() == {"salon": "off"}
    assert ("light", "turn_off", "light.salon") in home.appels


def test_idempotent():
    # une fois la cible atteinte, on ne renvoie pas la même commande à chaque tour
    sim, home = _sim(_SALON)
    sim.tic()
    assert sim.tic() == {}
    assert len(home.appels) == 1


def test_non_arme_ne_fait_rien():
    sim, home = _sim(_SALON, arme=False)
    assert sim.tic() == {} and home.appels == []


def test_sans_zones_ne_fait_rien():
    sim, home = _sim([])
    assert sim.tic() == {} and home.appels == []


def test_saut_aleatoire_laisse_la_zone_tranquille():
    # la variation « organique » : parfois on ne touche pas la zone ce tour-ci
    sim, home = _sim(_SALON, hasard=TOUJOURS_SAUT)
    assert sim.tic() == {} and home.appels == []


def test_volet_ouvre_et_ferme():
    zones = [{"nom": "volet", "entite": "cover.salon", "domaine": "cover", "moments": {"soir"}}]
    sim, home = _sim(zones)
    assert sim.tic() == {"volet": "on"}
    assert ("cover", "open_cover", "cover.salon") in home.appels


def test_echec_call_ne_plante_pas_et_reessaiera():
    sim, home = _sim(_SALON, home=FakeHome(boum=True))
    assert sim.tic() == {}          # l'échec est avalé, pas de crash
    assert sim._applique == {}      # rien n'est marqué appliqué -> on réessaiera au tour suivant


# --- Armement (store) ---

def test_armer_desarmer_etat():
    sim, _ = _sim(_SALON, arme=False)
    assert "désactivée" in sim.etat()
    sim.armer()
    assert sim.arme and "ACTIVE" in sim.etat()
    sim.desarmer()
    assert not sim.arme and "désactivée" in sim.etat()


# --- zones_config : le filtre de sécurité ---

def test_zones_config_exclut_les_serrures(monkeypatch):
    monkeypatch.setattr(config, "SIM_ZONES", {
        "salon": {"entite": "light.salon", "moments": ["soir"]},
        "porte": {"entite": "lock.entree"},                      # serrure -> exclue
        "portail_dom": {"entite": "x", "domaine": "lock"},       # domaine serrure -> exclu
        "porte_maquillee": {"entite": "lock.garage", "domaine": "light"},  # maquillée -> exclue
        "clim": {"entite": "climate.salon"},                     # domaine non géré -> exclu
    })
    noms = {z["nom"] for z in zones_config()}
    assert noms == {"salon"}   # seule la lumière passe


def test_zones_config_moment_par_defaut(monkeypatch):
    monkeypatch.setattr(config, "SIM_ZONES", {"salon": {"entite": "light.salon"}})
    assert zones_config()[0]["moments"] == {"soir"}


def test_zones_config_ignore_entree_invalide(monkeypatch):
    monkeypatch.setattr(config, "SIM_ZONES", {"vide": {}, "pasdict": "light.salon"})
    assert zones_config() == []


def test_jamais_de_serrure_dans_les_services():
    # garde-fou structurel : aucune action de serrure n'existe dans la palette de simulation
    assert "lock" not in _SERVICES and "serrure" not in _SERVICES


def test_simulation_complete_ne_touche_jamais_une_serrure(monkeypatch):
    # un cycle complet (tous les moments), avec une serrure configurée : jamais ouverte/fermée
    monkeypatch.setattr(config, "SIM_ZONES", {
        "salon": {"entite": "light.salon", "moments": ["soir"]},
        "porte": {"entite": "lock.entree", "moments": ["nuit", "matin", "après-midi", "soir"]},
    })
    home = FakeHome()
    for heure in range(24):
        sim = PresenceSimulator(home, zones_config(), FakeStore({"vacances": True}),
                                horloge=lambda h=heure: datetime(2026, 1, 1, h, 0), hasard=SANS_SAUT)
        sim.tic()
    serrures = [a for a in home.appels if a[0] == "lock" or a[2].startswith("lock.")]
    assert serrures == []


# --- Outils & veilleur ---

def _activer(monkeypatch, tmp_path, zones=None):
    monkeypatch.setattr(config, "SIM", True)
    monkeypatch.setattr(config, "SIM_ZONES",
                        zones if zones is not None else {"salon": {"entite": "light.salon", "moments": ["soir"]}})
    monkeypatch.setattr(config, "SIM_FILE", tmp_path / "sim.json")
    monkeypatch.setattr(config, "SIM_INTERVALLE", 42.0)
    presence_sim._SIM = None   # casse le singleton entre les tests


def test_pas_d_outils_sans_config(monkeypatch):
    monkeypatch.setattr(config, "SIM", False)
    presence_sim._SIM = None
    assert build_simulation_tools(FakeHome()) == []


def test_pas_d_outils_sans_zone(monkeypatch, tmp_path):
    _activer(monkeypatch, tmp_path, zones={})   # activé mais aucune zone valable
    assert build_simulation_tools(FakeHome()) == []


def test_outils_arment_et_desarment(monkeypatch, tmp_path):
    _activer(monkeypatch, tmp_path)
    tools = {t.name: t for t in build_simulation_tools(FakeHome())}
    assert set(tools) == {"armer_vacances", "desarmer_vacances", "etat_vacances"}
    assert "désactivée" in tools["etat_vacances"].run()
    tools["armer_vacances"].run()
    assert "ACTIVE" in tools["etat_vacances"].run()
    tools["desarmer_vacances"].run()
    assert "désactivée" in tools["etat_vacances"].run()


def test_armement_survit_au_redemarrage(monkeypatch, tmp_path):
    _activer(monkeypatch, tmp_path)
    {t.name: t for t in build_simulation_tools(FakeHome())}["armer_vacances"].run()
    presence_sim._SIM = None   # simule un redémarrage : on relit le fichier
    tools = {t.name: t for t in build_simulation_tools(FakeHome())}
    assert "ACTIVE" in tools["etat_vacances"].run()


def test_make_watcher_none_sans_config(monkeypatch):
    monkeypatch.setattr(config, "SIM", False)
    presence_sim._SIM = None
    assert make_presence_watcher(FakeHome()) is None


def test_make_watcher_configure(monkeypatch, tmp_path):
    _activer(monkeypatch, tmp_path)
    w = make_presence_watcher(FakeHome())
    assert isinstance(w, PresenceWatcher) and w.interval_s == 42.0
