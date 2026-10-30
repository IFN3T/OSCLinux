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

Dans **Thèmes**, le thème de base OSCLinux est toujours installé et ne peut pas être supprimé. Les autres thèmes sont récupérés depuis `themes/manifest.json` et peuvent être installés, appliqués, mis à jour ou supprimés. Chaque paquet est un fichier JSON limité à des couleurs de la palette autorisée ; son empreinte SHA-256 est vérifiée avant installation. Les thèmes installés sont stockés dans `~/.local/share/osclinux/themes/`.

Une entrée de manifeste contient `id`, `name`, `description`, `author`, `version` et `sha256`. Le paquet correspondant est `themes/packages/<id>.json`. Les versions de schéma 1 et 2 restent prises en charge. Le schéma 3 ajoute des motifs décoratifs prédéfinis et une texture facultative en PNG, JPG/JPEG, WebP, GIF ou WebM. La texture est déclarée comme un seul fichier `background.<extension>` dans `background.asset`, puis référencée dans le manifeste par `assets` avec une URL HTTPS et une empreinte SHA-256.

Les textures distantes doivent utiliser `raw.githubusercontent.com` ; les redirections vers d’autres hôtes sont refusées. Un élément `assets` du manifeste contient `name`, `url` et `sha256`, et doit correspondre au seul fichier déclaré par le paquet. Exemple de réglages pour un fond animé :

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

Les téléchargements sont limités à 16 Mio et vérifiés par empreinte. Les images sont décodées avant installation, avec limites de dimensions, de nombre d’images animées et de pixels décodés. Les WebM doivent avoir une signature EBML valide et sont lus en boucle sans sortie audio. Les thèmes ne peuvent pas fournir de HTML, JavaScript, SVG, CSS libre, URL externe ou fichier local arbitraire ; les formes, couleurs, voiles et motifs restent limités à des réglages connus.

## Mises à jour

`osclinux_updater.py` consulte les releases stables de `IFN3T/OSCLinux`. Une nouvelle version est proposée à l’utilisateur ; le téléchargement n’a lieu qu’après confirmation. Les archives sont limitées à 50 Mio, contrôlées avec le digest SHA-256 fourni par GitHub et extraites uniquement dans les fichiers de l’application, `modules/manifest.json`, `themes/manifest.json`, `themes/packages/*.json` et `osclinux/`. Les paramètres, modules et thèmes déjà installés ainsi que les autres données utilisateur ne sont pas remplacés.

Pour vérifier le canal manuellement :

```sh
source .venv/bin/activate
python OSCLinuxUpdater.py --check-updates
```

Pour publier une mise à jour, augmente `APP_VERSION` dans `osclinux/version.py`, crée une release sémantique (par exemple `v0.3.0`) et joins exactement un fichier `OSCLinux-update.zip` contenant les fichiers application, `modules/manifest.json`, `themes/manifest.json`, `themes/packages/*.json` et les répertoires `osclinux/`. GitHub doit fournir le digest SHA-256 de l’archive.
