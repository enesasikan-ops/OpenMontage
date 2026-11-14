"""Tests de la mémoire associative (liens.py) : relier les souvenirs entre eux.

On vérifie les deux régimes : liens par mots partagés (local, défaut) et liens
sémantiques par embeddings (modèle injecté — aucun réseau dans les tests), plus le
repli propre quand les embeddings échouent.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from archive import Archive  # noqa: E402
from liens import AssociativeMemory, build_link_tools  # noqa: E402
from people import PeopleMemory  # noqa: E402


# --- Mode « mots partagés » (défaut, sans embeddings) ---

def test_relie_par_mots_partages():
    items = [
        {"texte": "Carlos aime le café du matin", "origine": "fait"},
        {"texte": "le café du matin me réveille", "origine": "archive"},
        {"texte": "la tondeuse coupe l'herbe", "origine": "fait"},
    ]
    am = AssociativeMemory(items)              # mode mots
    r = am.relier("Carlos")
    assert r["ancres"] and r["ancres"][0]["texte"] == "Carlos aime le café du matin"
    liens = {lien["texte"] for lien in r["ancres"][0]["liens"]}
    assert "le café du matin me réveille" in liens      # relié par {café, matin}
    assert "la tondeuse coupe l'herbe" not in liens      # aucun mot en commun


def test_seuil_mots_respecte():
    items = [
        {"texte": "Carlos aime le café du matin"},
        {"texte": "le café du matin me réveille"},   # 2 mots partagés (café, matin)
    ]
    # avec un seuil de 3 mots partagés, le lien disparaît
    r = AssociativeMemory(items, seuil_mots=3).relier("Carlos")
    assert r["ancres"][0]["liens"] == []


def test_sujet_sans_correspondance():
    items = [{"texte": "la piscine est chauffée"}]
    assert AssociativeMemory(items).relier("astronomie")["ancres"] == []


def test_sujet_et_items_vides():
    assert AssociativeMemory([]).relier("quoi que ce soit")["ancres"] == []
    assert AssociativeMemory([{"texte": "un fait"}]).relier("")["ancres"] == []
    assert AssociativeMemory([{"texte": "un fait"}]).texte_rappel("") == ""


# --- Mode sémantique (embeddings injectés) ---

def _fake_embed(textes):
    def vec(t):
        t = t.lower()
        if "chat" in t or "félin" in t or "felin" in t:
            return [1.0, 0.0, 0.0]
        if "voiture" in t or "route" in t:
            return [0.0, 0.0, 1.0]
        return [0.0, 1.0, 0.0]
    return [vec(t) for t in textes]


def test_lien_semantique_sans_mot_commun():
    # « chat » et « félin » ne partagent aucun mot, mais sont proches par le SENS
    items = [
        {"texte": "le chat dort sur le canapé", "origine": "fait"},
        {"texte": "le félin se repose au soleil", "origine": "archive"},
        {"texte": "la voiture roule vite", "origine": "fait"},
    ]
    # mode mots : aucun lien chat<->félin
    tous_mots = _tous(AssociativeMemory(items).relier("le chat"))
    assert "le félin se repose au soleil" not in tous_mots

    # mode embeddings : chat et félin se rejoignent, la voiture reste à l'écart
    tous_sem = _tous(AssociativeMemory(items, embed=_fake_embed).relier("le chat"))
    assert "le félin se repose au soleil" in tous_sem
    assert "la voiture roule vite" not in tous_sem


def _tous(resultat):
    textes = {a["texte"] for a in resultat["ancres"]}
    textes |= {lien["texte"] for a in resultat["ancres"] for lien in a["liens"]}
    return textes


def test_repli_propre_si_embeddings_echouent():
    def embed_ko(_textes):
        raise RuntimeError("ollama injoignable")
    items = [
        {"texte": "Carlos aime le café du matin"},
        {"texte": "le café du matin me réveille"},
    ]
    am = AssociativeMemory(items, embed=embed_ko)
    assert am._vecs is None                       # on est retombé en mode mots
    r = am.relier("Carlos")                        # et ça marche quand même
    assert "le café du matin me réveille" in _tous(r)


def test_repli_si_embeddings_incoherents():
    # le modèle renvoie moins de vecteurs que d'items -> on ignore et on reste en mots
    am = AssociativeMemory([{"texte": "a b c"}, {"texte": "a b d"}],
                           embed=lambda t: [[1.0, 0.0]])
    assert am._vecs is None


# --- Outil, câblé sur les trois sources locales ---

def test_outil_relie_les_trois_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARCHIVE_FILE", tmp_path / "archive.json")
    monkeypatch.setattr(config, "PEOPLE_FILE", tmp_path / "personnes.json")
    monkeypatch.setattr(config, "EMBED_MODEL", "")   # mode mots, aucun réseau

    Archive(config.ARCHIVE_FILE).archiver("le café du matin me réveille toujours")
    PeopleMemory(config.PEOPLE_FILE).remember("Carlos", "préfère le café sans sucre")
    memory = types.SimpleNamespace(facts=["Carlos aime le café du matin"])

    tool = {t.name: t for t in build_link_tools(memory)}["relier_souvenirs"]
    out = tool.run(sujet="Carlos")
    assert "café" in out.lower()                 # il relie bien les souvenirs autour du café
    assert "Je relie" in out or "je relie" in out


def test_outil_repond_proprement_quand_rien():
    memory = types.SimpleNamespace(facts=[])
    tool = {t.name: t for t in build_link_tools(memory)}["relier_souvenirs"]
    assert "ne relie rien" in tool.run(sujet="quoi que ce soit").lower()
