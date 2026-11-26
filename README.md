# NobodyDoc

Anonymise **en local** des documents Word, Excel, PowerPoint et des mails avant
de les envoyer à une IA ou à un prestataire. Aucune donnée ne quitte le poste.

> État : étape 1 (moteur d'anonymisation + ligne de commande). L'interface
> graphique, la table de correspondance chiffrée et l'exécutable Windows
> portable arrivent dans les étapes suivantes.

## Ce qui est masqué

| Type | Exemple | Comment |
|---|---|---|
| Noms de personnes | Jean Dupont → `[PERSONNE_1]` | modèle de langue français local (spaCy) |
| Entreprises | Acme Industries → `[ORGANISATION_1]` | modèle de langue + dictionnaire |
| Termes de l'entreprise | clients, acronymes, départements, produits | dictionnaire (CSV ou JSON) |
| E-mails, téléphones (FR et international) | | règles |
| IBAN, cartes bancaires, n° de sécurité sociale | | règles avec clé de contrôle |
| SIREN / SIRET / TVA intracommunautaire | | règles |
| Adresses postales, codes postaux + villes | | règles |
| Sites web, adresses IP | | règles |

Une même valeur reçoit toujours le même jeton, dans tous les fichiers traités
ensemble. Un nom repéré une fois est masqué partout, y compris seul
(« Dupont », « M. Dupont ») ou dans une cellule Excel isolée.

## Formats

* **Word** (.docx) : texte, tableaux, en-têtes et pieds de page, notes,
  commentaires et leurs auteurs, révisions (y compris le texte supprimé),
  zones de texte, liens, graphiques.
* **Excel** (.xlsx) : cellules, commentaires et leurs auteurs, graphiques.
  Les nombres et formules sont conservés.
* **PowerPoint** (.pptx) : diapositives, notes du présentateur, graphiques
  (et leurs données Excel incorporées).
* **Mails** (.eml, .msg Outlook → .eml) : expéditeur et destinataires, objet,
  corps texte et HTML, pièces jointes Office. Les en-têtes techniques
  (serveurs, adresses IP) sont retirés, ainsi que les pièces jointes dans un
  format non pris en charge (PDF, images).
* **Texte** (.txt, .csv, .md, .json, .log).

Pour tous les formats Office : la mise en forme est conservée, l'auteur et la
société sont effacés des propriétés et la miniature d'aperçu est supprimée.
Les originaux ne sont jamais modifiés : une copie `nom_anonymise.ext` est créée.

**Limites connues** : le texte contenu dans les images n'est pas lu
(un avertissement est affiché) ; les noms d'onglets Excel sont signalés mais
pas renommés ; les anciens formats .doc/.xls/.ppt ne sont pas pris en charge.

## Dictionnaire de l'entreprise

Fichier CSV (modifiable dans Excel, séparateur `;`), voir
[`dictionnaire_exemple.csv`](dictionnaire_exemple.csv) :

```
terme;categorie;variantes
Acme;CLIENT;Acme Industries|ACME Corp
DSI;DEPARTEMENT;
Microsoft;EXCLUSION;
```

* La catégorie donne le nom du jeton (`[CLIENT_1]`, `[DEPARTEMENT_1]`...).
* Les variantes partagent le jeton du terme principal.
* Un terme en majuscules (acronyme) n'est cherché qu'en majuscules.
* La catégorie `EXCLUSION` liste les mots à ne jamais masquer.

## Utilisation (ligne de commande, pour l'instant)

```
pip install -r requirements.txt
python -m nobodydoc rapport.docx clients.xlsx mail.msg --dictionnaire dico.csv --sortie anonymise --table
```

Options : `--sans-ner` (règles et dictionnaire seulement), `--lieux` (masque
aussi villes et pays), `--table` (affiche la correspondance jeton → valeur).

## Développement

```
pip install -r requirements-dev.txt
pytest
```

Les tests génèrent des documents d'exemple et vérifient qu'aucune valeur
sensible ne subsiste nulle part dans les fichiers produits (XML brut compris).
