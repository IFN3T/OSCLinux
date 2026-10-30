# OSCLinux

OSCLinux est un gestionnaire de modules qui alterne des informations dans la chatbox OSC de VRChat.

## Installation et lancement

Python 3.10 ou plus récent est requis. Utilise un environnement virtuel local :

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python OSCLinuxUpdater.py
```

La fenêtre **OSCLinux Updater** vérifie les releases et le bouton **Lancer OSCLinux** ouvre l’application principale puis ferme le gestionnaire. OSCLinux peut aussi être démarré directement avec `python OSCLinux.py`.

## Catalogue de modules

Aucun module n’est installé par défaut. Dans **Modules**, la liste du catalogue affiche la description, la version et l’auteur. Le bouton vert `+` installe un module ; une fois installé, `×` le retire, `⚙` ouvre ses paramètres et `⬆` apparaît quand une mise à jour est disponible. Les fichiers sont téléchargés depuis les chemins centralisés du dépôt, puis contrôlés par le SHA-256 publié dans `modules/manifest.json`. Le manifeste ne contient pas d’URL de mise à jour par module.

Le catalogue fournit actuellement Spotify, CPU/RAM/GPU, températures, météo, horloge et texte personnalisé. Spotify lit les lecteurs MPRIS via `playerctl` (optionnel) ; la météo utilise les API Open-Meteo. Les options de chaque module sont disponibles après son installation. Le texte personnalisé accepte `{time}`, `{date}` et `{city}`.

Une fois des modules installés et activés, règle leur ordre dans **Paramètres généraux** puis démarre le script. Le mode alternance envoie un module à la fois ; les autres modes utilisent le premier module actif ou combinent les valeurs. Les messages OSC utilisent `/chatbox/input` et sont limités à 144 caractères. VRChat doit avoir OSC activé.

Chaque paquet Python du catalogue expose `get_text(options) -> str`. Le manifeste définit l’identifiant, le nom, la description, l’auteur, la version, l’empreinte SHA-256 et les champs de réglage ; le gestionnaire calcule le chemin du paquet à partir de l’identifiant. Les paramètres sont conservés dans `~/.config/osclinux/settings.json`. L’option de lancement de session crée ou retire le fichier `.desktop` dans `~/.config/autostart/`.

## Catalogue de thèmes

Dans **Thèmes**, les deux apparences intégrées — **OSCLinux Sombre** et **Clair** — sont toujours disponibles, même hors connexion, et ne peuvent pas être supprimées. Les thèmes optionnels sont récupérés depuis `themes/manifest.json` et peuvent être installés, appliqués, mis à jour ou supprimés. Chaque paquet est un fichier JSON limité aux réglages autorisés ; son empreinte SHA-256 est vérifiée avant installation. Les thèmes installés sont stockés dans `~/.local/share/osclinux/themes/`.

Le catalogue contient **Cyberpunk 2077**, **Minecraft** et **Sakura**. Les thèmes intégrés ne figurent pas dans ce catalogue et restent protégés contre la désinstallation. Une entrée de manifeste contient `id`, `name`, `description`, `author`, `version`, `sha256` et la liste `assets`. Le paquet correspondant est `themes/packages/<id>.json`. Les versions de schéma 1 et 2 restent prises en charge. Le schéma 3 permet à chaque thème de définir directement sa palette, ses formes, ses bordures, ses dessins d’icônes et les fichiers de fond, d’icône ou de texture auxquels il fait référence.

Les ressources distantes doivent être placées sous `themes/assets/<id>/` dans ce dépôt. Les URL doivent utiliser `raw.githubusercontent.com` et viser exactement le dossier du thème ; les redirections vers d’autres chemins ou hôtes sont refusées. Chaque élément `assets` du manifeste contient `name`, `url` et `sha256`, et l’ensemble doit correspondre exactement aux fichiers déclarés par le paquet. Un thème peut référencer `background.png|jpg|webp|gif|webm`, `icon-*.png|webp` et `texture-*.png|jpg|webp`. Les identifiants de composants et de surfaces permis, avec un exemple JSON complet, sont détaillés dans `themes/README.md`.

```json
{
  "schema_version": 3,
  "colors": { "window_bg": "#101020" },
  "shape": { "button_radius": 10 },
  "background": {
    "asset": "background.webp",
    "fit": "cover",
    "image_opacity": 100,
    "overlay_color": "#000000",
    "overlay_opacity": 35
  },
  "pattern": { "style": "sakura", "opacity": 12, "color": "#ff80b5" }
}
```

Les ressources sont limitées à 64 Mio au total, avec des quotas séparés pour les fonds, icônes et textures, et vérifiées par empreinte. Les images sont décodées avant installation, avec limites de dimensions, de nombre d’images animées et de pixels décodés. Les WebM doivent avoir une signature EBML valide et sont lus en boucle sans sortie audio. Les icônes dessinées utilisent des primitives géométriques bornées définies dans le JSON. Les thèmes ne peuvent pas fournir de HTML, JavaScript, SVG, feuille de style ou fichier local arbitraire.

## Mises à jour

`osclinux_updater.py` consulte les releases stables de `IFN3T/OSCLinux`. Une nouvelle version est proposée à l’utilisateur ; le téléchargement n’a lieu qu’après confirmation. Les archives sont limitées à 50 Mio, contrôlées avec le digest SHA-256 fourni par GitHub et extraites uniquement dans les fichiers de l’application, les manifestes et paquets, les ressources de thème validées et `osclinux/`. Les paramètres, modules et thèmes déjà installés ainsi que les autres données utilisateur ne sont pas remplacés.

Pour vérifier le canal manuellement :

```sh
source .venv/bin/activate
python OSCLinuxUpdater.py --check-updates
```

Pour publier une mise à jour, augmente `APP_VERSION` dans `osclinux/version.py`, crée une release sémantique (par exemple `v0.3.0`) et joins exactement un fichier `OSCLinux-update.zip` contenant les fichiers application, les manifestes et paquets, les fichiers référencés sous `themes/assets/<id>/` et les répertoires `osclinux/`. GitHub doit fournir le digest SHA-256 de l’archive.
