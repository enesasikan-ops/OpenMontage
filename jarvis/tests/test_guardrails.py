"""Invariants de sécurité — la VRAIE « camisole » : des actions sensibles toujours gardées.

La protection contre « l'IA ouvre la porte sous la pression » n'est PAS dans le modèle
(ni dans un décodage contraint type Outlines, qui garantit le FORMAT, pas l'autorisation).
Elle est dans le CODE : confirmation + auth vocale. Ces tests verrouillent cet invariant :
aucune refonte ne doit pouvoir retirer la confirmation d'une action sensible, ni laisser
l'auth vocale ouvrir au premier venu.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from smarthome import SmartHome, build_smarthome  # noqa: E402
from voiceprint import REFUS, SpeakerGuard, SpeakerVerifier, VoiceStore, proteger_outils  # noqa: E402

# Actions physiques sensibles : elles ne doivent JAMAIS s'exécuter sans confirmation.
SENSIBLES = {"ouvrir", "deverrouiller", "verrouiller"}


def _home():
    # SmartHome avec requête injectée : aucune I/O réseau, juste pour construire les outils.
    return SmartHome(base_url="http://x", token="t", request=lambda *a, **k: [])


def test_toute_action_sensible_est_confirmee():
    outils = {t.name: t for t in build_smarthome(_home())}
    for nom in SENSIBLES:
        assert nom in outils, f"l'outil sensible « {nom} » a disparu"
        assert outils[nom].confirm is not None, (
            f"RÉGRESSION DE SÉCURITÉ : « {nom} » peut s'exécuter sans confirmation")


def test_la_confirmation_decrit_bien_l_action():
    outils = {t.name: t for t in build_smarthome(_home())}
    # la phrase de confirmation doit nommer l'acte (déverrouiller), pas rester vague
    assert "déverrouiller" in outils["deverrouiller"].confirm("porte").lower()


# --- L'auth vocale protège réellement : un non-propriétaire est refusé ---

IDENT = lambda audio: list(audio)   # noqa: E731
PROPRIO = [1.0, 0.0, 0.0]
INTRUS = [0.0, 1.0, 0.0]


def test_auth_vocale_refuse_un_intrus(tmp_path):
    v = SpeakerVerifier(VoiceStore(tmp_path / "vp.json"), embed=IDENT)
    v.enroler("proprio", [PROPRIO])
    voix = {"a": INTRUS}
    guard = SpeakerGuard(v, "proprio", source=lambda: voix["a"])

    ouvert = []
    tools = {"deverrouiller": _OutilFactice("deverrouiller", ouvert)}
    proteger_outils(tools, guard, ("deverrouiller",))

    # un inconnu qui crie « police » : sa voix ne correspond pas -> refus, rien ne s'exécute
    assert tools["deverrouiller"].run() == REFUS and ouvert == []
    # le propriétaire, lui, passe
    voix["a"] = PROPRIO
    assert tools["deverrouiller"].run() == "FAIT" and ouvert == ["deverrouiller"]


def _OutilFactice(nom, journal):
    from tools import Tool
    return Tool(name=nom, description="", parameters={"type": "object", "properties": {}, "required": []},
                run=lambda **k: (journal.append(nom), "FAIT")[1])


# --- Invariant : auth vocale activée SANS enrôlement échoue FERMÉ (pas d'ouverture) ---

def test_auth_vocale_sans_empreinte_ne_s_ouvre_pas(monkeypatch, tmp_path):
    """RÉGRESSION : un fichier d'empreintes vide/corrompu ne doit PAS désactiver la garde."""
    import config
    from voiceprint import make_guard

    monkeypatch.setattr(config, "VOICE_AUTH", True)
    monkeypatch.setattr(config, "VOICE_OWNER", "proprio")
    monkeypatch.setattr(config, "VOICE_FILE", tmp_path / "empreintes_absentes.json")
    monkeypatch.setattr(config, "VOICE_SEUIL", 0.65)
    monkeypatch.setattr(config, "VOICE_PIN", "")
    monkeypatch.setattr(config, "VOICE_FENETRE", 60.0)

    guard = make_guard(source=lambda: [1.0, 0.0, 0.0], embed=IDENT)
    assert guard is not None, "RÉGRESSION DE SÉCURITÉ : la garde a disparu (fail-open)"
    assert guard.autorise()[0] is False, "RÉGRESSION DE SÉCURITÉ : action sensible ouverte sans empreinte"
