"""Tests du pont CrowdSec (IDS/IPS réseau) : lecture seule, annonce des IP bloquées."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from crowdsec import (CrowdSec, CrowdSecWatcher, _portee, _raison,  # noqa: E402
                      build_crowdsec_tools, make_crowdsec)

EXTERNE = "93.184.216.34"      # IP publique (globale)
LOCALE = "192.168.1.50"        # IP privée


def _decision(ip=EXTERNE, type_="ban", scenario="crowdsecurity/ssh-bf", id_=1, origin="crowdsec"):
    return {"id": id_, "value": ip, "type": type_, "scenario": scenario, "origin": origin,
            "duration": "3h59m"}


def _client(pages):
    """pages : liste de réponses successives renvoyées par decisions()."""
    etat = {"i": 0}

    def get(url, headers):
        assert headers.get("X-Api-Key") == "cle-bouncer"
        i = min(etat["i"], len(pages) - 1)
        etat["i"] += 1
        return pages[i]

    return CrowdSec("http://localhost:8080", "cle-bouncer", get=get)


# --- Traductions ---

def test_raison_connue():
    assert _raison("crowdsecurity/ssh-bf") == "force brute SSH"
    assert _raison("crowdsecurity/http-probing") == "sondage web"


def test_raison_inconnue_dernier_segment():
    assert _raison("acme/mon-scenario") == "mon-scenario"
    assert _raison("") == "activité hostile"


def test_portee_externe_vs_locale():
    assert _portee(EXTERNE) == "externe"
    assert _portee(LOCALE) == "locale"


# --- Client ---

def test_client_lit_les_decisions():
    c = _client([[_decision()]])
    assert c.decisions()[0]["value"] == EXTERNE


def test_client_reponse_vide():
    c = _client([[]])
    assert c.decisions() == []


# --- Watcher : dédoublonnage et cycle de vie ---

def test_premier_passage_apprend_sans_annoncer():
    w = CrowdSecWatcher(_client([[_decision(id_=1)]]))
    assert w.check() == []                      # le passif n'est pas crié au démarrage


def test_nouvelle_ip_annoncee_une_fois():
    client = _client([[_decision(id_=1)],                       # passif (silencieux)
                      [_decision(id_=1), _decision(id_=2, ip="45.9.1.1")]])
    w = CrowdSecWatcher(client)
    assert w.check() == []
    nouvelles = w.check()
    assert len(nouvelles) == 1
    critique, message = nouvelles[0]
    assert critique is True
    assert "45.9.1.1" in message and "bloquée" in message and "maintenus" in message


def test_meme_decision_pas_reannoncee():
    client = _client([[], [_decision(id_=7)], [_decision(id_=7)]])
    w = CrowdSecWatcher(client)
    w.check()                                   # apprend (vide)
    assert len(w.check()) == 1                  # id 7 : nouveau
    assert w.check() == []                      # id 7 encore présent : silencieux


def test_decision_expiree_puis_reban_reannonce():
    client = _client([[_decision(id_=7)],       # passif
                      [],                        # id 7 expiré (oublié)
                      [_decision(id_=9, ip=EXTERNE)]])   # nouveau blocage
    w = CrowdSecWatcher(client)
    w.check()
    assert w.check() == []                       # plus rien d'actif
    assert len(w.check()) == 1                   # reban (nouvel id) : réannoncé


def test_crowdsec_injoignable_silencieux():
    def boom(url, headers):
        raise OSError("connexion refusée")
    w = CrowdSecWatcher(CrowdSec("http://localhost:8080", "cle-bouncer", get=boom))
    assert w.check() == []                       # pas de plantage, pas de fausse alerte


# --- Fabrique depuis la config ---

def test_make_crowdsec_desactive(monkeypatch):
    monkeypatch.setattr(config, "CROWDSEC", False)
    assert make_crowdsec() is None


def test_make_crowdsec_sans_cle(monkeypatch):
    monkeypatch.setattr(config, "CROWDSEC", True)
    monkeypatch.setattr(config, "CROWDSEC_KEY", "")
    assert make_crowdsec() is None               # activé mais pas de clé → inactif


def test_make_crowdsec_pret(monkeypatch):
    monkeypatch.setattr(config, "CROWDSEC", True)
    monkeypatch.setattr(config, "CROWDSEC_KEY", "cle-bouncer")
    monkeypatch.setattr(config, "CROWDSEC_URL", "http://localhost:8080")
    assert isinstance(make_crowdsec(), CrowdSecWatcher)


# --- Outil (lecture seule) ---

def test_pas_d_outil_sans_config(monkeypatch):
    monkeypatch.setattr(config, "CROWDSEC", False)
    assert build_crowdsec_tools() == []


def test_outil_rapport(monkeypatch):
    monkeypatch.setattr(config, "CROWDSEC", True)
    monkeypatch.setattr(config, "CROWDSEC_KEY", "cle-bouncer")
    client = _client([[_decision(ip=EXTERNE), _decision(ip="45.9.1.1", id_=2)]])
    tools = build_crowdsec_tools(client=client)
    assert len(tools) == 1 and tools[0].name == "point_securite_reseau"
    out = tools[0].run()
    assert "2 attaque" in out and EXTERNE in out   # 2 décisions locales (origin crowdsec par défaut)


def test_outil_reseau_calme(monkeypatch):
    monkeypatch.setattr(config, "CROWDSEC", True)
    monkeypatch.setattr(config, "CROWDSEC_KEY", "cle-bouncer")
    tools = build_crowdsec_tools(client=_client([[]]))
    assert "calme" in tools[0].run()


# --- Liste communautaire (immunité de meute) : préventif, pas annoncé un par un ---

def test_watcher_annonce_les_attaques_locales_pas_la_meute():
    locale = _decision(ip=EXTERNE, id_=1, origin="crowdsec")       # vraie attaque sur toi
    comm = _decision(ip="45.9.1.1", id_=2, origin="CAPI")          # bouclier communautaire
    client = _client([[], [locale, comm]])                         # passif puis +2
    w = CrowdSecWatcher(client)
    w.check()                                                      # apprentissage
    alertes = w.check()
    assert len(alertes) == 1                                       # seule l'attaque locale est annoncée
    assert EXTERNE in alertes[0][1] and "45.9.1.1" not in alertes[0][1]


def test_outil_distingue_local_et_communautaire(monkeypatch):
    monkeypatch.setattr(config, "CROWDSEC", True)
    monkeypatch.setattr(config, "CROWDSEC_KEY", "cle-bouncer")
    decisions = [_decision(ip=EXTERNE, origin="crowdsec"),
                 _decision(ip="45.9.1.1", id_=2, origin="CAPI"),
                 _decision(ip="45.9.1.2", id_=3, origin="lists:firehol")]
    tools = build_crowdsec_tools(client=_client([decisions]))
    out = tools[0].run()
    assert "1 attaque" in out and "bouclier communautaire : 2 IP" in out
