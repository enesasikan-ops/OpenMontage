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

## Bugs dans le code de Jarvis : rapporter, ne pas corriger sans aval

Quand une session Claude Code **détecte une erreur ou un bug** dans le code source de
Jarvis (hors tâche demandée), elle le **signale au propriétaire** — description claire,
fichier et ligne, conséquence — et **ne le corrige pas d'elle-même**.

Le propriétaire décide :

- **Il donne l'aval** → Claude corrige et commit, le propriétaire relit le diff.
- **Il ne donne pas l'aval** → Claude n'y touche pas. La réparation revient alors à
  l'auto-amélioration de Jarvis (Gemini en renfort) : le propriétaire l'ajoute aux
  demandes d'amélioration, Jarvis propose un correctif, et le propriétaire l'active
  avec ✅. Claude ne force jamais ce correctif à sa place.

Nuance honnête : les **fichiers du cœur** (liste ci-dessous) ne peuvent pas être
réparés par l'**auto-amélioration automatique** (la nuit) : elle leur est interdite.
Pour un bug dans un fichier du cœur, il y a deux issues : l'aval du propriétaire pour
que Claude corrige, ou la voie « proposition de cœur » ci-dessous (Gemini propose, le
propriétaire relit le diff et valide).

## Fichiers du cœur — jamais modifiés tout seuls, modifiables seulement sur diff relu

L'auto-amélioration **automatique** de Jarvis (la nuit) ne touche **jamais** aux
fichiers du cœur listés dans `growth.py` / `core_proposals.py`
(`config.py`, `claude_bridge.py`, `brain.py`, `drone.py`, `security.py`, `main.py`,
`telegram_bot.py`, `tools.py` ; jamais `.env`). Ce garde-fou ne se retire pas.

Une seule porte est ouverte, étroite (`core_proposals.py`) : **sur demande explicite
du propriétaire**, un renfort (Gemini) PROPOSE un changement d'un fichier du cœur.
Alors, et seulement alors :
- on calcule le **diff** et on lance les **tests dans une copie isolée** ;
- le propriétaire **lit le diff** et **valide** (commande « valide cœur ») ;
- rien n'est écrit sans cette validation, l'ancien fichier est sauvegardé en `.bak`,
  et un redémarrage est nécessaire.
Cette porte ne s'ouvre jamais toute seule, jamais la nuit, jamais sans le diff sous les
yeux du propriétaire. `.env` en est toujours exclu.

## Rien ne s'applique sans l'humain

Aucune amélioration écrite par Jarvis (Gemini ou Claude en renfort) n'est appliquée
sans l'approbation explicite du propriétaire. La chaîne reste :
génération → sandbox → tests qui passent → **✅ du propriétaire** → chargement à chaud.
Ne retire ni ne contourne aucune de ces étapes.

## Secrets

Les secrets (jetons, clés) vivent dans `.env` (ignoré par git). Ne mets jamais de vraie
valeur dans le code, dans `.env.example`, ou dans un commit. `.env.example` ne contient
que des étiquettes vides.
