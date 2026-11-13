"""Tests de la sentinelle (surveillance des signes d'intrusion)."""

import json
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import proactive  # noqa: E402
import security  # noqa: E402
import skills  # noqa: E402
from tools import build_tools  # noqa: E402

BASE = {"ports": {"ollama:11434": "ollama (port 11434)"}, "appareils": {"aa:bb:cc:00:00:01": "adresse 192.168.1.1 (identifiant aa:bb:cc:00:00:01)"},
        "demarrage": {}, "admins": {"PC\\Enes": "PC\\Enes"}, "menaces": {}}


def sentinel(tmp_path, state, firewall=None):
    return security.Sentinel(tmp_path / "s.json", take_snapshot=lambda: json.loads(json.dumps(state)),
                             firewall=lambda: (firewall or {"off": []})["off"])


def test_first_run_memorises_without_alarm(tmp_path):
    s = sentinel(tmp_path, BASE)
    events = s.check()
    assert len(events) == 1 and events[0][0] is False and "mémorisé" in events[0][1]
    assert s.check() == []


def test_new_listening_program_and_device_reported_once(tmp_path):
    state = json.loads(json.dumps(BASE))
    s = sentinel(tmp_path, state)
    s.check()
    state["ports"]["nc.exe:4444"] = "nc.exe (port 4444)"
    state["appareils"]["de:ad:be:ef:00:02"] = "adresse 192.168.1.66 (identifiant de:ad:be:ef:00:02)"
    events = s.check()
    assert (False, "un nouveau programme accepte des connexions venant du réseau : nc.exe (port 4444)") in events
    assert any("appareil inconnu" in text and "192.168.1.66" in text for _, text in events)
    assert s.check() == []                       # signalé une seule fois


def test_known_device_leaving_and_returning_is_silent(tmp_path):
    state = json.loads(json.dumps(BASE))
    s = sentinel(tmp_path, state)
    s.check()
    device = state["appareils"].popitem()
    assert s.check() == []
    state["appareils"][device[0]] = device[1]
    assert s.check() == []


def test_new_admin_and_threat_are_critical(tmp_path):
    state = json.loads(json.dumps(BASE))
    s = sentinel(tmp_path, state)
    s.check()
    state["admins"]["PC\\support"] = "PC\\support"
    state["menaces"]["2147"] = "Trojan:Win32/Exemple"
    events = dict((text, critical) for critical, text in s.check())
    assert events["un nouveau compte administrateur est apparu : PC\\support"] is True
    assert events["Windows Defender a détecté une menace : Trojan:Win32/Exemple"] is True


def test_reference_survives_restart(tmp_path):
    state = json.loads(json.dumps(BASE))
    sentinel(tmp_path, state).check()
    state["demarrage"]["x|c:\\x.exe"] = "x"
    events = sentinel(tmp_path, state).check()   # nouveau processus Jarvis
    assert events == [(False, "un nouveau programme se lance au démarrage : x")]


def test_firewall_off_alerts_once_then_again_if_it_recurs(tmp_path):
    fw = {"off": []}
    s = sentinel(tmp_path, BASE, fw)
    s.check()
    fw["off"] = ["Public"]
    assert s.check() == [(True, "le pare-feu Windows est désactivé (Public)")]
    assert s.check() == []
    fw["off"] = []
    s.check()
    fw["off"] = ["Public"]
    assert len(s.check()) == 1


def test_real_open_port_is_detected(tmp_path):
    """Fausse intrusion : un vrai programme se met à écouter sur le réseau."""
    s = security.Sentinel(tmp_path / "s.json", firewall=lambda: [])
    s.check()
    with socket.socket() as sock:
        sock.bind(("0.0.0.0", 0))
        sock.listen()
        port = sock.getsockname()[1]
        label = "port temporaire" if port >= security.DYNAMIC_PORT else f"port {port}"
        events = s.check()
    assert any("accepte des connexions venant du réseau" in text and label in text for _, text in events)


def test_local_only_port_is_not_reported(tmp_path):
    s = security.Sentinel(tmp_path / "s.json", firewall=lambda: [])
    s.check()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))              # accessible seulement depuis le PC lui-même
        sock.listen()
        assert s.check() == []


ARP_WINDOWS = """
Interface : 192.168.1.20 --- 0x5
  Adresse Internet      Adresse physique      Type
  192.168.1.1           aa-bb-cc-dd-ee-01     dynamique
  192.168.1.66          DE-AD-BE-EF-00-02     dynamique
  192.168.1.255         ff-ff-ff-ff-ff-ff     statique
  224.0.0.22            01-00-5e-00-00-16     statique
"""
ARP_LINUX = """? (192.168.1.1) at aa:bb:cc:dd:ee:01 [ether] on eth0
? (192.168.1.9) at <incomplete> on eth0
"""


@pytest.mark.parametrize("output, expected", [
    (ARP_WINDOWS, {"aa:bb:cc:dd:ee:01", "de:ad:be:ef:00:02"}),
    (ARP_LINUX, {"aa:bb:cc:dd:ee:01"}),
    ("", set()),
])
def test_network_devices_parsing(output, expected):
    run = lambda *a, **k: NS(stdout=output)  # noqa: E731
    assert set(security.network_devices(run)) == expected


def test_network_devices_without_arp_command():
    def missing(*a, **k):
        raise FileNotFoundError("arp")

    assert security.network_devices(missing) == {}


def fake_powershell(answers):
    def run(cmd, **kwargs):
        for needle, payload in answers.items():
            if needle in cmd[-1]:
                return NS(stdout=json.dumps(payload))
        return NS(stdout="")
    return run


def test_windows_sources(monkeypatch):
    monkeypatch.setattr(security.platform, "system", lambda: "Windows")
    run = fake_powershell({
        "Win32_StartupCommand": [{"Name": "OneDrive", "Command": "c:\\od.exe"}, {"Name": "Jarvis", "Command": "pythonw"}],
        "Get-LocalGroupMember": {"Name": "PC\\Enes"},          # un seul résultat : objet, pas liste
        "Get-MpThreat": [],
        "Get-NetFirewallProfile": [{"Name": "Domain", "Enabled": True}, {"Name": "Public", "Enabled": False}],
    })
    assert set(security.startup_programs(run).values()) == {"OneDrive", "Jarvis"}
    assert security.admin_accounts(run) == {"PC\\Enes": "PC\\Enes"}
    assert security.defender_threats(run) == {}
    assert security.firewall_off(run) == ["Public"]


def test_snapshot_survives_broken_source(monkeypatch):
    monkeypatch.setattr(security.platform, "system", lambda: "Windows")

    def broken(*a, **k):
        raise OSError("powershell introuvable")

    snap = security.snapshot(broken)
    assert snap["admins"] == {} and snap["demarrage"] == {} and isinstance(snap["ports"], dict)


def test_antivirus_scan(monkeypatch):
    assert "que sous Windows" in security.start_antivirus_scan() or security.platform.system() == "Windows"
    monkeypatch.setattr(security.platform, "system", lambda: "Windows")
    seen = []
    assert "lancée" in security.start_antivirus_scan(lambda cmd, **k: seen.append(cmd) or NS(stdout=""))
    assert "Start-MpScan -ScanType QuickScan" in seen[0][-1]

    def fail(*a, **k):
        raise OSError

    assert "pas réussi" in security.start_antivirus_scan(fail)


def test_tools_exposed_and_scan_needs_confirmation(tmp_path):
    s = sentinel(tmp_path, BASE)
    tools = build_tools(None, NS(available=False), lambda t: None,
                        reminders=skills.Reminders(tmp_path / "r.json"), lists=skills.Lists(tmp_path / "l.json"),
                        sentinel=s)
    assert "1 programme(s) acceptent des connexions du réseau : ollama (port 11434)" in tools["rapport_securite"].run()
    assert tools["rapport_securite"].confirm is None
    assert "analyse antivirus" in tools["analyse_antivirus"].confirm()
    without = build_tools(None, NS(available=False), lambda t: None,
                          reminders=skills.Reminders(tmp_path / "r2.json"), lists=skills.Lists(tmp_path / "l2.json"))
    assert "rapport_securite" not in without


# --- Avec les initiatives ---

def make_proactive(tmp_path, monkeypatch, hour, events):
    monkeypatch.setattr(config, "PROACTIVE_FILE", tmp_path / "i.json")
    monkeypatch.setattr(config, "BRIEFING_TIME", "")
    monkeypatch.setattr(config, "ALERTS", False)
    monkeypatch.setattr(config, "QUIET_HOURS", "22:00-07:00")
    monkeypatch.setattr(config, "STYLE", "film")
    monkeypatch.setattr(config, "TITLE", "Monsieur")
    clock = NS(t=datetime(2026, 11, 13, hour, 0, tzinfo=ZoneInfo("Europe/Paris")))
    sent = []
    queue = list(events)
    p = proactive.Proactive(skills.Reminders(tmp_path / "r.json"), skills.Lists(tmp_path / "l.json"),
                            notify=sent.append, now=lambda: clock.t,
                            security=lambda: queue.pop(0) if queue else [])
    return p, sent, clock


def test_critical_alert_passes_at_night_info_waits_for_morning(tmp_path, monkeypatch):
    events = [[(True, "un nouveau compte administrateur est apparu : PC\\support"),
               (False, "un appareil inconnu est apparu sur le réseau : adresse 192.168.1.66")]]
    p, sent, clock = make_proactive(tmp_path, monkeypatch, 3, events)
    p.tick()
    assert sent == ["Alerte de sécurité, Monsieur : un nouveau compte administrateur est apparu : PC\\support."]
    clock.t = clock.t.replace(hour=7, minute=30)
    p.tick()
    assert sent[1] == "Pour votre information, Monsieur : un appareil inconnu est apparu sur le réseau : adresse 192.168.1.66."
    p.tick()
    assert len(sent) == 2


def test_security_checked_every_five_minutes_and_failure_is_contained(tmp_path, monkeypatch):
    p, sent, clock = make_proactive(tmp_path, monkeypatch, 15, [])
    calls = []

    def flaky():
        calls.append(1)
        raise OSError("lecture impossible")

    p.security = flaky
    for _ in range(11):
        p.tick()
        clock.t += timedelta(minutes=1)
    assert len(calls) == 3 and sent == []        # à 0, 5 et 10 minutes, sans planter
