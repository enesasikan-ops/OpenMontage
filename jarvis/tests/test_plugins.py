"""Tests du gestionnaire de plugins à chargement à chaud (et de son couplage au générateur)."""

import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

JARVIS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(JARVIS))

from brain import Brain  # noqa: E402
from memory import Memory  # noqa: E402
from plugin_manager import PluginManager, build_plugin_tools, generate_and_load  # noqa: E402
from tools import Tool  # noqa: E402

TEMPLATE = '''from tools import Tool

PLUGIN = {{"version": "{version}"}}


def build_tools():
    return [Tool(name="{tool}", description="outil de test",
                 parameters={{"type": "object", "properties": {{}}, "required": []}},
                 run=lambda: "{answer}")]
'''


def write(plugins: Path, name: str, tool="saluer", answer="bonjour", version="1", body=None):
    folder = plugins / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.py").write_text(body if body is not None else
                                       TEMPLATE.format(tool=tool, answer=answer, version=version),
                                       encoding="utf-8")
    return folder


def core_tool(name="heure"):
    return Tool(name=name, description="cœur", parameters={"type": "object", "properties": {}, "required": []},
                run=lambda: "cœur")


def fake_brain(tools):
    return NS(tools=dict(tools))


@pytest.fixture
def plugins(tmp_path):
    return tmp_path / "plugins"


def test_new_plugin_is_loaded_and_reaches_the_brain(plugins):
    brain = fake_brain({"heure": core_tool()})
    m = PluginManager(plugins)
    m.attach(brain)
    write(plugins, "salut")
    report = m.reload()
    assert report["charges"] == ["salut"]
    assert set(brain.tools) == {"heure", "saluer"}
    assert brain.tools["saluer"].run() == "bonjour"


def test_hot_reload_on_code_change(plugins):
    brain = fake_brain({"heure": core_tool()})
    m = PluginManager(plugins)
    m.attach(brain)
    write(plugins, "salut", answer="bonjour", version="1")
    m.reload()
    write(plugins, "salut", answer="merhaba", version="2")      # le code change, Jarvis tourne
    report = m.reload()
    assert report["recharges"] == ["salut"]
    assert brain.tools["saluer"].run() == "merhaba"
    assert "salut v2" in m.status_text()


def test_unchanged_plugin_is_not_reloaded(plugins):
    m = PluginManager(plugins)
    write(plugins, "salut")
    m.reload()
    assert m.reload() == {"charges": [], "recharges": [], "decharges": [], "erreurs": {}}


def test_broken_update_keeps_previous_version(plugins):
    brain = fake_brain({})
    m = PluginManager(plugins, core_names={"heure"})
    m.attach(brain)
    write(plugins, "salut", answer="v1 ok")
    m.reload()
    write(plugins, "salut", body="def build_tools(:\n")           # erreur de syntaxe
    report = m.reload()
    assert "salut" in report["erreurs"] and "erreur au chargement" in report["erreurs"]["salut"]
    assert brain.tools["saluer"].run() == "v1 ok"                  # rollback : l'ancienne reste
    assert "l'ancienne version reste active" in m.status_text()
    assert m.reload()["erreurs"] == {}                             # pas de retentative en boucle
    write(plugins, "salut", answer="v2 réparée")                   # on corrige
    assert m.reload()["recharges"] == ["salut"]
    assert brain.tools["saluer"].run() == "v2 réparée"
    assert m.errors == {}


def test_removed_plugin_is_unloaded_and_cleans_up(plugins, tmp_path):
    marker = tmp_path / "unloaded.txt"
    body = TEMPLATE.format(tool="saluer", answer="x", version="1") + (
        f"\n\ndef on_unload():\n    open({str(marker)!r}, 'w').write('bye')\n")
    brain = fake_brain({})
    m = PluginManager(plugins)
    m.attach(brain)
    folder = write(plugins, "salut", body=body)
    m.reload()
    shutil.rmtree(folder)
    assert m.reload()["decharges"] == ["salut"]
    assert "saluer" not in brain.tools
    assert marker.read_text() == "bye"                            # le plugin a libéré ses ressources


@pytest.mark.parametrize("body, expected", [
    ("x = 1\n", "aucun outil"),
    ("def build_tools():\n    return ['pas un outil']\n", "doivent renvoyer des Tool"),
    ("def build_tools():\n    raise RuntimeError('boum')\n", "build_tools() a échoué"),
])
def test_invalid_plugins_are_rejected(plugins, body, expected):
    m = PluginManager(plugins)
    write(plugins, "mauvais", body=body)
    report = m.reload()
    assert expected.replace("doivent", "doit") in report["erreurs"]["mauvais"] or expected in report["erreurs"]["mauvais"]
    assert m.tools() == {}


def test_plugin_cannot_override_core(plugins):
    brain = fake_brain({"heure": core_tool()})
    m = PluginManager(plugins)
    m.attach(brain)
    write(plugins, "pirate", tool="heure", answer="piraté")
    report = m.reload()
    assert "existe déjà dans le cœur" in report["erreurs"]["pirate"]
    assert brain.tools["heure"].run() == "cœur"


def test_two_plugins_cannot_share_a_tool_name(plugins):
    m = PluginManager(plugins)
    write(plugins, "aaa", tool="saluer")
    write(plugins, "bbb", tool="saluer")
    report = m.reload()
    assert report["charges"] == ["aaa"]
    assert "déjà fourni par un autre plugin" in report["erreurs"]["bbb"]


def test_invalid_folder_name(plugins):
    m = PluginManager(plugins)
    write(plugins, "Mauvais-Nom")
    assert "nom de dossier invalide" in m.reload()["erreurs"]["Mauvais-Nom"]


def test_multi_file_plugin(plugins):
    folder = plugins / "calcul"
    folder.mkdir(parents=True)
    (folder / "aide.py").write_text("def double(x):\n    return x * 2\n", encoding="utf-8")
    (folder / "calcul.py").write_text(
        "from tools import Tool\nfrom aide import double\n\n"
        "def build_tools():\n    return [Tool(name='doubler', description='d', "
        "parameters={'type': 'object', 'properties': {}, 'required': []}, run=lambda: str(double(21)))]\n",
        encoding="utf-8")
    m = PluginManager(plugins)
    m.reload()
    assert m.tools()["doubler"].run() == "42"


def test_watcher_picks_up_new_plugin_without_restart(plugins):
    brain = fake_brain({"heure": core_tool()})
    m = PluginManager(plugins, interval_s=0.05)
    m.attach(brain)
    m.start()
    try:
        write(plugins, "salut", answer="à chaud")
        deadline = time.time() + 5
        while "saluer" not in brain.tools and time.time() < deadline:
            time.sleep(0.05)
        assert brain.tools["saluer"].run() == "à chaud"
    finally:
        m.stop()


def test_brain_uses_hot_loaded_tool_mid_conversation(plugins, tmp_path):
    replies = [{"content": "salut"},
               {"content": "", "tool_calls": [{"function": {"name": "saluer", "arguments": {}}}]},
               {"content": "fini"}]

    class Client:
        def chat(self, model, messages, tools, **k):
            return {"message": replies.pop(0)}

    brain = Brain(Client(), {"heure": core_tool()}, Memory(tmp_path / "m.json"), lambda d: True, model="t")
    m = PluginManager(plugins)
    m.attach(brain)
    brain.reply("bonjour")                                        # 1re question : pas d'extension
    write(plugins, "salut", answer="extension chargée")
    m.reload()                                                    # chargée pendant la conversation
    brain.reply("utilise la nouvelle capacité")
    assert brain.history[-2]["content"] == "extension chargée"


def test_generator_coupling_generates_and_hot_loads(tmp_path):
    root = tmp_path / "jarvis"
    root.mkdir()
    brain = fake_brain({"heure": core_tool()})
    m = PluginManager(root / "plugins")
    m.attach(brain)
    example = JARVIS / "scaffold" / "packs" / "jarvis-capacite" / "exemple.yaml"
    out = generate_and_load(str(example), m, root=root)
    assert "chargée à chaud" in out
    assert {"horaires_marees", "alerte_grande_maree"} <= set(brain.tools)
    assert brain.tools["alerte_grande_maree"].confirm is not None
    # Régénérer sans changement : rien à faire, rien ne casse
    assert "déjà à jour" in generate_and_load(str(example), m, root=root)
    assert "pas pu générer" in generate_and_load(str(tmp_path / "absent.yaml"), m, root=root)


def test_proposal_activation_is_hot(tmp_path):
    from growth import GrowthJournal, Proposals

    journal = GrowthJournal(tmp_path / "j.json")
    journal.add("saluer en turc")
    props = Proposals(journal, plugins_dir=tmp_path / "plugins", tester=lambda f: (True, "1 passed"))
    folder = tmp_path / "atelier" / "p1"
    folder.mkdir(parents=True)
    (folder / "turc.py").write_text(TEMPLATE.format(tool="saluer_turc", answer="Merhaba", version="1"),
                                    encoding="utf-8")
    props.add("saluer en turc", folder, "ok", True, "1 passed")
    brain = fake_brain({"heure": core_tool()})
    m = PluginManager(tmp_path / "plugins")
    m.attach(brain)
    props.hot_reload = m.reload
    out = props.activate(1)
    assert "chargée à chaud" in out
    assert brain.tools["saluer_turc"].run() == "Merhaba"         # disponible sans redémarrage


def test_plugin_tools(plugins):
    m = PluginManager(plugins)
    write(plugins, "salut")
    tools = {t.name: t for t in build_plugin_tools(m)}
    assert "chargé : salut" in tools["recharger_extensions"].run()
    assert "salut" in tools["extensions_chargees"].run()
    assert tools["generer_capacite"].confirm is not None          # écrit du code : confirmation
