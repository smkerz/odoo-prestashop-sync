# Plan de test — Connecteur PrestaShop ↔ Odoo

## Ordre d'exécution

```
Phase 0 (config)
  └→ Phase 1 (import clients)              ← OBLIGATOIRE en premier
       ├→ Phase 2 (sync adresses)          ← après les clients
       │    └→ Phase 3 (webhooks adresses) ← après phase 2
       └→ Phase 4 (consents PS → Odoo)     ← après les clients
            ├→ Phase 5 (consents Odoo → PS) ← après phase 4
            ├→ Phase 6 (unsubscribe email)  ← après phase 4
            └→ Phase 7 (webhooks consents)  ← après phase 4
  └→ Phase 8 (robustesse)                  ← à la fin
```

---

## Phase 0 — Prérequis & Configuration initiale

| #   | Où | Action |
|-----|----|--------|
| 0.1 | PrestaShop > Paramètres avancés > Webservice | Activer le Webservice, créer une clé API avec **GET** sur `customers`, `addresses`, `countries`, `states`, `languages` + **PUT** sur `customers` |
| 0.2 | Odoo > Paramètres système | Vérifier que `web.base.url` pointe vers ton Odoo (ex : `https://odoo.mondomaine.com`) |
| 0.3 | Odoo > Apps | Mettre à jour la liste des apps, chercher **"PrestaShop"**, installer |
| 0.4 | Odoo > PrestaShop > Créer un Backend | Remplir : **Name**, **Base URL** du PS, **API Key**, **Webhook Secret** (ex : `test123secret`) |
| 0.5 | Odoo > Backend PS | Cliquer **Test** → doit afficher **"Connexion réussie"** |
| 0.6 | Odoo > Backend PS > onglet Customers | Vérifier que `customer_tag_id` se crée auto. Si `newsletter_tag_id` et `partner_offers_tag_id` sont vides, les créer manuellement. **Cocher `include_guest_customers`** si tu veux aussi importer les comptes invités |

---

## Phase 1 — Import Clients

| #   | Ce que tu fais | Où | Ce que tu vérifies |
|-----|----------------|----|--------------------|
| 1.1 | Vérifie que **Include Guest Customers** est coché (onglet Customers du Backend), puis clic **Import** | Odoo Backend | Notification de succès. Logs : opération `import_customers`, statut `ok`. Les comptes invités PS sont aussi importés |
| 1.2 | Va dans Contacts, filtre par tag **"Client Prestashop"** | Odoo Contacts | Tous les clients PS (y compris invités) sont là avec nom, email, téléphone. L'import n'a **pas ajouté** de rue/ville/zip — si une adresse existait déjà sur le contact, elle est inchangée |
| 1.3 | Ouvre un client, vérifie les champs | Odoo Contact | Nom = nom PS, Email = email PS. Pas de rue/ville/zip ajouté par l'import |
| 1.4 | Relance **Import** | Odoo Backend | Aucun nouveau client importé (incrémental). Log dit `0 new` ou similaire |
| 1.5 | Crée un nouveau client dans PS (back-office PS > Clients > Ajouter) | PrestaShop | — |
| 1.6 | Relance **Import** dans Odoo | Odoo Backend | Seul le nouveau client apparaît. Les anciens ne sont pas dupliqués |
| 1.7 | Décoche **Include Guest Customers**, relance **Import** | Odoo Backend | Les comptes invités (`is_guest=1`) sont ignorés (skipped). Seuls les vrais comptes sont importés |
| 1.8 | Recoche **Include Guest Customers** pour la suite des tests | Odoo Backend | — |

---

## Phase 2 — Sync Adresses

| #   | Ce que tu fais | Où | Ce que tu vérifies |
|-----|----------------|----|--------------------|
| 2.1 | Clic **Adresses** (section Customers) | Odoo Backend | Log `sync_addresses` statut `ok` |
| 2.2 | Ouvre un client qui a des adresses dans PS | Odoo Contact | Onglet "Contacts & Adresses" : sous-contacts type **Livraison** avec rue, ville, zip, pays |
| 2.3 | Vérifie le pays/état | Odoo sous-contact | Pays et état correctement mappés (ex : France, Île-de-France) |
| 2.4 | Relance **Adresses** | Odoo Backend | Aucun doublon créé (déduplication par signature) |
| 2.5 | Dans PS, ajoute une adresse à un client existant | PrestaShop | — |
| 2.6 | Relance **Adresses** dans Odoo | Odoo Backend | Nouvelle adresse apparaît comme sous-contact. Les anciennes ne sont pas dupliquées |

---

## Phase 3 — Webhooks Adresses (temps réel)

> Sans le module PHP côté PS, simule avec `curl`.
> Adapte `backend_id`, `address_id`, `customer_id`, le secret et l'URL Odoo.

**Exemple de commande :**

```bash
# Webhook CREATE
BODY='{"backend_id":1,"action":"create","address_id":99,"customer_id":3,"shop_url":"https://ta-boutique.com"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "test123secret" | awk '{print $2}')
curl -X POST https://ton-odoo.com/prestashop/webhook/addresses \
  -H "Content-Type: application/json" \
  -H "X-Prestashop-Signature: $SIG" \
  -d "$BODY"
```

| #   | Ce que tu fais | Ce que tu vérifies |
|-----|----------------|--------------------|
| 3.1 | Envoie webhook `action=create` avec un `address_id` existant dans PS | Réponse `{"status": "ok"}`. Sous-contact créé dans Odoo |
| 3.2 | Modifie l'adresse dans PS, envoie webhook `action=update` | Sous-contact mis à jour (nouvelle rue, etc.) |
| 3.3 | Envoie webhook `action=delete` | Sous-contact archivé/supprimé dans Odoo |
| 3.4 | Envoie webhook avec **mauvaise signature** | Réponse `401`, log warning `"invalid signature"` |
| 3.5 | Envoie webhook avec `backend_id` inexistant et `shop_url` inconnu | Réponse `400` `"backend not found"` |
| 3.6 | `GET /prestashop/webhook/ping` | Réponse `{"status": "ok"}` |

---

## Phase 4 — Consentements PrestaShop → Odoo

| #    | Ce que tu fais | Où | Ce que tu vérifies |
|------|----------------|----|--------------------|
| 4.1  | Note quels clients dans PS ont `newsletter=1` et `optin=1` | PrestaShop > Clients | — |
| 4.2  | Clic **Preview** (section Consents) | Odoo Backend | Log `preview_consents` montre les changements prévus, **aucune écriture** |
| 4.3  | Clic **Presta → Odoo** | Odoo Backend | Log `sync_email_marketing` statut `ok` |
| 4.4  | Va dans Email Marketing > Mailing Lists | Odoo | 2 listes créées auto : **"Newsletter (hostname)"** et **"Partner Offers (hostname)"** |
| 4.5  | Ouvre la liste Newsletter | Odoo Mailing List | Les clients PS avec `newsletter=1` sont inscrits |
| 4.6  | Ouvre la liste Partner Offers | Odoo Mailing List | Les clients PS avec `optin=1` sont inscrits |
| 4.7  | Ouvre un client inscrit, vérifie ses tags | Odoo Contact | Tags newsletter et/ou offres partenaires présents |
| 4.8  | Dans PS, décoche newsletter pour un client | PrestaShop | — |
| 4.9  | Relance **Presta → Odoo** | Odoo Backend | Client désinscrit de la liste Newsletter + tag retiré |
| 4.10 | Dans PS, recoche newsletter pour ce même client | PrestaShop | — |
| 4.11 | Relance **Presta → Odoo** | Odoo Backend | Client réinscrit à la liste Newsletter + tag remis |

---

## Phase 5 — Consentements Odoo → PrestaShop (révocation)

| #   | Ce que tu fais | Où | Ce que tu vérifies |
|-----|----------------|----|--------------------|
| 5.1 | Prends un client inscrit newsletter dans PS (`newsletter=1`), déjà synced en phase 4 | — | — |
| 5.2 | Dans Odoo, ouvre la mailing list Newsletter, trouve ce contact, mets `opt_out = True` | Odoo Mailing List | Contact marqué **"opted out"** |
| 5.3 | Clic **Odoo → Presta** | Odoo Backend | Log `sync_consents_odoo_to_prestashop` statut `ok` |
| 5.4 | Va dans PS, ouvre ce client | PrestaShop | `newsletter = 0` (révoqué par Odoo) |
| 5.5 | Dans PS, remets `newsletter = 1` manuellement | PrestaShop | — |
| 5.6 | Relance **Odoo → Presta** | Odoo Backend | Rien ne change — Odoo ne repousse **PAS** `newsletter=1` (revocation-only) |
| 5.7 | Dans Odoo, ajoute l'email à la Blacklist (Email Marketing > Blacklist) | Odoo | Email blacklisté |
| 5.8 | Relance **Odoo → Presta** | Odoo Backend | Dans PS : `newsletter=0` **ET** `optin=0` (blacklist = révocation totale) |

---

## Phase 6 — Désabonnement via lien email (scénario réel)

| #   | Ce que tu fais | Où | Ce que tu vérifies |
|-----|----------------|----|--------------------|
| 6.1 | Crée un Mailing dans Odoo envoyé à la liste Newsletter | Odoo Email Marketing | — |
| 6.2 | Envoie le mailing (ou envoie un test à toi-même) | Odoo | — |
| 6.3 | Dans l'email reçu, clique **"Unsubscribe"** en bas | Email | Page de désinscription Odoo |
| 6.4 | Confirme la désinscription | Navigateur | — |
| 6.5 | Vérifie : mailing list > ce contact a `opt_out = True` | Odoo | Contact désinscrit de la liste |
| 6.6 | Clic **Odoo → Presta** | Odoo Backend | `newsletter=0` dans PrestaShop pour ce client |

---

## Phase 7 — Webhooks Consentements (temps réel)

**Exemple de commande :**

```bash
# Webhook CONSENT
BODY='{"backend_id":1,"customer_id":3,"newsletter":"1","optin":"0","shop_url":"https://ta-boutique.com"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "test123secret" | awk '{print $2}')
curl -X POST https://ton-odoo.com/prestashop/webhook/consents \
  -H "Content-Type: application/json" \
  -H "X-Prestashop-Signature: $SIG" \
  -d "$BODY"
```

| #   | Ce que tu fais | Ce que tu vérifies |
|-----|----------------|--------------------|
| 7.1 | Webhook avec `newsletter=1`, `optin=0` pour un client mappé | Tag newsletter ajouté, tag offres retiré, mailing lists mises à jour |
| 7.2 | Webhook avec `newsletter=0`, `optin=1` | Inverse |
| 7.3 | Webhook avec un `customer_id` inconnu d'Odoo | Client auto-créé + consentements appliqués. Log `webhook_create_customer` |
| 7.4 | Webhook avec `customer_id=0` (test) | Réponse OK, aucun traitement |
| 7.5 | Webhook avec mauvaise signature | `401`, log warning |

---

## Phase 8 — Robustesse & cas limites

| #   | Ce que tu fais | Ce que tu vérifies |
|-----|----------------|--------------------|
| 8.1 | Lance **Import** 2 fois en parallèle (2 onglets) | Le 2e est bloqué par le verrou PostgreSQL. Pas de doublon, pas de crash |
| 8.2 | Mets un `api_key` faux, clique **Test** | Message d'erreur clair |
| 8.3 | Mets une `base_url` incorrecte, clique **Test** | Message d'erreur clair (timeout ou connexion refusée) |
| 8.4 | Clic **Purge Logs** | Tous les logs supprimés |
| 8.5 | **Réimport ID** avec un ID PS valide | Client mis à jour/recréé |
| 8.6 | **Réimport ID** avec un ID inexistant | Message d'erreur propre |
| 8.7 | Toggle `respect_odoo_opt_out = OFF`, client blacklisté, relance **Presta → Odoo** avec `newsletter=1` dans PS | Le client **EST** réinscrit (opt-out ignoré). **Remettre ON après !** |
