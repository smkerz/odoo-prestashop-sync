# TODO

Liste de travail du connecteur PrestaShop ↔ Odoo et du module PrestaShop `prestashopodoo`.
Mise à jour le 4 octobre 2026. Aucune donnée personnelle ne doit figurer dans ce fichier.

Environnement de test, procédure et scénarios : voir `tests/e2e/README.md`.

---

## 1. À faire rapidement

| # | Sujet | Ce qu'il faut faire | Qui |
|---|---|---|---|
| 2 bis | Contrôle des inscriptions et désinscriptions en masse | Vérifier vers le 19 octobre 2026, puis début novembre, qu'aucune vague anormale d'inscriptions ou de désinscriptions n'est apparue depuis la remise en route du 4 octobre. Requêtes et repères : voir « Contrôle périodique » en bas de ce fichier | Exploitation, puis dev |
| 3 | Sauvegardes locales | Sortir du dépôt le dossier de sauvegardes de la base (exclu de git, mais présent dans le dossier de travail) | Exploitation |
| 4 | Dépôts GitHub | Décider de leur visibilité : ils sont publics et contiennent des fichiers d'adresses | Exploitation |
| 5 | Clé d'API du `.hair` | La régénérer et la mettre à jour dans le backend Odoo : elle est apparue en clair dans des logs | Exploitation |
| 6 | Secret webhook | Le changer s'il correspond à la valeur restée dans l'historique du dépôt du module PrestaShop | Exploitation |
| 7 | Fichiers de données dans le dépôt | Retirer `bounces.csv`, `blacklist_import.csv`, `hard_bounces.txt` et les scripts ponctuels `_*.py`, y compris de l'historique | Dev, après le point 4 |

## 2. Fiabilité du connecteur

| # | Sujet | Ce qu'il faut faire |
|---|---|---|
| 8 | Synchro abandonnée marquée « OK » | Quand l'API PrestaShop ne répond pas, la synchro s'arrête sans rien désinscrire, mais le journal affiche « OK » avec des compteurs à zéro. Afficher une erreur claire et alerter (activité ou e-mail). C'est ce qui a masqué une panne de plusieurs jours |
| 9 | Plafond Presta → Odoo | Refuser une synchro qui désinscrirait une part anormale d'une liste en un passage, comme le fait déjà le push Odoo → Presta (`opt_out_push_max_per_run`) |
| 10 | Comptes en double (erreur 141) | PrestaShop refuse par son API toute modification d'un client dont l'adresse e-mail est aussi celle d'un autre compte. Le push échoue alors à chaque passage pour ces clients. Soit dédoublonner dans la boutique, soit retirer le consentement par un endpoint du module, et ne journaliser l'erreur qu'une fois |
| 11 | Deux comptes reliés à la même fiche | Quand deux comptes PrestaShop pointent vers le même contact Odoo, l'adresse e-mail du contact suit le dernier compte modifié |
| 11 bis | Client existant qui crée un compte | Quand le webhook de consentements retrouve le contact par son adresse e-mail (contact déjà présent dans Odoo), il ne crée pas la correspondance avec le compte PrestaShop. Le webhook d'adresse qui suit est alors ignoré (« customer mapping not found »), jusqu'au prochain import clients. Créer la correspondance dès le webhook |
| 12 | Backend sans client importé | `_sync_email_marketing_lists` sort avant de traiter les inscrits par e-mail seul quand aucun client n'est encore importé |
| 13 | Plafond de 5 000 sur les listes d'abonnés | `customer_max_per_run` tronque la liste des abonnés lue dans PrestaShop ; au-delà, les suivants seraient désinscrits. Loin des volumes actuels |
| 14 | Écho des webhooks | Chaque modification faite par Odoo dans PrestaShop revient sous forme de webhook. Sans conséquence, mais c'est du trafic et du bruit dans les logs |
| 15 | Sécurité des échanges | La clé d'API passe dans l'URL des endpoints du module, et `webhookconfig` renvoie le secret en clair. À corriger des deux côtés ensemble |
| 16 | Étiquettes « révoqué » | `newsletter_revoked_tag_id` et `partner_offers_revoked_tag_id` ne sont affichées nulle part et ne pilotent rien. Les supprimer ou leur donner un rôle |

## 3. Qualité du code

| # | Sujet | Ce qu'il faut faire |
|---|---|---|
| 17 | Tests de la logique Odoo | Les tests sans serveur couvrent le client API, les règles de révocation et la vérification des webhooks. La synchro des consentements n'est testée que par la batterie `tests/e2e` |
| 18 | Découpage de `models/prestashop_backend.py` | Environ 2 400 lignes : configuration, consentements, adresses, clients, commandes. À répartir par domaine |
| 19 | Recherche du client dans le webhook de consentements | Elle a sa propre recherche par correspondance, alors que les trois chemins d'import partagent `_upsert_partner_from_customer_node` |
| 20 | Écritures groupées sur le contact | Le webhook de consentements fait jusqu'à six écritures sur la même fiche |
| 21 | Fichiers hérités à la racine | `test_battery.py`, `TEST_PLAN.md`, `PROMPT_FIX_UNSUBSCRIBE.md` : antérieurs à `tests/` et à `tests/e2e/`, à relire ou retirer |
| 22 | `webhookconfig.php` (module PrestaShop) | Seul endpoint non aligné sur la classe commune `PrestashopodooApiController` |
| 23 | `cron_sync_addresses` et `_sync_addresses` | Plus référencés dans le code ; vérifier qu'aucune tâche planifiée créée à la main ne les appelle avant de les supprimer |

## 4. Exploitation

| # | Sujet | Ce qu'il faut faire |
|---|---|---|
| 25 | Boutiques de test recopiées depuis la production | Refaire après chaque recopie : l'exception du mot de passe HTTP pour `/api/` et `/module/prestashopodoo/`, la configuration du module vers l'Odoo de test, la désactivation du captcha, le mode « ne jamais envoyer d'e-mails » |
| 26 | Copie de la base Odoo vers la base de test | Cocher « Neutraliser » à la duplication, puis rediriger les backends vers les boutiques de test avant de démarrer le conteneur |
| 26 bis | Tutoriel d'installation d'Odoo (metrodyn.fr) : instances multiples | Y ajouter la section sur plusieurs instances Odoo partageant un serveur PostgreSQL : `db_name` par instance en plus de `dbfilter`, et redémarrage nécessaire après toute mise à jour de code. Le texte est rédigé, il reste à le publier | Exploitation |
| 26 ter | Tutoriel d'installation d'Odoo (metrodyn.fr) : copie vers un environnement de test | Rédiger puis publier un encadré sur la duplication d'une base de production : cocher « Neutraliser », couper les tâches planifiées et les envois d'e-mails, rediriger les connexions externes vers les environnements de test avant de démarrer l'instance | Dev pour la rédaction, exploitation pour la publication |
| 27 | Désinscriptions d'août 2026 sur le `.fr` | Une soixantaine de clients désinscrits par cron du 11 au 16 août, sans modification en masse dans la boutique. Cause inconnue |

## 5. Nouvelles synchronisations

Aucune n'est commencée, sauf mention. Attendre que la synchronisation actuelle ait tourné quelques semaines sans incident.

| # | Synchronisation | Sens | Ce que ça apporte | Dépend de | État |
|---|---|---|---|---|---|
| 28 | Produits | À décider | Un catalogue cohérent, indispensable pour importer des commandes proprement | Choix de la référence du catalogue (PIM, Odoo ou boutique) | Seule la table de correspondance existe |
| 29 | Commandes | Boutique → Odoo | Chiffre d'affaires, historique d'achat par client | Produits | Code présent, désactivé, jamais testé |
| 30 | Stock | Odoo → boutique | Ne pas vendre un article épuisé, avec trois boutiques sur le même stock | Produits | |
| 31 | États de commande et suivi colis | Odoo → boutique | Le client voit « expédié » et son numéro de suivi | Commandes | |
| 32 | Prix et promotions | Odoo → boutique | Un seul endroit pour les tarifs des trois boutiques. La plus risquée | Produits | |
| 33 | Factures et avoirs | Boutique → Odoo | Comptabilité sans ressaisie | Commandes | |
| 34 | Paiements | Boutique → Odoo | Rapprochement bancaire | Commandes, factures | |
| 35 | Retours et remboursements | Les deux | Stock et comptabilité justes après un retour | Commandes | |
| 36 | Segmentation marketing | Boutique → Odoo | Newsletters ciblées : langue, pays, puis total acheté et date du dernier achat | Rien pour langue et pays ; commandes pour les achats | |
| 37 | Paniers abandonnés | Boutique → Odoo | Relances depuis Odoo | Produits | |
| 38 | Informations professionnelles | Boutique → Odoo | Société, numéro de TVA, groupe de clients | Rien | |
| 39 | Adresses e-mail en erreur | Odoo → boutique | Marquer dans la boutique les adresses qui rejettent les e-mails | Rien | |

---

## Contrôle périodique : vagues d'inscriptions ou de désinscriptions

À lancer sur le serveur Odoo, en lecture seule. Aucune adresse n'est affichée.

Désinscriptions et inscriptions groupées à la même minute, depuis le 5 octobre 2026 :

```bash
docker exec odoo17-db psql -U odoo17 -d mcdavidian -c "select l.name, to_char(s.opt_out_datetime,'YYYY-MM-DD HH24:MI') as minute_utc, count(*) as desinscriptions from mailing_subscription s join mailing_list l on l.id = s.list_id where s.opt_out and s.opt_out_datetime >= '2026-10-05' and l.name ilike '%Prestashop - mcdavidian.%' group by 1, 2 having count(*) >= 5 order by 3 desc limit 20;" -c "select l.name, to_char(s.create_date,'YYYY-MM-DD HH24:MI') as minute_utc, count(*) as inscriptions from mailing_subscription s join mailing_list l on l.id = s.list_id where s.create_date >= '2026-10-05' and l.name ilike '%Prestashop - mcdavidian.%' group by 1, 2 having count(*) >= 5 order by 3 desc limit 20;"
```

Abonnés actifs par liste, et dernières erreurs du connecteur :

```bash
docker exec odoo17-db psql -U odoo17 -d mcdavidian -c "select l.name, count(*) filter (where not s.opt_out) as abonnes_actifs, count(*) filter (where s.opt_out) as desinscrits from mailing_subscription s join mailing_list l on l.id = s.list_id where l.name ilike '%Prestashop - mcdavidian.%' group by 1 order by 1;" -c "select to_char(create_date,'MM-DD HH24:MI') as quand, operation, left(message, 100) as message from prestashop_sync_log where status = 'error' and create_date > now() - interval '15 days' and message not like 'Failed to sync consents to PrestaShop.' order by id desc limit 15;"
```

Comment lire le résultat :

- **Une ligne à 5 désinscriptions ou plus à la même minute** est suspecte : de vraies personnes ne se désinscrivent pas ensemble. Exception connue : une campagne envoyée peu avant, qui provoque des désinscriptions étalées sur plusieurs minutes, pas concentrées sur une seule.
- **Une ligne à 5 inscriptions ou plus à la même minute** signale soit un import de clients (normal après un rattrapage), soit une vague de robots sur le formulaire newsletter.
- **Une erreur « push aborted … revocations exceed the limit »** signifie que le plafond de sécurité a bloqué un envoi anormal vers une boutique : ne pas forcer avec le bouton, chercher d'abord la cause avec « Preview ».
- **Repères au 5 octobre 2026**, clients abonnés à la newsletter dans les boutiques : `.com` environ 170, `.fr` 70, `.hair` 161. Une chute brutale de l'un de ces chiffres est le signe d'un incident.

Les erreurs « Failed to sync consents to PrestaShop. » sont exclues de la seconde requête : ce sont les comptes en double connus (point 10).

---

## Limites connues et voulues

- **Odoo → PrestaShop est en révocation seule.** Odoo ne remet jamais `newsletter=1` ni `optin=1` dans la boutique.
- **Le push n'agit que sur un signal explicite** : désinscription d'une liste ou liste noire. Un contact simplement absent d'une liste Odoo n'est jamais désinscrit dans PrestaShop.
- **`respect_odoo_opt_out`** : un contact désinscrit dans Odoo n'est pas réinscrit par la synchro planifiée, même si PrestaShop l'indique abonné. Seul un webhook (nouvelle action du client) lève la désinscription.
- **Inscrits par e-mail seul supprimés de PrestaShop** : ils restent dans Odoo. Seules les lignes désactivées (`active=0`) sont désinscrites, parce que c'est un signal explicite. Une désinscription par le formulaire de la boutique est transmise par le module PrestaShop (1.3.2 et suivants).
- **Le captcha du formulaire newsletter** n'est pas couvert par les tests : une inscription réelle à la main reste le seul moyen de le vérifier.
- **nginx du `.fr` et du `.hair`** rejette l'agent `python-requests` (403). Le connecteur envoie `OdooPrestashopConnector/1.0`. En cas de nouveau 403 sur l'API, regarder d'abord les règles anti-robots.
- **Un conteneur Odoo ne charge le code qu'au démarrage**, et chaque conteneur doit avoir `db_name` dans sa configuration, sinon il exécute les tâches planifiées de toutes les bases du serveur.
