"""Robustesse d'un mot de passe / d'une clé Wi-Fi — en local, sans rien attaquer.

« Ma clé WPA2 est-elle cassable ? » se répond sans déauthentifier le moindre appareil :
on ÉVALUE la phrase de passe (longueur, variété, entropie, présence dans les listes
courantes). Donne le même verdict actionnable qu'une attaque (« faible, change-la »),
mais instantané, légal, et sans toucher au réseau ni au spectre radio.

Tout reste local : le mot de passe n'est ni stocké, ni envoyé nulle part.
"""

from __future__ import annotations

import math
import re

# Un échantillon des mots de passe les plus courants / éventés (pas une liste exhaustive).
COURANTS = {
    "123456", "123456789", "12345678", "12345", "1234567890", "password", "motdepasse",
    "azerty", "azertyuiop", "qwerty", "qwertyuiop", "111111", "000000", "123123",
    "admin", "root", "welcome", "iloveyou", "abc123", "password1", "motdepasse1",
    "soleil", "loulou", "doudou", "0000", "1234", "letmein", "monkey", "dragon",
    "aaaaaa", "123321", "654321", "password123", "qwerty123", "changeme", "default",
}

_CLAVIER = ("azerty", "qwerty", "asdf", "qsdf", "wxcv", "1234", "2580")


def _entropie(mdp: str) -> float:
    pool = 0
    if re.search(r"[a-z]", mdp):
        pool += 26
    if re.search(r"[A-Z]", mdp):
        pool += 26
    if re.search(r"\d", mdp):
        pool += 10
    if re.search(r"[^A-Za-z0-9]", mdp):
        pool += 32
    return len(mdp) * math.log2(pool) if pool else 0.0


def _sequentiel(mdp: str) -> bool:
    bas = mdp.lower()
    if len(bas) < 4:
        return False
    suites = "abcdefghijklmnopqrstuvwxyz0123456789"
    for i in range(len(suites) - 3):
        if suites[i:i + 4] in bas or suites[i:i + 4][::-1] in bas:
            return True
    return False


def _trivial(mdp: str) -> "str | None":
    bas = mdp.lower()
    if bas in COURANTS:
        return "C'est un mot de passe très courant (dans toutes les listes d'attaque)."
    if len(set(mdp)) <= 2:
        return "Trop peu de caractères différents (ex. répétitions)."
    if _sequentiel(mdp):
        return "Il contient une suite évidente (1234, abcd…)."
    if any(k in bas for k in _CLAVIER):
        return "Il contient une suite de clavier (azerty, qwerty…)."
    if bas.isdigit():
        return "Uniquement des chiffres : cassé en quelques secondes."
    return None


def evaluer(mdp: str) -> dict:
    """Renvoie {niveau, bits, raisons, conseil}. niveau : critique|faible|moyen|correct|fort."""
    mdp = mdp or ""
    if not mdp:
        return {"niveau": "critique", "bits": 0.0, "raisons": ["Mot de passe vide."],
                "conseil": "Mets une vraie phrase de passe."}
    raisons = []
    trivial = _trivial(mdp)
    bits = _entropie(mdp)

    if trivial:
        niveau = "critique"
        raisons.append(trivial)
    elif len(mdp) < 8 or bits < 40:
        niveau = "faible"
        raisons.append(f"Trop courte ou peu variée ({len(mdp)} caractères, ~{bits:.0f} bits).")
    elif bits < 60:
        niveau = "moyen"
        raisons.append(f"Correcte mais améliorable (~{bits:.0f} bits).")
    elif bits < 80:
        niveau = "correct"
        raisons.append(f"Solide (~{bits:.0f} bits).")
    else:
        niveau = "fort"
        raisons.append(f"Très solide (~{bits:.0f} bits).")

    conseil = ("Pour une clé Wi-Fi : une phrase de passe de 4 mots aléatoires, ou 20+ "
               "caractères variés. Ne réutilise pas un mot de passe d'un autre service.")
    return {"niveau": niveau, "bits": round(bits, 1), "raisons": raisons, "conseil": conseil}


def message(mdp: str) -> str:
    r = evaluer(mdp)
    icone = {"critique": "🔴", "faible": "🟠", "moyen": "🟡", "correct": "🟢", "fort": "🟢"}
    tete = f"{icone.get(r['niveau'], '•')} Robustesse : {r['niveau']}."
    return tete + " " + " ".join(r["raisons"]) + " " + r["conseil"]


def build_pwcheck_tools() -> list:
    from tools import Tool

    return [Tool(
        name="verifier_mot_de_passe",
        description=("Évalue la robustesse d'un mot de passe ou d'une clé Wi-Fi, EN LOCAL "
                     "(rien n'est envoyé ni stocké). À utiliser pour « ma clé Wi-Fi est-elle "
                     "solide ? », « ce mot de passe est-il fort ? ». Ne teste rien sur le réseau."),
        parameters={"type": "object",
                    "properties": {"mot_de_passe": {"type": "string",
                                   "description": "le mot de passe à évaluer"}},
                    "required": ["mot_de_passe"]},
        run=lambda mot_de_passe: message(mot_de_passe),
    )]
