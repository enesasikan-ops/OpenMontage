"""Tests de l'authentification par empreinte vocale (facteur, échoue fermé, secours)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import voiceprint as vp  # noqa: E402
from voiceprint import (REFUS, SpeakerGuard, SpeakerVerifier, VoiceStore,  # noqa: E402
                        build_voice_tools, cosine, make_guard, proteger_outils)

# Embedder factice : l'« audio » EST déjà un vecteur d'empreinte (identité).
IDENT = lambda audio: list(audio)  # noqa: E731
PROPRIO = [1.0, 0.0, 0.0]          # la voix du propriétaire
PROPRIO_BIS = [0.95, 0.05, 0.0]    # le proprio, autre intonation (cosinus ~0.99)
ENFANT = [0.0, 1.0, 0.0]           # une autre voix


def _verifier(tmp_path, seuil=0.65):
    return SpeakerVerifier(VoiceStore(tmp_path / "vp.json"), embed=IDENT, seuil=seuil)


# --- Cosinus ---

def test_cosine():
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([], [1]) == 0.0


# --- Store ---

def test_store_persiste(tmp_path):
    s = VoiceStore(tmp_path / "vp.json")
    s.ajouter("proprio", [1.0, 2.0])
    assert VoiceStore(tmp_path / "vp.json").empreintes("proprio") == [[1.0, 2.0]]


def test_store_oublier(tmp_path):
    s = VoiceStore(tmp_path / "vp.json")
    s.ajouter("x", [1.0])
    assert s.oublier("x") is True and s.empreintes("x") == []
    assert s.oublier("absent") is False


# --- Vérification ---

def test_enrole_et_reconnait_le_proprietaire(tmp_path):
    v = _verifier(tmp_path)
    assert v.enroler("proprio", [PROPRIO, PROPRIO_BIS]) == 2
    ok, score = v.verifier(PROPRIO, "proprio")
    assert ok and score > 0.99


def test_refuse_une_autre_voix(tmp_path):
    v = _verifier(tmp_path)
    v.enroler("proprio", [PROPRIO])
    ok, score = v.verifier(ENFANT, "proprio")
    assert not ok and score < 0.65


def test_identifier_qui_parle(tmp_path):
    v = _verifier(tmp_path)
    v.enroler("proprio", [PROPRIO])
    v.enroler("enfant", [ENFANT])
    assert v.identifier(PROPRIO_BIS)[0] == "proprio"
    assert v.identifier([0.0, 0.0, 1.0])[0] is None    # inconnu : personne


def test_verifier_sans_audio_ni_empreinte(tmp_path):
    v = _verifier(tmp_path)
    assert v.verifier([], "proprio") == (False, 0.0)       # pas d'audio
    v.enroler("proprio", [PROPRIO])
    assert v.verifier(PROPRIO, "inconnu") == (False, 0.0)  # personne nommée non enrôlée


# --- Garde : échoue fermé + porte de secours ---

def _guard(tmp_path, source, code="", clock=None):
    v = _verifier(tmp_path)
    v.enroler("proprio", [PROPRIO])
    horloge = clock or (lambda: 0.0)
    return SpeakerGuard(v, "proprio", source=source, code=code, fenetre_s=60, horloge=horloge)


def test_autorise_la_voix_du_proprietaire(tmp_path):
    g = _guard(tmp_path, source=lambda: PROPRIO)
    assert g.autorise() == (True, "")


def test_refuse_la_voix_de_l_enfant(tmp_path):
    g = _guard(tmp_path, source=lambda: ENFANT)
    ok, msg = g.autorise()
    assert not ok and msg == REFUS


def test_echoue_ferme_sans_audio(tmp_path):
    g = _guard(tmp_path, source=lambda: None)      # aucun son (ex. canal texte)
    ok, msg = g.autorise()
    assert not ok and REFUS in msg                 # au doute, on REFUSE


def test_code_maitre_ouvre_une_fenetre(tmp_path):
    horloge = {"t": 100.0}
    g = _guard(tmp_path, source=lambda: ENFANT, code="4731", clock=lambda: horloge["t"])
    assert "secondes" in g.deverrouiller("4731")
    assert g.autorise()[0] is True                 # débloqué par le code malgré la voix enfant
    horloge["t"] += 61                             # la fenêtre expire
    assert g.autorise()[0] is False


def test_code_maitre_mauvais_code(tmp_path):
    g = _guard(tmp_path, source=lambda: ENFANT, code="4731")
    assert g.deverrouiller("0000") == REFUS
    assert g.autorise()[0] is False


def test_message_refus_mentionne_le_code(tmp_path):
    g = _guard(tmp_path, source=lambda: ENFANT, code="4731")
    _, msg = g.autorise()
    assert "code maître" in msg


# --- Protection des outils ---

def _outil(nom, journal):
    from tools import Tool
    return Tool(name=nom, description="", parameters={"type": "object", "properties": {}, "required": []},
                run=lambda **k: (journal.append(nom), "FAIT")[1])


def test_outil_protege_bloque_sans_identite(tmp_path):
    journal = []
    tools = {"ouvrir": _outil("ouvrir", journal), "heure": _outil("heure", journal)}
    g = _guard(tmp_path, source=lambda: ENFANT)       # voix non reconnue
    proteges = proteger_outils(tools, g, ("ouvrir", "inexistant"))
    assert proteges == ["ouvrir"]
    assert tools["ouvrir"].run() == REFUS and journal == []   # action NON exécutée
    assert tools["heure"].run() == "FAIT"                     # outil non protégé : libre


def test_outil_protege_passe_pour_le_proprietaire(tmp_path):
    journal = []
    tools = {"ouvrir": _outil("ouvrir", journal)}
    g = _guard(tmp_path, source=lambda: PROPRIO)
    proteger_outils(tools, g, ("ouvrir",))
    assert tools["ouvrir"].run() == "FAIT" and journal == ["ouvrir"]


def test_build_voice_tools_code(tmp_path):
    g = _guard(tmp_path, source=lambda: ENFANT, code="4731")
    tool = {t.name: t for t in build_voice_tools(g)}["code_maitre"]
    assert "secondes" in tool.run(code="4731")


# --- Fabrique ---

def test_make_guard_desactive(monkeypatch):
    monkeypatch.setattr(config, "VOICE_AUTH", False)
    assert make_guard() is None


def test_make_guard_sans_enrolement_echoue_ferme(monkeypatch, tmp_path):
    # RÉGRESSION DE SÉCURITÉ : auth activée sans empreinte ne doit PAS désactiver la garde.
    monkeypatch.setattr(config, "VOICE_AUTH", True)
    monkeypatch.setattr(config, "VOICE_OWNER", "proprio")
    monkeypatch.setattr(config, "VOICE_FILE", tmp_path / "vide.json")
    monkeypatch.setattr(config, "VOICE_SEUIL", 0.65)
    monkeypatch.setattr(config, "VOICE_PIN", "")
    monkeypatch.setattr(config, "VOICE_FENETRE", 60.0)
    g = make_guard(source=lambda: PROPRIO, embed=IDENT)
    assert g is not None                               # la garde existe (échec fermé, pas ouvert)
    ok, msg = g.autorise()
    assert ok is False and "aucune empreinte" in msg   # action sensible REFUSÉE


def test_make_guard_sans_enrolement_code_maitre_depanne(monkeypatch, tmp_path):
    # le propriétaire n'est pas enfermé dehors : le code maître reste la porte de secours.
    monkeypatch.setattr(config, "VOICE_AUTH", True)
    monkeypatch.setattr(config, "VOICE_OWNER", "proprio")
    monkeypatch.setattr(config, "VOICE_FILE", tmp_path / "vide.json")
    monkeypatch.setattr(config, "VOICE_SEUIL", 0.65)
    monkeypatch.setattr(config, "VOICE_PIN", "4731")
    monkeypatch.setattr(config, "VOICE_FENETRE", 60.0)
    g = make_guard(source=lambda: None, embed=IDENT)
    assert "code maître" in g.autorise()[1]            # message guide vers le code
    g.deverrouiller("4731")
    assert g.autorise()[0] is True                     # débloqué par le code maître


def test_make_guard_pret(monkeypatch, tmp_path):
    chemin = tmp_path / "vp.json"
    SpeakerVerifier(VoiceStore(chemin), embed=IDENT).enroler("proprio", [PROPRIO])
    monkeypatch.setattr(config, "VOICE_AUTH", True)
    monkeypatch.setattr(config, "VOICE_OWNER", "proprio")
    monkeypatch.setattr(config, "VOICE_FILE", chemin)
    monkeypatch.setattr(config, "VOICE_SEUIL", 0.65)
    monkeypatch.setattr(config, "VOICE_PIN", "")
    monkeypatch.setattr(config, "VOICE_FENETRE", 60.0)
    g = make_guard(source=lambda: PROPRIO, embed=IDENT)
    assert g is not None and g.autorise()[0] is True
