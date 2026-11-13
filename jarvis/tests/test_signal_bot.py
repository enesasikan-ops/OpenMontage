"""Tests du bot Signal deux-sens (SignalJarvis), transport simulé."""

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signal_bot import SignalJarvis  # noqa: E402

OWNER = "+33600000000"


class Sorties:
    """Collecte, de façon sûre pour les threads, tout ce que le bot envoie."""

    def __init__(self):
        self._msgs = []
        self._lock = threading.Lock()

    def __call__(self, texte, piece_jointe=None):
        with self._lock:
            self._msgs.append(texte)

    @property
    def tout(self):
        with self._lock:
            return list(self._msgs)

    def attendre(self, fragment, delai=2.0):
        fin = time.time() + delai
        while time.time() < fin:
            if any(fragment in m for m in self.tout):
                return True
            time.sleep(0.01)
        return False


def _bot(brain_reply=lambda t: "réponse", confirm_holder=None, owner=OWNER):
    sorties = Sorties()

    def brain_factory(confirm, on_status):
        if confirm_holder is not None:
            confirm_holder["confirm"] = confirm
        return NS(reply=brain_reply)

    return SignalJarvis(brain_factory, owner, sorties), sorties


# --- Sécurité ---

def test_ignore_un_numero_non_autorise():
    bot, sorties = _bot()
    bot.traiter("+33699999999", "coucou")
    time.sleep(0.05)
    assert sorties.tout == []   # rien envoyé à un inconnu


# --- Question normale ---

def test_question_passe_au_cerveau():
    bot, sorties = _bot(brain_reply=lambda t: f"tu as dit : {t}")
    bot.traiter(OWNER, "quelle heure est-il ?")
    assert sorties.attendre("tu as dit : quelle heure est-il ?")


# --- Confirmation d'action sensible (oui / non par texte) ---

def test_confirmation_oui():
    holder = {}
    resultats = {}

    def reply(texte):
        resultats["ok"] = holder["confirm"]("supprimer le fichier X")
        return "c'est fait" if resultats["ok"] else "annulé"

    bot, sorties = _bot(brain_reply=reply, confirm_holder=holder)
    bot.traiter(OWNER, "supprime X")
    assert sorties.attendre("⚠️")          # Jarvis a posé la question
    bot.traiter(OWNER, "oui")              # tu réponds oui
    assert sorties.attendre("c'est fait")
    assert resultats["ok"] is True


def test_confirmation_non():
    holder = {}

    def reply(texte):
        return "c'est fait" if holder["confirm"]("formater le disque") else "annulé"

    bot, sorties = _bot(brain_reply=reply, confirm_holder=holder)
    bot.traiter(OWNER, "formate")
    assert sorties.attendre("⚠️")
    bot.traiter(OWNER, "non")
    assert sorties.attendre("annulé")


# --- Propositions d'amélioration (pas de boutons : réponse texte) ---

def _proposals():
    vu = []
    return NS(
        activate=lambda key: vu.append(("activate", key)) or f"Activée n°{key}.",
        reject=lambda key: vu.append(("reject", key)) or f"Rejetée n°{key}.",
    ), vu


def test_proposition_valide_par_numero():
    bot, sorties = _bot()
    props, vu = _proposals()
    bot.proposals = props
    bot.send_proposal("Amélioration : ajoute la météo.", 3)
    bot.traiter(OWNER, "valide 3")
    assert ("activate", "3") in vu
    assert sorties.attendre("Activée n°3")


def test_proposition_rejet_par_numero():
    bot, sorties = _bot()
    props, vu = _proposals()
    bot.proposals = props
    bot.send_proposal("Amélioration : ajoute X.", 5)
    bot.traiter(OWNER, "rejette 5")
    assert ("reject", "5") in vu


def test_oui_simple_applique_la_derniere_proposition():
    bot, sorties = _bot()
    props, vu = _proposals()
    bot.proposals = props
    bot.send_proposal("Amélioration : ajoute X.", 7)
    bot.traiter(OWNER, "oui")              # sans numéro -> la dernière annoncée
    assert ("activate", "7") in vu


# --- Mode cœur : Gemini propose, tu lis le diff, tu valides ---

def _core(tests_ok=True):
    vu = []
    prop = NS(fichier="drone.py", ancien="a", nouveau="b", diff="--- a\n+++ b\n",
              tests_ok=tests_ok, tests="1 passed")
    return NS(
        proposer=lambda f, c: vu.append(("proposer", f, c)) or prop,
        appliquer=lambda p: vu.append(("appliquer", p.fichier)) or "drone.py modifié (.bak). Redémarre.",
    ), vu, prop


def test_coeur_propose_et_envoie_le_diff():
    bot, sorties = _bot()
    bot.core, vu, prop = _core()
    bot.traiter(OWNER, "cœur drone.py: augmente la limite")
    assert sorties.attendre("Proposition pour le CŒUR")
    assert ("proposer", "drone.py", "augmente la limite") in vu
    assert bot._core_pending is prop


def test_coeur_valide_applique():
    bot, sorties = _bot()
    bot.core, vu, prop = _core(tests_ok=True)
    bot.traiter(OWNER, "cœur drone.py: x")
    assert sorties.attendre("Proposition pour le CŒUR")
    bot.traiter(OWNER, "valide cœur")
    assert ("appliquer", "drone.py") in vu
    assert bot._core_pending is None


def test_coeur_refuse_si_tests_echouent():
    bot, sorties = _bot()
    bot.core, vu, prop = _core(tests_ok=False)
    bot.traiter(OWNER, "cœur drone.py: x")
    assert sorties.attendre("Proposition pour le CŒUR")
    bot.traiter(OWNER, "valide cœur")
    assert not any(a[0] == "appliquer" for a in vu)   # jamais appliqué si les tests cassent
    assert sorties.attendre("tests")


def test_coeur_rejet_n_applique_rien():
    bot, sorties = _bot()
    bot.core, vu, prop = _core()
    bot.traiter(OWNER, "cœur drone.py: x")
    assert sorties.attendre("Proposition pour le CŒUR")
    bot.traiter(OWNER, "rejette cœur")
    assert not any(a[0] == "appliquer" for a in vu)


def test_confirmation_prioritaire_sur_proposition():
    # Si une confirmation est en attente, « oui » répond à ELLE, pas à une proposition.
    holder = {}

    def reply(texte):
        return "ok" if holder["confirm"]("action sensible") else "non"

    bot, sorties = _bot(brain_reply=reply, confirm_holder=holder)
    props, vu = _proposals()
    bot.proposals = props
    bot.send_proposal("prop", 1)
    bot.traiter(OWNER, "fais l'action")
    assert sorties.attendre("⚠️")
    bot.traiter(OWNER, "oui")              # doit confirmer l'action, pas activer la prop
    assert sorties.attendre("ok")
    assert vu == []                        # la proposition n'a PAS été activée
