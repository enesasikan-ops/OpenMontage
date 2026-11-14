"""Tests de l'apprentissage d'habitudes (explicable, local, propose sans agir)."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import habits  # noqa: E402
from habits import (Habit, HabitLearner, Suggester, build_habit_tools,  # noqa: E402
                    contexte, creneaux, est_allume, from_ha_history, meteo_a,
                    meteo_simple, moment, slots, timeline_meteo, transitions_on)

PARIS = ZoneInfo("Europe/Paris")


# --- Helpers de contexte ---

def test_moment():
    assert moment(3) == "nuit" and moment(9) == "matin"
    assert moment(14) == "après-midi" and moment(20) == "soir"


def test_meteo_simple():
    assert meteo_simple("rainy") == "pluie"
    assert meteo_simple("pouring") == "pluie"
    assert meteo_simple("snowy") == "neige"
    assert meteo_simple("sunny") == "sec"
    assert meteo_simple(None) is None


def test_contexte_mardi_soir_pluie():
    # 2024-01-02 est un mardi
    assert contexte(datetime(2024, 1, 2, 20), "pluie") == ("mardi", "soir", "pluie")


def test_est_allume():
    assert est_allume("on") and est_allume("heat")
    assert not est_allume("off") and not est_allume("unavailable")


# --- Apprentissage ---

def _slot(ctx, *actions):
    return {"contexte": ctx, "actions": set(actions)}


def test_apprend_support_et_confiance():
    CTX = ("mardi", "soir", "pluie")
    learner = HabitLearner()
    # 5 créneaux mardi-soir-pluie ; porche allumé 4 fois ; chauffage 1 fois
    learner.apprendre([
        _slot(CTX, "light.porche", "climate.salon"),
        _slot(CTX, "light.porche"),
        _slot(CTX, "light.porche"),
        _slot(CTX, "light.porche"),
        _slot(CTX),
    ])
    habs = {h.entity: h for h in learner.habitudes(support_min=3, confiance_min=0.6)}
    assert "light.porche" in habs
    porche = habs["light.porche"]
    assert porche.support == 4 and porche.total == 5
    assert abs(porche.confiance - 0.8) < 1e-9
    assert "climate.salon" not in habs          # support 1 : rejeté


def test_seuils_rejettent_le_hasard():
    CTX = ("lundi", "matin", "sec")
    learner = HabitLearner()
    learner.apprendre([_slot(CTX, "light.x")] + [_slot(CTX) for _ in range(9)])
    assert learner.habitudes(support_min=3, confiance_min=0.6) == []   # 1/10 : du bruit


def test_raison_lisible():
    h = Habit(contexte=("mardi", "soir", "pluie"), entity="light.porche",
              support=4, total=5, nom="Lumière du porche")
    r = h.raison()
    assert "mardis soir" in r and "pleut" in r
    assert "Lumière du porche" in r and "4 fois sur 5" in r


# --- Suggestion ---

def test_suggestion_propose_si_contexte_et_eteint():
    h = Habit(("mardi", "soir", "pluie"), "light.porche", 4, 5)
    s = Suggester([h])
    props = s.suggestions(("mardi", "soir", "pluie"), {"light.porche": "off"})
    assert [p.entity for p in props] == ["light.porche"]


def test_suggestion_rien_si_deja_allume():
    h = Habit(("mardi", "soir", "pluie"), "light.porche", 4, 5)
    assert Suggester([h]).suggestions(("mardi", "soir", "pluie"), {"light.porche": "on"}) == []


def test_suggestion_rien_si_autre_contexte():
    h = Habit(("mardi", "soir", "pluie"), "light.porche", 4, 5)
    assert Suggester([h]).suggestions(("lundi", "matin", "sec"), {"light.porche": "off"}) == []


# --- Lecture de l'historique ---

def test_transitions_on_fronts_montants():
    hist = [
        {"state": "off", "last_changed": "2024-01-02T18:00:00"},
        {"state": "on", "last_changed": "2024-01-02T20:00:00"},
        {"state": "on", "last_changed": "2024-01-02T20:30:00"},   # pas un nouveau front
        {"state": "off", "last_changed": "2024-01-02T23:00:00"},
        {"state": "on", "last_changed": "2024-01-09T20:00:00"},
    ]
    t = transitions_on(hist, PARIS)
    assert t == [datetime(2024, 1, 2, 20), datetime(2024, 1, 9, 20)]


def test_transitions_on_convertit_utc_en_local():
    # 19:00 UTC en hiver à Paris = 20:00 local
    hist = [{"state": "off", "last_changed": "2024-01-02T18:00:00+00:00"},
            {"state": "on", "last_changed": "2024-01-02T19:00:00+00:00"}]
    assert transitions_on(hist, PARIS) == [datetime(2024, 1, 2, 20)]


def test_meteo_a_lookup():
    tl = timeline_meteo([
        {"state": "sunny", "last_changed": "2024-01-02T08:00:00"},
        {"state": "rainy", "last_changed": "2024-01-02T17:00:00"},
    ], PARIS)
    assert meteo_a(tl, datetime(2024, 1, 2, 12)) == "sec"
    assert meteo_a(tl, datetime(2024, 1, 2, 20)) == "pluie"
    assert meteo_a(tl, datetime(2024, 1, 1, 0)) is None   # avant tout relevé


def test_creneaux_nombre():
    debut = datetime(2024, 1, 1, 0)
    fin = datetime(2024, 1, 3, 0)          # 2 jours pleins = 8 créneaux
    assert len(creneaux(debut, fin)) == 8


def test_slots_marque_les_actions():
    debut, fin = datetime(2024, 1, 2, 0), datetime(2024, 1, 3, 0)
    on_times = {"light.porche": [datetime(2024, 1, 2, 20)]}   # mardi soir
    res = slots(on_times, [], debut, fin)
    soir = [s for s in res if s["contexte"][1] == "soir"][0]
    assert soir["contexte"] == ("mardi", "soir", None)
    assert soir["actions"] == {"light.porche"}
    autres = [s for s in res if s["contexte"][1] != "soir"]
    assert all(s["actions"] == set() for s in autres)


# --- Intégration depuis l'historique HA (home simulé) ---

class FakeHome:
    def __init__(self, historique, etats=None):
        self._hist = historique
        self._etats = etats or []
        self.demande = None

    def history(self, entities, start_iso, end_iso=""):
        self.demande = (list(entities), start_iso)
        return self._hist

    def states(self):
        return self._etats


def _porche_les_mardis(n_allumes):
    """Historique : porche éteint 19h puis allumé 20h, pour n_allumes mardis de suite."""
    hist = []
    jour = datetime(2024, 1, 2)      # mardi
    for _ in range(n_allumes):
        hist.append({"state": "off", "last_changed": jour.replace(hour=19).isoformat()})
        hist.append({"state": "on", "last_changed": jour.replace(hour=20).isoformat()})
        jour += timedelta(days=7)
    hist[0]["entity_id"] = "light.porche"
    hist[0]["attributes"] = {"friendly_name": "Lumière du porche"}
    return hist


def test_from_ha_history_degage_une_habitude():
    historique = [_porche_les_mardis(7)]       # 7 mardis soirs d'affilée
    home = FakeHome(historique)
    now = datetime(2024, 3, 1)                  # ~60 j après le 1er mardi
    learner, noms = from_ha_history(home, ["light.porche"], "", jours=60, now=now)
    assert noms["light.porche"] == "Lumière du porche"
    habs = learner.habitudes(support_min=3, confiance_min=0.6, noms=noms)
    porche = [h for h in habs if h.entity == "light.porche"]
    assert porche and porche[0].contexte == ("mardi", "soir", None)
    assert porche[0].support >= 3


# --- Outils (lecture seule) ---

def _active(monkeypatch, home):
    monkeypatch.setattr(config, "HABITS", True)
    monkeypatch.setattr(config, "HABITS_ENTITES", ("light.porche",))
    monkeypatch.setattr(config, "HABITS_METEO", "")
    monkeypatch.setattr(config, "HABITS_JOURS", 60)
    monkeypatch.setattr(config, "HABITS_SUPPORT", 3)
    monkeypatch.setattr(config, "HABITS_CONFIANCE", 0.6)
    monkeypatch.setattr(habits, "_now", lambda: datetime(2024, 3, 1))


def test_pas_d_outils_sans_config(monkeypatch):
    monkeypatch.setattr(config, "HABITS", False)
    assert build_habit_tools(FakeHome([])) == []


def test_mes_habitudes_rapport(monkeypatch):
    home = FakeHome([_porche_les_mardis(7)])
    _active(monkeypatch, home)
    tools = {t.name: t for t in build_habit_tools(home)}
    out = tools["mes_habitudes"].run()
    assert "porche" in out.lower() and "mardi" in out


def test_anticiper_propose_quand_contexte(monkeypatch):
    # now = mardi soir ; porche actuellement éteint -> doit proposer
    home = FakeHome([_porche_les_mardis(7)], etats=[{"entity_id": "light.porche", "state": "off"}])
    _active(monkeypatch, home)
    monkeypatch.setattr(habits, "_now", lambda: datetime(2024, 3, 5, 20))   # 2024-03-05 = mardi, 20h
    tools = {t.name: t for t in build_habit_tools(home)}
    out = tools["anticiper_maintenant"].run()
    assert "porche" in out.lower()
