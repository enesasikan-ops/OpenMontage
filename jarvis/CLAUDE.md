# Jarvis — règles pour les sessions Claude Code

Ces règles s'appliquent à tout travail dans le dossier `jarvis/`.

## Le dossier `plugins/` appartient à Jarvis et à son propriétaire — n'y touche pas

Le dossier `jarvis/plugins/` contient les capacités que **Jarvis écrit lui-même**
(via Gemini ou Claude en renfort), **approuvées par le propriétaire** (bouton ✅ sur
Telegram/Signal). Ce code n'appartient pas aux sessions Claude Code.

**Règle (sauf demande explicite et nominative du propriétaire) :**

- Ne crée, ne modifie, ne réécris, ne « nettoie » et ne supprime **aucun** fichier
  sous `jarvis/plugins/`.
- Ne le fais pas « pour aider », ni au passage d'un autre changement, ni au nom de la
  cohérence ou du style. Si un plugin te semble fautif, **signale-le** au propriétaire
  et attends sa demande ; ne le corrige pas de ta propre initiative.
- Le propriétaire doit nommer explicitement le plugin à toucher (« modifie
  `plugins/meteo.py` »). Une demande vague ne suffit pas.

Le `plugin_manager.py`, lui, fait partie du cœur et suit les règles ci-dessous.

## Fichiers du cœur — jamais modifiés par l'auto-amélioration

L'auto-amélioration de Jarvis (la nuit) ne doit jamais toucher aux fichiers du cœur
listés dans `growth.py` (`config.py`, `claude_bridge.py`, `brain.py`, `drone.py`,
`security.py`, `plugin_manager.py`, …). Ce garde-fou ne se retire pas.

## Rien ne s'applique sans l'humain

Aucune amélioration écrite par Jarvis (Gemini ou Claude en renfort) n'est appliquée
sans l'approbation explicite du propriétaire. La chaîne reste :
génération → sandbox → tests qui passent → **✅ du propriétaire** → chargement à chaud.
Ne retire ni ne contourne aucune de ces étapes.

## Secrets

Les secrets (jetons, clés) vivent dans `.env` (ignoré par git). Ne mets jamais de vraie
valeur dans le code, dans `.env.example`, ou dans un commit. `.env.example` ne contient
que des étiquettes vides.
