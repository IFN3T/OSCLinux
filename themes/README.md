# Ressources des thèmes

Un thème peut référencer des images depuis son fichier `packages/<id>.json`. Les fichiers sont rangés dans `themes/assets/<id>/` et chaque ressource utilisée doit aussi être déclarée dans `manifest.json`, avec son URL `raw.githubusercontent.com` et son empreinte SHA-256.

```json
{
  "schema_version": 3,
  "background": {"asset": "background.webp", "fit": "cover"},
  "icons": {
    "brand": "icon-brand.png",
    "audio_player": "icon-audio.png",
    "temperatures": "icon-temperature.webp"
  },
  "textures": {
    "panel": "texture-panel.png",
    "button": "texture-button.webp"
  }
}
```

Les identifiants d’icône acceptés sont `brand`, `modules`, `timeline`, `osc`, `themes`, `settings`, `journal`, `audio_player`, `system`, `temperatures`, `weather`, `clock` et `custom`. Les surfaces texturables sont `panel`, `card`, `sidebar`, `topbar` et `button`.

Les noms de fichiers sont volontairement limités à `background.*`, `icon-*.png|webp` et `texture-*.png|jpg|jpeg|webp`. Le manifeste doit fournir pour chaque fichier utilisé une entrée de ce type :

```json
{
  "name": "icon-brand.png",
  "url": "https://raw.githubusercontent.com/IFN3T/OSCLinux/main/themes/assets/pikachu/icon-brand.png",
  "sha256": "<empreinte SHA-256 du fichier>"
}
```

Le validateur refuse les chemins hors du dossier correspondant à l’identifiant du thème, les ressources inutilisées, les formats non pris en charge et les fichiers qui dépassent leurs quotas. Les icônes et textures sont des images raster décodées par Qt ; un thème ne peut pas fournir de code, de feuille de style, de SVG ou de script. Le total des ressources d’un thème est limité à 64 Mio.
