"""Tests de la détection de persistance (portes dérobées : clé SSH, cron, autostart).

Invariant défensif : on DÉTECTE et on ALERTE, on ne supprime jamais tout seul ; la
première photo est la référence silencieuse, puis tout AJOUT est signalé (clé SSH et
cron = critiques) jusqu'à acceptation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import persistance  # noqa: E402
from persistance import (  # noqa: E402
    Collecteur,
    PersistenceMonitor,
    build_persistence_tools,
    comparer,
    make_persistence_monitor,
)


def _snap(cles=None, cron=None, fichiers=None):
    return {"cles_ssh": cles or {}, "cron": cron or [], "fichiers": fichiers or {}}


class FakeStore:
    def __init__(self):
        self.data = {}

    def save(self):
        pass


class StubCol:
    def __init__(self, snaps):
        self.snaps = list(snaps)
        self.i = 0

    def instantane(self):
        s = self.snaps[min(self.i, len(self.snaps) - 1)]
        self.i += 1
        return s


K = "/home/x/.ssh/authorized_keys"


# --- comparer ---

def test_nouvelle_cle_ssh_est_critique():
    base = _snap(cles={K: [{"empreinte": "aaa", "comment": "moi@maison"}]})
    actuel = _snap(cles={K: [{"empreinte": "aaa", "comment": "moi@maison"},
                             {"empreinte": "bbb", "comment": "intrus@ailleurs"}]})
    critiques = [m for c, m in comparer(base, actuel) if c]
    assert len(critiques) == 1
    assert "Nouvelle clé SSH" in critiques[0] and "intrus@ailleurs" in critiques[0]


def test_cle_ssh_retiree_non_critique():
    base = _snap(cles={K: [{"empreinte": "aaa", "comment": "moi"}]})
    out = list(comparer(base, _snap(cles={K: []})))
    assert out and all(not c for c, _ in out)
    assert "retirée" in out[0][1]


def test_nouvelle_tache_cron_est_critique():
    out = list(comparer(_snap(cron=["0 1 * * * a"]),
                        _snap(cron=["0 1 * * * a", "* * * * * /tmp/evil"])))
    crit = [m for c, m in out if c]
    assert crit and "cron" in crit[0].lower() and "/tmp/evil" in crit[0]


def test_fichier_demarrage_modifie():
    out = list(comparer(_snap(fichiers={"/h/.bashrc": "h1"}),
                        _snap(fichiers={"/h/.bashrc": "h2"})))
    assert out == [(False, "📝 Fichier de démarrage modifié : /h/.bashrc")]


def test_nouveau_autostart():
    out = list(comparer(_snap(), _snap(fichiers={"/h/.config/autostart/x.desktop": "h"})))
    assert out and not out[0][0] and "démarrage automatique" in out[0][1]


def test_aucun_changement():
    s = _snap(cles={K: [{"empreinte": "a", "comment": "m"}]}, cron=["x"], fichiers={"/f": "h"})
    assert list(comparer(s, s)) == []


# --- Collecteur sur un vrai dossier (injecté) ---

def test_collecteur_lit_les_cibles(tmp_path):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "authorized_keys").write_text("ssh-ed25519 AAAABBBBCCCC moi@maison\n")
    (tmp_path / ".bashrc").write_text("echo bonjour\n")
    (tmp_path / ".config" / "autostart").mkdir(parents=True)
    (tmp_path / ".config" / "autostart" / "truc.desktop").write_text("[Desktop Entry]\n")

    snap = Collecteur(home=tmp_path, run_cron=lambda: "0 3 * * * /usr/bin/backup\n# note\n").instantane()
    cles = next(iter(snap["cles_ssh"].values()))
    assert cles[0]["comment"] == "moi@maison"
    assert snap["cron"] == ["0 3 * * * /usr/bin/backup"]          # le commentaire cron est ignoré
    assert any(c.endswith(".bashrc") for c in snap["fichiers"])
    assert any("autostart" in c for c in snap["fichiers"])


# --- Monitor : référence silencieuse puis alerte ---

def test_premiere_fois_etablit_la_reference_sans_alerter():
    base = _snap(cles={K: [{"empreinte": "a", "comment": "moi"}]})
    mon = PersistenceMonitor(StubCol([base]), FakeStore())
    assert mon.check() == []                                   # 1re photo = référence, pas d'alerte
    assert mon.store.data["base"] == base


def test_ajout_apres_reference_declenche_une_alerte_critique():
    base = _snap(cles={K: [{"empreinte": "a", "comment": "moi"}]})
    avec_intrus = _snap(cles={K: [{"empreinte": "a", "comment": "moi"},
                                   {"empreinte": "z", "comment": "intrus"}]})
    mon = PersistenceMonitor(StubCol([base, avec_intrus]), FakeStore())
    assert mon.check() == []                                   # référence
    alertes = mon.check()                                      # intrus ajouté
    assert alertes and alertes[0][0] is True and "intrus" in alertes[0][1]


def test_accepter_remet_la_reference():
    base = _snap(cron=["a"])
    avec_cron = _snap(cron=["a", "b"])
    mon = PersistenceMonitor(StubCol([base, avec_cron]), FakeStore())
    mon.check()                                                # référence = base
    mon.accepter()                                            # on accepte l'état avec le nouveau cron
    assert mon.check() == []                                   # plus d'alerte


def test_rapport_lisible():
    base = _snap(cron=["a"])
    avec = _snap(cron=["a", "* * * * * /tmp/x"])
    mon = PersistenceMonitor(StubCol([base, avec]), FakeStore())
    mon.check()
    r = mon.rapport()
    assert "persistance" in r.lower() or "cron" in r.lower()
    assert "/tmp/x" in r


# --- Câblage ---

def test_make_monitor_none_si_desactive(monkeypatch):
    monkeypatch.setattr(config, "PERSISTENCE", False)
    persistance._MONITOR = None
    assert make_persistence_monitor() is None


def test_outils_gates_et_confirmation(monkeypatch):
    monkeypatch.setattr(config, "PERSISTENCE", True)
    persistance._MONITOR = PersistenceMonitor(StubCol([_snap()]), FakeStore())
    tools = {t.name: t for t in build_persistence_tools()}
    assert set(tools) == {"verifier_persistance", "accepter_persistance"}
    assert tools["accepter_persistance"].confirm is not None   # accepter efface des alertes -> confirmation
    assert tools["verifier_persistance"].confirm is None       # vérifier = lecture seule


def test_pas_d_outils_si_desactive(monkeypatch):
    monkeypatch.setattr(config, "PERSISTENCE", False)
    persistance._MONITOR = None
    assert build_persistence_tools() == []
