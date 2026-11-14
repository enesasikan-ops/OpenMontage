"""Apprentissage d'habitudes — Jarvis anticipe, mais PROPOSE (il n'agit pas en douce).

Principe : pas de boîte noire (TensorFlow…), du **comptage explicable**. Jarvis lit
l'historique de Home Assistant (lecture seule) et découpe le passé en **créneaux**
(jour × moment de la journée × météo). Pour chaque créneau, il note ce que tu as
allumé. Une **habitude** = une action qui revient assez souvent dans un même contexte
(« les mardis soirs de pluie, tu allumes le porche : 4 fois sur 5 »).

Garde-fou volontaire : par défaut, Jarvis **propose** l'action et attend ton « oui ».
Agir tout seul sur une corrélation devinée (chauffage, serrures…) peut se tromper,
gaspiller ou surprendre. Tu peux promouvoir une habitude SÛRE en automatique, une par
une — c'est ton choix explicite, jamais celui de Jarvis.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _now() -> datetime:
    return datetime.now()

# Moments de la journée (bornes en heures). Grossier exprès : les habitudes émergent
# mieux avec peu de données si le contexte n'est pas trop fin.
MOMENTS = (("nuit", 0, 6), ("matin", 6, 12), ("après-midi", 12, 18), ("soir", 18, 24))

_PLUIE = {"rainy", "pouring", "lightning-rainy", "snowy-rainy", "hail"}
_NEIGE = {"snowy"}
_ETEINT = {"off", "unavailable", "unknown", "", None}


def moment(heure: int) -> str:
    for nom, debut, fin in MOMENTS:
        if debut <= heure < fin:
            return nom
    return "nuit"


def meteo_simple(etat: "str | None") -> "str | None":
    if etat is None:
        return None
    e = etat.lower()
    if e in _PLUIE:
        return "pluie"
    if e in _NEIGE:
        return "neige"
    return "sec"


def contexte(dt: datetime, meteo: "str | None" = None) -> tuple:
    """Clé de contexte : (jour, moment, météo). météo None si pas de capteur."""
    return (JOURS[dt.weekday()], moment(dt.hour), meteo)


def est_allume(etat: "str | None") -> bool:
    return etat not in _ETEINT


# --- Habitude apprise ---------------------------------------------------------------


@dataclass(frozen=True)
class Habit:
    contexte: tuple          # (jour, moment, météo|None)
    entity: str
    support: int             # nombre de fois où l'action a eu lieu dans ce contexte
    total: int               # nombre de créneaux de ce contexte observés
    nom: str = ""            # nom lisible de l'appareil (friendly_name)

    @property
    def confiance(self) -> float:
        return self.support / self.total if self.total else 0.0

    def _contexte_phrase(self) -> str:
        jour, mmt, meteo = self.contexte
        base = f"les {jour}s {mmt}"
        return f"{base} quand il {'pleut' if meteo == 'pluie' else 'neige'}" if meteo in ("pluie", "neige") else base

    def raison(self) -> str:
        quoi = self.nom or self.entity
        return f"{self._contexte_phrase()}, tu allumes {quoi} ({self.support} fois sur {self.total})"


# --- Apprentissage ------------------------------------------------------------------


@dataclass
class HabitLearner:
    """Compte, par contexte, combien de créneaux ont vu chaque action.

    On lui donne des créneaux : {"contexte": (…), "actions": set[entity]}.
    """
    _total: dict = field(default_factory=lambda: defaultdict(int))
    _hits: dict = field(default_factory=lambda: defaultdict(int))

    def apprendre(self, creneaux: list) -> None:
        for creneau in creneaux:
            ctx = creneau["contexte"]
            self._total[ctx] += 1
            for entity in creneau["actions"]:
                self._hits[(ctx, entity)] += 1

    def habitudes(self, support_min: int = 3, confiance_min: float = 0.6,
                  noms: "dict | None" = None) -> list:
        noms = noms or {}
        out = []
        for (ctx, entity), hits in self._hits.items():
            total = self._total[ctx]
            if hits >= support_min and total and hits / total >= confiance_min:
                out.append(Habit(contexte=ctx, entity=entity, support=hits,
                                 total=total, nom=noms.get(entity, "")))
        out.sort(key=lambda h: (h.confiance, h.support), reverse=True)
        return out


# --- Suggestion (ce que Jarvis proposerait MAINTENANT) ------------------------------


class Suggester:
    def __init__(self, habitudes: list):
        self.habitudes = habitudes

    def suggestions(self, contexte_now: tuple, etats_actuels: dict) -> list:
        """Habitudes qui s'appliquent au contexte courant et ne sont pas déjà faites."""
        props = []
        for h in self.habitudes:
            if h.contexte != contexte_now:
                continue
            if est_allume(etats_actuels.get(h.entity)):   # déjà allumé : rien à proposer
                continue
            props.append(h)
        return props


# --- Lecture de l'historique Home Assistant -----------------------------------------


def _parse(ts: str, zone: ZoneInfo) -> datetime:
    """ISO Home Assistant (UTC) -> datetime local naïf (pour comparer jours/heures)."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is not None:
        dt = dt.astimezone(zone).replace(tzinfo=None)
    return dt


def transitions_on(historique_entite: list, zone: ZoneInfo) -> list:
    """Instants où l'appareil passe à l'état allumé (front montant seulement)."""
    instants, precedent = [], None
    for e in sorted(historique_entite, key=lambda x: x.get("last_changed", "")):
        etat = est_allume(e.get("state"))
        if etat and precedent is False:
            instants.append(_parse(e["last_changed"], zone))
        precedent = etat
    return instants


def timeline_meteo(historique_entite: list, zone: ZoneInfo) -> list:
    tl = [(_parse(e["last_changed"], zone), meteo_simple(e.get("state")))
          for e in sorted(historique_entite, key=lambda x: x.get("last_changed", ""))]
    return tl


def meteo_a(timeline: list, t: datetime) -> "str | None":
    courant = None
    for dt, meteo in timeline:
        if dt <= t:
            courant = meteo
        else:
            break
    return courant


def creneaux(debut: datetime, fin: datetime) -> list:
    """Découpe [debut, fin) en créneaux (jour × moment)."""
    out = []
    jour = debut.replace(hour=0, minute=0, second=0, microsecond=0)
    while jour < fin:
        for _, h0, h1 in MOMENTS:
            s = jour.replace(hour=h0)
            e = jour.replace(hour=0) + timedelta(hours=h1)
            if e <= debut or s >= fin:
                continue
            out.append((max(s, debut), min(e, fin)))
        jour += timedelta(days=1)
    return out


def slots(on_times: dict, tl_meteo: list, debut: datetime, fin: datetime) -> list:
    """Construit les créneaux annotés {contexte, actions} pour le learner."""
    out = []
    for s, e in creneaux(debut, fin):
        meteo = meteo_a(tl_meteo, s + (e - s) / 2) if tl_meteo else None
        ctx = contexte(s, meteo)
        actions = {ent for ent, times in on_times.items()
                   if any(s <= t < e for t in times)}
        out.append({"contexte": ctx, "actions": actions})
    return out


def from_ha_history(home, entities: list, meteo_entity: str, jours: int,
                    now: "datetime | None" = None) -> "tuple[HabitLearner, dict]":
    """Apprend depuis l'historique HA. Renvoie (learner, noms lisibles des entités)."""
    zone = ZoneInfo(config.TIMEZONE)
    fin = now or _now()
    debut = fin - timedelta(days=jours)
    a_lire = list(entities) + ([meteo_entity] if meteo_entity else [])
    brut = home.history(a_lire, (debut.replace(microsecond=0)).isoformat())
    par_entite = {}
    for serie in brut:
        if serie:
            par_entite[serie[0].get("entity_id", "")] = serie
    on_times = {ent: transitions_on(par_entite.get(ent, []), zone) for ent in entities}
    tl_meteo = timeline_meteo(par_entite.get(meteo_entity, []), zone) if meteo_entity else []
    learner = HabitLearner()
    learner.apprendre(slots(on_times, tl_meteo, debut, fin))
    noms = {}
    for ent in entities:
        serie = par_entite.get(ent, [])
        if serie:
            noms[ent] = serie[0].get("attributes", {}).get("friendly_name", "") or ent
    return learner, noms


# --- Outils (lecture seule : Jarvis rapporte et propose, il n'agit pas ici) ----------


def _etats_on_off(home) -> dict:
    etats = {}
    try:
        for e in home.states():
            etats[e["entity_id"]] = e.get("state")
    except Exception:
        pass
    return etats


def build_habit_tools(home) -> list:
    from tools import Tool

    if not (config.HABITS and config.HABITS_ENTITES):
        return []

    def _apprendre():
        return from_ha_history(home, list(config.HABITS_ENTITES), config.HABITS_METEO,
                               config.HABITS_JOURS)

    def mes_habitudes() -> str:
        try:
            learner, noms = _apprendre()
        except Exception:
            return "Je n'arrive pas à relire l'historique de la maison pour l'instant."
        habs = learner.habitudes(config.HABITS_SUPPORT, config.HABITS_CONFIANCE, noms)
        if not habs:
            return ("Je n'ai pas encore repéré d'habitude nette. Laissez-moi observer "
                    "quelques semaines de plus.")
        lignes = [f"• {h.raison()}." for h in habs[:8]]
        return "Voici ce que j'ai remarqué :\n" + "\n".join(lignes)

    def anticiper_maintenant() -> str:
        try:
            learner, noms = _apprendre()
        except Exception:
            return "Je n'arrive pas à relire l'historique de la maison pour l'instant."
        habs = learner.habitudes(config.HABITS_SUPPORT, config.HABITS_CONFIANCE, noms)
        etats = _etats_on_off(home)
        meteo = meteo_simple(etats.get(config.HABITS_METEO)) if config.HABITS_METEO else None
        ctx = contexte(_now(), meteo)
        props = Suggester(habs).suggestions(ctx, etats)
        if not props:
            return "Rien à anticiper là, tout de suite : vos habitudes du moment sont déjà faites."
        quoi = ", ".join(h.nom or h.entity for h in props)
        return f"Vu l'heure et le contexte, je vous proposerais d'allumer : {quoi}. Je m'en occupe ?"

    return [
        Tool(name="mes_habitudes",
             description=("Liste les habitudes que Jarvis a remarquées dans la maison "
                          "(« qu'as-tu remarqué ? », « mes habitudes »). Lecture seule."),
             parameters={"type": "object", "properties": {}, "required": []},
             run=mes_habitudes),
        Tool(name="anticiper_maintenant",
             description=("Regarde le contexte courant (jour, heure, météo) et dit ce que "
                          "Jarvis proposerait d'allumer d'après tes habitudes. Ne fait rien "
                          "tout seul : il propose."),
             parameters={"type": "object", "properties": {}, "required": []},
             run=anticiper_maintenant),
    ]
