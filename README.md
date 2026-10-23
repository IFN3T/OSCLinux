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

## Modules inclus

- **Spotify** lit le lecteur MPRIS de Linux via `playerctl` (optionnel) et affiche titre, artiste et progression.
- **CPU / RAM / GPU** lit les statistiques système Linux et `nvidia-smi` si disponible.
- **Températures** lit les zones thermiques Linux et les températures NVIDIA si disponibles.
- **Météo** récupère les conditions courantes pour une ville choisie via les API Open-Meteo.
- **Horloge** affiche l’heure au format 12 h ou 24 h.
- **Personnalisé** envoie un texte libre avec `{time}`, `{date}` et `{city}` comme variables.

Active les modules souhaités, règle leur durée d’affichage et l’ordre, puis démarre le script. Le mode alternance envoie un module à la fois ; les autres modes utilisent le premier module actif ou combinent les valeurs. Les messages OSC utilisent `/chatbox/input` et sont limités à 144 caractères. L’adresse et les ports OSC sont configurables dans l’interface. VRChat doit avoir OSC activé.

Les paramètres sont conservés dans `~/.config/osclinux/settings.json`. L’option de lancement de session crée ou retire le fichier `.desktop` dans `~/.config/autostart/`.

## Mises à jour

`osclinux_updater.py` consulte les releases stables de `IFN3T/OSCLinux`. Une nouvelle version est proposée à l’utilisateur ; le téléchargement n’a lieu qu’après confirmation. Les archives sont limitées à 50 Mio, contrôlées avec le digest SHA-256 fourni par GitHub et extraites uniquement dans `OSCLinux.py`, `OSCLinuxUpdater.py`, `osclinux_updater.py` et `osclinux/`. Les paramètres, modules externes et autres données ne sont pas remplacés.

Pour vérifier le canal manuellement :

```sh
source .venv/bin/activate
python OSCLinuxUpdater.py --check-updates
```

Pour publier une mise à jour, augmente `APP_VERSION` dans `osclinux/version.py`, crée une release sémantique (par exemple `v0.3.0`) et joins exactement un fichier `OSCLinux-update.zip` contenant les deux scripts, `osclinux_updater.py` et le répertoire `osclinux/`. GitHub doit fournir le digest SHA-256 de l’archive.
