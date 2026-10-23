# OSCLinux

OSCLinux est composé du programme principal et de son gestionnaire de mises à jour.

Utilise Python 3.10 ou une version plus récente et un environnement virtuel local :

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python OSCLinuxUpdater.py
```

La fenêtre **OSCLinux Updater** vérifie les releases GitHub sans bloquer son interface. Son bouton **Lancer OSCLinux** ouvre le programme principal dans un processus séparé. OSCLinux peut aussi être lancé directement avec `python OSCLinux.py`.

Le gestionnaire propose les versions stables plus récentes. Après confirmation, il télécharge et prépare la mise à jour pour le prochain lancement. Le programme applique les fichiers préparés au démarrage et redémarre afin de charger la nouvelle version.

Les vérifications réseau utilisent HTTPS avec un délai borné. Les archives sont limitées à 50 Mio, vérifiées avec le digest SHA-256 de GitHub et extraites uniquement pour les chemins autorisés (`OSCLinux.py`, `OSCLinuxUpdater.py`, `osclinux_updater.py` et `osclinux/`). Les chemins traversants, liens symboliques, archives trop volumineuses et redirections vers des hôtes inconnus sont refusés. L'installation conserve une sauvegarde et tente une restauration en cas d'échec. Les paramètres et fichiers hors liste ne sont pas remplacés.

Une erreur réseau ou GitHub n'empêche pas le démarrage de l'application.

Pour vérifier le canal manuellement :

```sh
source .venv/bin/activate
python OSCLinuxUpdater.py --check-updates
```

Pour exécuter les vérifications de régression :

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
```

## Publier une mise à jour

1. Mets `APP_VERSION` à jour dans `osclinux/version.py`.
2. Publie une GitHub Release avec un tag sémantique, par exemple `v0.2.0`.
3. Ajoute exactement un fichier nommé `OSCLinux-update.zip`.
4. Place à la racine du ZIP `OSCLinux.py`, `OSCLinuxUpdater.py`, `osclinux_updater.py` et les fichiers du paquet `osclinux/`. N'inclus pas les paramètres ou données utilisateur.
5. Publie la release. GitHub doit fournir le digest SHA-256 du fichier ; le gestionnaire refusera une archive sans ce digest.
