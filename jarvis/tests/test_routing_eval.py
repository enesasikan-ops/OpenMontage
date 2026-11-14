"""Tests du banc d'essai de compréhension (scoring du routage — mesure seulement)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routing_eval import charger, evaluer, rapport  # noqa: E402

JEU = [
    {"phrase": "ouvre le portail", "outil_attendu": "ouvrir"},
    {"phrase": "quelle heure est-il", "outil_attendu": "heure_et_date"},
    {"phrase": "comment ça va", "outil_attendu": None},
]


def _routeur(table):
    return lambda phrase: table.get(phrase)


def test_tout_bon():
    table = {"ouvre le portail": "ouvrir", "quelle heure est-il": "heure_et_date",
             "comment ça va": None}
    res = evaluer(JEU, _routeur(table))
    assert res["reussites"] == 3 and res["total"] == 3 and res["taux"] == 1.0
    assert res["echecs"] == []


def test_compte_les_echecs():
    table = {"ouvre le portail": "allumer",          # mauvais outil
             "quelle heure est-il": "heure_et_date",
             "comment ça va": "demander_a_claude"}    # aurait dû n'appeler aucun outil
    res = evaluer(JEU, _routeur(table))
    assert res["reussites"] == 1
    phrases_ko = {e["phrase"] for e in res["echecs"]}
    assert phrases_ko == {"ouvre le portail", "comment ça va"}
    assert res["echecs"][0]["attendu"] == "ouvrir" and res["echecs"][0]["predit"] == "allumer"


def test_routeur_qui_plante_compte_comme_echec():
    def boom(phrase):
        raise RuntimeError("modèle absent")
    res = evaluer([{"phrase": "x", "outil_attendu": "y"}], boom)
    assert res["reussites"] == 0 and "erreur" in res["echecs"][0]["predit"]


def test_jeu_vide():
    res = evaluer([], _routeur({}))
    assert res["total"] == 0 and res["taux"] == 0.0


def test_charger(tmp_path):
    p = tmp_path / "jeu.json"
    p.write_text(json.dumps([{"phrase": "a", "outil_attendu": "b"}]), "utf-8")
    assert charger(p) == [{"phrase": "a", "outil_attendu": "b"}]


def test_charger_format_enveloppe(tmp_path):
    p = tmp_path / "jeu.json"
    p.write_text(json.dumps({"exemples": [{"phrase": "a", "outil_attendu": None}]}), "utf-8")
    assert charger(p)[0]["phrase"] == "a"


def test_rapport_lisible():
    res = evaluer(JEU, _routeur({"ouvre le portail": "ouvrir"}))
    txt = rapport(res)
    assert "%" in txt and "Échecs" in txt and "attendu" in txt


def test_exemple_livre_est_valide():
    exemples = charger(Path(__file__).resolve().parents[1] / "routage_exemple.json")
    assert len(exemples) >= 5 and all("phrase" in e for e in exemples)
