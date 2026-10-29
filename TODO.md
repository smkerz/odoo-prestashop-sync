# TODO

Liste de travail du connecteur PrestaShop ↔ Odoo et du module PrestaShop `prestashopodoo`.
Mise à jour le 29 octobre 2026. Aucune donnée personnelle ne doit figurer dans ce fichier.

Environnement de test, procédure et scénarios : voir `tests/e2e/README.md`.

---

## 1. À faire rapidement

| # | Sujet | Ce qu'il faut faire | Qui |
|---|---|---|---|
| 2 bis | Contrôle des vagues d'inscriptions et de désinscriptions | Premier contrôle fait le 29 octobre : aucune erreur en 15 jours, un résumé chaque jour, deux vagues le 11 octobre (30 sur le `.fr`, 22 sur le `.com`), toutes deux des lignes « e-mail seul » désactivées dans les boutiques, alerte reçue. Refaire vers le 5 novembre avec les requêtes de « Contrôle périodique » | Exploitation, puis dev |
| 3 | Sauvegardes locales | Sortir du dossier du dépôt le dossier de sauvegardes de la base (exclu de git, mais présent dans le dossier de travail) | Exploitation |
| 4 | Publication sur Odoo Apps | Les dépôts restent publics. La branche `17.0` (lue par Odoo Apps) contient la version de septembre, dans un sous-dossier : la remettre à jour à partir de `main` avant de publier | Dev |
| 8 | Robots sur les formulaires newsletter | Le captcha du `.hair` était désactivé : réactivé le 29 octobre (reCAPTCHA v3, newsletter protégée, script vérifié sur la page publique). Surveiller les résumés quelques jours (plus d'adresses Gmail truffées de points), puis désactiver dans la boutique les robots déjà inscrits ; l'alerte de vague de désinscriptions partira, c'est attendu | Exploitation |

## 2. Fiabilité du connecteur

| # | Sujet | Ce qu'il faut faire |
|---|---|---|
| 9 | Plafond Presta → Odoo | Refuser une synchro qui désinscrirait une part anormale d'une liste en un passage, comme le fait déjà le push Odoo → Presta (`opt_out_push_max_per_run`). L'alerte e-mail prévient déjà, mais après coup |
| 11 | Deux comptes reliés à la même fiche | Quand deux comptes PrestaShop pointent vers le même contact Odoo, l'adresse e-mail du contact suit le dernier compte modifié |
| 12 | Backend sans client importé | `_sync_email_marketing_lists` sort avant de traiter les inscrits par e-mail seul quand aucun client n'est encore importé |
| 13 | Plafond de 5 000 sur les listes d'abonnés | `customer_max_per_run` tronque la liste des abonnés lue dans PrestaShop ; au-delà, les suivants seraient désinscrits. Loin des volumes actuels |
| 14 | Écho des webhooks | Chaque modification faite par Odoo dans PrestaShop revient sous forme de webhook. Sans conséquence, mais c'est du trafic et du bruit dans les logs |
| 15 | Sécurité des échanges | La clé d'API passe dans l'URL des endpoints du module, et `webhookconfig` renvoie le secret en clair : à corriger des deux côtés ensemble. Le secret des webhooks fait 8 caractères et il est le même sur les trois boutiques : passer à 32 caractères ou plus, un par boutique (à changer dans le backend Odoo et dans la configuration du module, en même temps) |
| 16 | Étiquettes « révoqué » | `newsletter_revoked_tag_id` et `partner_offers_revoked_tag_id` ne sont affichées nulle part et ne pilotent rien. Les supprimer ou leur donner un rôle |
| 40 | Robot de Google Shopping | Il crée des comptes clients sur le `.com` (`storebotmail.joonix.net`) pour tester le parcours d'achat. Ils ne s'abonnent pas : les laisser, ou les exclure de l'import |

## 3. Qualité du code

| # | Sujet | Ce qu'il faut faire |
|---|---|---|
| 17 | Tests de la logique Odoo | Les tests sans serveur couvrent le client API, les règles de révocation, les notifications et la vérification des webhooks. La synchro des consentements n'est testée que par la batterie `tests/e2e` |
| 18 | Découpage de `models/prestashop_backend.py` | Environ 2 500 lignes : configuration, consentements, adresses, clients, commandes, notifications. À répartir par domaine |
| 19 | Recherche du client dans le webhook de consentements | Elle a sa propre recherche par correspondance, alors que les trois chemins d'import partagent `_upsert_partner_from_customer_node` |
| 20 | Écritures groupées sur le contact | Le webhook de consentements fait jusqu'à six écritures sur la même fiche |
| 21 | Fichiers hérités à la racine | `test_battery.py`, `TEST_PLAN.md`, `PROMPT_FIX_UNSUBSCRIBE.md` : antérieurs à `tests/` et à `tests/e2e/`, à relire ou retirer |
| 22 | `webhookconfig.php` (module PrestaShop) | Seul endpoint non aligné sur la classe commune `PrestashopodooApiController` |
| 23 | `cron_sync_addresses` et `_sync_addresses` | Plus référencés dans le code ; vérifier qu'aucune tâche planifiée créée à la main ne les appelle avant de les supprimer |

## 4. Exploitation

| # | Sujet | Ce qu'il faut faire | Qui |
|---|---|---|---|
| 25 | Boutiques de test recopiées depuis la production | Refaire après chaque recopie : l'exception du mot de passe HTTP pour `/api/` et `/module/prestashopodoo/`, la configuration du module vers l'Odoo de test, la désactivation du captcha, le mode « ne jamais envoyer d'e-mails » | Exploitation |
| 26 | Copie de la base Odoo vers la base de test | Cocher « Neutraliser » à la duplication, puis rediriger les backends vers les boutiques de test avant de démarrer le conteneur | Exploitation |
| 26 bis | Tutoriel metrodyn.fr : instances multiples | Y ajouter la section sur plusieurs instances Odoo partageant un serveur PostgreSQL : `db_name` par instance en plus de `dbfilter`, et redémarrage nécessaire après toute mise à jour de code. Le texte est rédigé, il reste à le publier | Exploitation |
| 26 ter | Tutoriel metrodyn.fr : copie vers un environnement de test | Rédiger puis publier un encadré sur la duplication d'une base de production : cocher « Neutraliser », couper les tâches planifiées et les envois d'e-mails, rediriger les connexions externes vers les environnements de test avant de démarrer l'instance | Dev pour la rédaction, exploitation pour la publication |
| 27 | Désinscriptions d'août 2026 sur le `.fr` | Une soixantaine de clients désinscrits par cron du 11 au 16 août, sans modification en masse dans la boutique. Cause inconnue | Dev |

## 5. Nouvelles synchronisations

Aucune n'est commencée, sauf mention. La synchronisation actuelle tourne sans incident depuis le 8 octobre.

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

## 6. Écartés

| # | Sujet | Décision |
|---|---|---|
| 5 | Clé d'API du `.hair` apparue en clair dans un ancien journal | Jugé sans gravité, conservée (29 octobre) |
| 6 | Secret webhook resté dans l'historique du module PrestaShop | Vérifié le 29 octobre : le secret en service n'apparaît dans l'historique d'aucun des deux dépôts. Rien à changer |

---

## Fait depuis le 4 octobre 2026

| Date | Version | Quoi |
|---|---|---|
| 5 octobre | 17.0.1.0.85 | Notifications par e-mail : alertes, résumé quotidien ou horaire, alerte sur une vague de désinscriptions |
| 8 octobre | 17.0.1.0.86 | Correctifs : premier résumé qui plantait, nouvelles inscriptions non datées donc non comptées |
| 8 octobre | 17.0.1.0.87 | Les résumés listent les adresses sous chaque chiffre et le texte des erreurs (option « Addresses in summaries ») |
| 29 octobre | — | Module PrestaShop 1.3.3 poussé sur GitHub ; fichiers d'adresses retirés du dépôt Odoo et de son historique (copie dans les archives locales) ; captcha du `.hair` réactivé |

---

## Contrôle périodique : vagues d'inscriptions ou de désinscriptions

À lancer sur le serveur dédié, en lecture seule. Aucune adresse n'est affichée.

Désinscriptions et inscriptions groupées à la même minute, depuis le 5 octobre 2026 :

```bash
docker exec odoo17-db psql -U odoo17 -d mcdavidian -c "select l.name, to_char(s.opt_out_datetime,'YYYY-MM-DD HH24:MI') as minute_utc, count(*) as desinscriptions from mailing_subscription s join mailing_list l on l.id = s.list_id where s.opt_out and s.opt_out_datetime >= '2026-10-05' and l.name ilike '%Prestashop - mcdavidian.%' group by 1, 2 having count(*) >= 5 order by 3 desc limit 20;" -c "select l.name, to_char(s.create_date,'YYYY-MM-DD HH24:MI') as minute_utc, count(*) as inscriptions from mailing_subscription s join mailing_list l on l.id = s.list_id where s.create_date >= '2026-10-05' and l.name ilike '%Prestashop - mcdavidian.%' group by 1, 2 having count(*) >= 5 order by 3 desc limit 20;"
```

Abonnés actifs par liste, et erreurs du connecteur sur 15 jours :

```bash
docker exec odoo17-db psql -U odoo17 -d mcdavidian -c "select l.name, count(*) filter (where not coalesce(s.opt_out,false)) as abonnes_actifs, count(*) filter (where s.opt_out) as desinscrits from mailing_subscription s join mailing_list l on l.id = s.list_id where l.name ilike '%Prestashop - mcdavidian.%' group by 1 order by 1;" -c "select b.name as boutique, left(l.message, 90) as message, count(*) as nb, to_char(max(l.create_date),'MM-DD HH24:MI') as derniere from prestashop_sync_log l join prestashop_backend b on b.id = l.backend_id where l.status = 'error' and l.create_date > now() - interval '15 days' group by 1, 2 order by 3 desc limit 20;"
```

| Ce qu'on voit | Ce que ça veut dire |
|---|---|
| 5 désinscriptions ou plus à la même minute | Suspect : de vraies personnes ne se désinscrivent pas ensemble. Regarder le journal du connecteur à cette minute ; une ligne « Opted out N email-only subscribers deactivated in PrestaShop » signifie un nettoyage fait dans la boutique. Exception : une campagne envoyée peu avant, mais ses désinscriptions s'étalent sur plusieurs minutes |
| 5 inscriptions ou plus à la même minute | Import de clients (normal après un rattrapage) ou vague de robots sur le formulaire newsletter |
| Erreur « push aborted … revocations exceed the limit » | Le plafond de sécurité a bloqué un envoi anormal vers une boutique : ne pas forcer avec le bouton, chercher d'abord la cause avec « Preview » |
| Chute brutale des abonnés actifs | Signe d'un incident. Repères au 29 octobre 2026, abonnés actifs des listes newsletter dans Odoo (clients et inscrits par e-mail seul) : `.com` 287, `.fr` 149, `.hair` 167 |
| Un jour sans résumé dans la boîte de réception | La tâche « PrestaShop: Notifications » ne tourne plus, ou le conteneur est arrêté |

---

## Limites connues et voulues

| Limite | Détail |
|---|---|
| Odoo → PrestaShop en révocation seule | Odoo ne remet jamais `newsletter=1` ni `optin=1` dans la boutique |
| Push sur signal explicite uniquement | Désinscription d'une liste ou liste noire. Un contact simplement absent d'une liste Odoo n'est jamais désinscrit dans PrestaShop |
| `respect_odoo_opt_out` | Un contact désinscrit dans Odoo n'est pas réinscrit par la synchro planifiée, même si PrestaShop l'indique abonné. Seul un webhook (nouvelle action du client) lève la désinscription |
| Inscrits par e-mail seul supprimés de PrestaShop | Ils restent dans Odoo. Seules les lignes désactivées (`active=0`) sont désinscrites, parce que c'est un signal explicite. Une désinscription par le formulaire de la boutique est transmise par le module PrestaShop (1.3.2 et suivants) |
| Résumés : réinscriptions | Un contact désinscrit qui se réinscrit repasse bien inscrit, mais n'est pas compté comme nouvelle inscription |
| Résumés : inscriptions avant le 8 octobre 2026 | Créées sans date, elles ne figurent dans aucun résumé (elles sont bien dans les listes) |
| Alerte de vague de désinscriptions | Elle part aussi lors d'un nettoyage volontaire de robots : c'est attendu |
| Captcha du formulaire newsletter | Non couvert par les tests : seuls les résumés (absence de robots) permettent de vérifier qu'il tient |
| nginx du `.fr` et du `.hair` | Rejette l'agent `python-requests` (403). Le connecteur envoie `OdooPrestashopConnector/1.0`. En cas de nouveau 403 sur l'API, regarder d'abord les règles anti-robots |
| Conteneurs Odoo | Le code n'est chargé qu'au démarrage, et chaque conteneur doit avoir `db_name` dans sa configuration, sinon il exécute les tâches planifiées de toutes les bases du serveur |
