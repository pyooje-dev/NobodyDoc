# NobodyDoc : guide d'utilisation

NobodyDoc remplace les informations sensibles de vos documents par des jetons
comme **[PERSONNE_1]** ou **[CLIENT_2]**, pour les envoyer sans risque à une IA
ou à un prestataire. **Tout se passe sur votre ordinateur** : aucun fichier
n'est envoyé sur Internet, et vos originaux ne sont jamais modifiés.

## Anonymiser

1. **Déposez vos fichiers** dans la fenêtre : Word, Excel, PowerPoint, mails
   Outlook (.msg, .eml) ou fichiers texte. Vous pouvez aussi déposer un dossier
   entier.
2. Cliquez sur **Analyser les fichiers**.
3. **Vérifiez la liste.** Chaque ligne est une information qui va être masquée.
   * Décochez ce qui ne doit pas l'être.
   * Les lignes « Modèle (à vérifier) » sont des suppositions de l'outil :
     regardez-les en priorité.
   * Un nom ou un code oublié ? Tapez-le dans **Ajouter** : il sera masqué
     partout.
4. Cliquez sur **Anonymiser**. Les copies sont créées dans un dossier
   « Anonymisé », à côté de vos fichiers.
5. **Relisez les copies avant de les envoyer.** Le texte contenu dans les
   images (captures d'écran, scans) n'est pas lu.

Une même information reçoit toujours le même jeton : « Jean Dupont » devient
[PERSONNE_1] dans tous les fichiers traités ensemble.

## Remettre les vrais noms dans la réponse

Quand l'IA ou le prestataire vous répond avec des jetons, ouvrez l'onglet
**Restaurer les vrais noms**, puis :

* collez le texte reçu et cliquez sur **Restaurer** ;
* ou glissez le document reçu sur la page : une copie « _restaure » est créée.

Choisissez la table correspondant à l'envoi (date et noms des fichiers). Les
tables sont chiffrées : seul votre compte Windows, sur ce poste, peut les lire.
Elles sont supprimées automatiquement après 90 jours (réglable).

## Le dictionnaire de l'entreprise

Cliquez sur **Dictionnaire de l'entreprise** pour indiquer :

* les **termes à toujours masquer** : clients, produits, projets, acronymes
  internes, noms de services. La catégorie choisie donne le nom du jeton
  (CLIENT → [CLIENT_1]) ;
* les **mots à ne jamais masquer** : noms de logiciels, villes, termes
  courants que l'outil prend à tort pour des noms.

Le dictionnaire se remplit aussi depuis l'écran de vérification, avec les
boutons **Toujours masquer** et **Ne jamais masquer**. Utilisez **Exporter**
pour le partager avec vos collègues, et **Importer** pour récupérer le leur.

## Ce qui est masqué

Noms de personnes et d'entreprises, e-mails, téléphones, adresses postales,
IBAN, cartes bancaires, numéros de sécurité sociale, SIREN/SIRET/TVA, sites
web, adresses IP et les termes de votre dictionnaire. L'outil efface aussi
l'auteur et la société cachés dans les propriétés des fichiers, les auteurs des
commentaires et les informations techniques des mails.

## Bon à savoir

* Les anciens formats (.doc, .xls, .ppt) doivent d'abord être réenregistrés au
  format récent (Fichier > Enregistrer sous).
* Un fichier protégé par mot de passe doit être déverrouillé avant.
* Les pièces jointes PDF ou images d'un mail sont retirées de la copie.
* Les noms d'onglets Excel ne sont pas renommés : un avertissement les signale.
