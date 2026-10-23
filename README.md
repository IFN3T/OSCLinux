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

## Mises à jour

`osclinux_updater.py` consulte les releases stables de `IFN3T/OSCLinux`. Une nouvelle version est proposée à l’utilisateur ; le téléchargement n’a lieu qu’après confirmation. Les archives sont limitées à 50 Mio, contrôlées avec le digest SHA-256 fourni par GitHub et extraites uniquement dans `OSCLinux.py`, `OSCLinuxUpdater.py`, `osclinux_updater.py`, `modules/manifest.json` et `osclinux/`. Les paramètres, modules externes et autres données ne sont pas remplacés.

Pour vérifier le canal manuellement :

```sh
source .venv/bin/activate
python OSCLinuxUpdater.py --check-updates
```

Pour publier une mise à jour, augmente `APP_VERSION` dans `osclinux/version.py`, crée une release sémantique (par exemple `v0.3.0`) et joins exactement un fichier `OSCLinux-update.zip` contenant `OSCLinux.py`, `OSCLinuxUpdater.py`, `osclinux_updater.py`, `modules/manifest.json` et le répertoire `osclinux/`. GitHub doit fournir le digest SHA-256 de l’archive.
