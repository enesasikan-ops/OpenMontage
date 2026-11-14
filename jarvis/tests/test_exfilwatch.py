"""Tests de la détection d'exfiltration (destinations sortantes inconnues)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import exfilwatch  # noqa: E402
from exfilwatch import (  # noqa: E402
    Collecteur,
    ExfilMonitor,
    build_exfil_tools,
    comparer,
    hotes_distants,
    make_exfil_monitor,
)

_SS = """ESTAB 0 0 192.168.1.10:51234 140.82.113.25:443
ESTAB 0 0 192.168.1.10:22 192.168.1.50:51000
ESTAB 0 0 10.0.0.2:40000 93.184.216.34:443
"""


class FakeStore:
    def __init__(self):
        self.data = {}

    def save(self):
        pass


def test_hotes_distants_garde_le_public_ignore_le_lan():
    hotes = hotes_distants(_SS)
    assert "140.82.113.25" in hotes and "93.184.216.34" in hotes
    assert "192.168.1.50" not in hotes        # pair interne → ignoré


def test_liste_blanche_par_prefixe():
    col = Collecteur(run_ss=lambda: _SS, liste_blanche=("140.82.",))
    hotes = col.instantane()["hotes"]
    assert "140.82.113.25" not in hotes and "93.184.216.34" in hotes


def test_comparer_signale_une_nouvelle_destination():
    out = list(comparer({"hotes": ["1.1.1.1"]}, {"hotes": ["1.1.1.1", "2.2.2.2"]}))
    assert len(out) == 1 and out[0][0] is False and "2.2.2.2" in out[0][1]


def test_monitor_reference_puis_alerte():
    col = Collecteur(run_ss=lambda: _SS)
    mon = ExfilMonitor(col, FakeStore())
    assert mon.check() == []                   # 1re photo = référence
    # une nouvelle destination apparaît
    mon.collecteur = Collecteur(run_ss=lambda: _SS + "ESTAB 0 0 10.0.0.2:5000 45.33.32.1:443\n")
    alertes = mon.check()
    assert alertes and "45.33.32.1" in alertes[0][1]


def test_accepter_rebase():
    seq = [_SS, _SS + "ESTAB 0 0 10.0.0.2:5000 45.33.32.1:443\n"]
    i = [0]

    def run():
        s = seq[min(i[0], len(seq) - 1)]
        i[0] += 1
        return s

    mon = ExfilMonitor(Collecteur(run_ss=run), FakeStore())
    mon.check()           # référence (photo 0)
    mon.accepter()        # accepte la photo 1 (avec 45.33.32.1)
    assert mon.check() == []   # photo 1 de nouveau → plus d'alerte


def test_outils_gates(monkeypatch):
    monkeypatch.setattr(config, "EXFIL", False)
    exfilwatch._MONITOR = None
    assert build_exfil_tools() == []
    assert make_exfil_monitor() is None
    monkeypatch.setattr(config, "EXFIL", True)
    monkeypatch.setattr(config, "EXFIL_FILE", Path("/tmp/jarvis_exfil_test.json"))
    monkeypatch.setattr(config, "EXFIL_ALLOW", ())
    exfilwatch._MONITOR = None
    names = {t.name for t in build_exfil_tools()}
    assert names == {"verifier_exfiltration", "accepter_exfiltration"}
