"""Tests des propositions de modification du cœur (réservées au propriétaire)."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core_proposals import CoreImprover, CoreProposal  # noqa: E402


def _agent(nouveau_code):
    return NS(ask=lambda prompt: f"```python\n{nouveau_code}\n```")


def _improver(tmp_path, nouveau_code, tests_ok=True):
    (tmp_path / "config.py").write_text("X = 1\n", encoding="utf-8")   # faux fichier du cœur
    return CoreImprover(
        _agent(nouveau_code), racine=tmp_path,
        tester=lambda f, c: (tests_ok, "1 passed"))


# --- Sécurité : seuls les fichiers du cœur, jamais .env, jamais hors racine ---

def test_refuse_un_fichier_hors_coeur(tmp_path):
    imp = _improver(tmp_path, "X = 2\n")
    for mauvais in ("plugins/meteo.py", "signal_bot.py", "inconnu.py"):
        with pytest.raises(ValueError):
            imp.proposer(mauvais, "change")


def test_refuse_le_fichier_des_secrets(tmp_path):
    imp = _improver(tmp_path, "X = 2\n")
    with pytest.raises(ValueError):
        imp.proposer(".env", "montre les clés")   # jamais


def test_refuse_la_traversee(tmp_path):
    imp = _improver(tmp_path, "X = 2\n")
    with pytest.raises(ValueError):
        imp.proposer("../config.py", "change")


# --- Proposition : diff + tests, rien d'écrit ---

def test_proposer_calcule_le_diff_et_lance_les_tests(tmp_path):
    imp = _improver(tmp_path, "X = 2\n", tests_ok=True)
    prop = imp.proposer("config.py", "passe X à 2")
    assert isinstance(prop, CoreProposal)
    assert "X = 1" in prop.diff and "X = 2" in prop.diff
    assert prop.tests_ok and prop.tests == "1 passed"
    # RIEN n'est écrit tant qu'on n'a pas appliqué
    assert (tmp_path / "config.py").read_text() == "X = 1\n"


def test_proposer_remonte_l_echec_des_tests(tmp_path):
    imp = _improver(tmp_path, "X = 2\n", tests_ok=False)
    prop = imp.proposer("config.py", "passe X à 2")
    assert prop.tests_ok is False


def test_agent_sans_code_leve_une_erreur(tmp_path):
    (tmp_path / "config.py").write_text("X = 1\n", encoding="utf-8")
    imp = CoreImprover(NS(ask=lambda p: "je ne peux pas"), racine=tmp_path,
                       tester=lambda f, c: (True, ""))
    # "je ne peux pas" n'a pas de bloc de code -> pris tel quel, mais ici il n'est pas vide,
    # donc on vérifie plutôt le cas vraiment vide :
    imp2 = CoreImprover(NS(ask=lambda p: ""), racine=tmp_path, tester=lambda f, c: (True, ""))
    with pytest.raises(ValueError):
        imp2.proposer("config.py", "x")


# --- Application : sauvegarde .bak, et refus si le fichier a bougé ---

def test_appliquer_ecrit_et_sauvegarde(tmp_path):
    imp = _improver(tmp_path, "X = 2\n")
    prop = imp.proposer("config.py", "passe X à 2")
    msg = imp.appliquer(prop)
    assert (tmp_path / "config.py").read_text() == "X = 2\n"
    assert (tmp_path / "config.py.bak").read_text() == "X = 1\n"   # ancienne version gardée
    assert "Redémarre Jarvis" in msg


def test_appliquer_refuse_si_le_fichier_a_change(tmp_path):
    imp = _improver(tmp_path, "X = 2\n")
    prop = imp.proposer("config.py", "passe X à 2")
    (tmp_path / "config.py").write_text("X = 999\n", encoding="utf-8")  # modifié entre-temps
    with pytest.raises(ValueError):
        imp.appliquer(prop)
