"""Tests du générateur de code (scaffold)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

JARVIS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(JARVIS))

from scaffold.__main__ import main  # noqa: E402
from scaffold.core import (Generator, Pack, ScaffoldError, camel, kebab, merge_manual,  # noqa: E402
                           pascal, snake, validate)

PACK = Pack.load("jarvis-capacite")
EXAMPLE = PACK.root / "exemple.yaml"


def config(**over):
    base = {"nom": "marees", "description": "Marées",
            "actions": [{"nom": "horaires", "description": "Horaires",
                         "parametres": [{"nom": "port", "type": "string"}]}]}
    base.update(over)
    return base


# --- Noms --------------------------------------------------------------------------------

@pytest.mark.parametrize("text, s, k, p, c", [
    ("météo marine", "m_t_o_marine", "m-t-o-marine", "MTOMarine", "mTOMarine"),
    ("UserProfile", "user_profile", "user-profile", "UserProfile", "userProfile"),
    ("order-service v2", "order_service_v2", "order-service-v2", "OrderServiceV2", "orderServiceV2"),
])
def test_name_filters(text, s, k, p, c):
    assert (snake(text), kebab(text), pascal(text), camel(text)) == (s, k, p, c)


# --- Validation ---------------------------------------------------------------------------

def test_validation_applies_defaults():
    cfg, errors = validate(config(), PACK.schema)
    assert errors == []
    assert cfg["auteur"] == "Jarvis" and cfg["documentation"] is True
    action = cfg["actions"][0]
    assert action["sensible"] is False
    assert action["parametres"][0]["requis"] is True


def test_validation_reports_all_errors_at_once():
    _, errors = validate({"nom": "Bad-Name", "actions": [{"nom": "x"}, {"nom": "x", "description": "d"}],
                          "inconnue": 1}, PACK.schema)
    text = "\n".join(errors)
    assert "« nom »" in text and "format attendu" in text
    assert "« description » est obligatoire" in text
    assert "actions[0].description" in text
    assert "doublons de « nom » : x" in text
    assert "inconnue" in text


def test_validation_types_and_choices():
    bad = config(documentation="oui",
                 actions=[{"nom": "a", "description": "d", "parametres": [{"nom": "p", "type": "date"}]}])
    _, errors = validate(bad, PACK.schema)
    text = "\n".join(errors)
    assert "documentation" in text and "type bool" in text
    assert "doit valoir l'un de" in text


# --- Zones manuelles -----------------------------------------------------------------------

def test_merge_keeps_manual_code_and_reports_lost_zones():
    old = "a\n    # >>> manuel: f\n    mon_code()\n    # <<< manuel: f\n# >>> manuel: g\nvieux\n# <<< manuel: g\n"
    new = "a2\n    # >>> manuel: f\n    pass\n    # <<< manuel: f\n"
    merged, lost = merge_manual(new, old)
    assert "mon_code()" in merged and "pass" not in merged and merged.startswith("a2")
    assert lost == ["g"]


def test_merge_html_zones():
    old = "<!-- >>> manuel: notes -->\nmes notes\n<!-- <<< manuel: notes -->\n"
    new = "# Titre\n<!-- >>> manuel: notes -->\n<!-- <<< manuel: notes -->\n"
    merged, _ = merge_manual(new, old)
    assert "mes notes" in merged and merged.startswith("# Titre")


# --- Plan / écriture -------------------------------------------------------------------------

def kinds(actions):
    return [a.kind for a in actions]


def test_plan_create_then_skip_force_update(tmp_path):
    gen = Generator(PACK, tmp_path)
    acts = gen.plan(config())
    assert kinds(acts) == ["creer"] * 3
    gen.apply(acts)
    assert kinds(gen.plan(config())) == ["identique"] * 3
    cfg2 = config(description="Marées v2")
    assert set(kinds(gen.plan(cfg2))) <= {"ignorer", "identique"}  # sans option : on ne touche à rien
    assert "ignorer" in kinds(gen.plan(cfg2))
    assert "ecraser" in kinds(gen.plan(cfg2, force=True))
    assert "mettre_a_jour" in kinds(gen.plan(cfg2, update=True))


def test_condition_skips_optional_file(tmp_path):
    acts = Generator(PACK, tmp_path).plan(config(documentation=False))
    assert not any(a.path.name == "README.md" for a in acts)


def test_output_outside_target_is_refused(tmp_path):
    pack = Pack(name="t", root=PACK.root, description="", schema={},
                files=[{"modele": "README.md.j2", "sortie": "../../evil.txt"}])
    with pytest.raises(ScaffoldError, match="hors du dossier cible"):
        Generator(pack, tmp_path).plan({})


def test_invalid_config_raises_before_writing(tmp_path):
    with pytest.raises(ScaffoldError, match="Configuration invalide"):
        Generator(PACK, tmp_path).plan({"nom": "x"})
    assert not any(tmp_path.iterdir())


def test_sensitive_action_gets_confirmation(tmp_path):
    cfg = config(actions=[{"nom": "supprimer", "description": "Supprime", "sensible": True}])
    content = next(a.content for a in Generator(PACK, tmp_path).plan(cfg) if a.path.name == "marees.py")
    assert "confirm=lambda **_:" in content


# --- De bout en bout : le code généré marche dans Jarvis --------------------------------------

def test_generated_capability_passes_its_tests_and_loads(tmp_path):
    assert main(["generer", str(EXAMPLE), "--sortie", str(tmp_path)]) == 0
    env = {**os.environ, "PYTHONPATH": str(JARVIS)}
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", str(tmp_path / "plugins")],
                         capture_output=True, text=True, env=env, cwd=str(JARVIS))
    assert run.returncode == 0, run.stdout + run.stderr

    from growth import load_plugins

    tools = {t.name: t for t in load_plugins(tmp_path / "plugins")}
    assert {"horaires_marees", "alerte_grande_maree"} <= set(tools)
    assert tools["alerte_grande_maree"].confirm is not None
    assert "pas encore implémentée" in tools["horaires_marees"].run()


def test_cli_errors_and_packs(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("nom: X\n", encoding="utf-8")
    assert main(["generer", str(bad), "--pack", "jarvis-capacite", "--sortie", str(tmp_path)]) == 2
    assert "Configuration invalide" in capsys.readouterr().err
    assert main(["generer", str(tmp_path / "absent.yaml")]) == 2
    assert main(["packs"]) == 0 and "jarvis-capacite" in capsys.readouterr().out
    assert main(["generer", str(EXAMPLE), "--pack", "inexistant"]) == 2
