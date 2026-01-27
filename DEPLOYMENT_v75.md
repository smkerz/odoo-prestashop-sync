# Déploiement version 17.0.1.0.75

Date: 2026-01-25

## Nouvelles fonctionnalités

### Synchronisation temps réel des adresses via webhook

**Avant (v17.0.1.0.74):**
- Les adresses n'étaient synchronisées que manuellement via le bouton "Sync Addresses"
- Créer/modifier/supprimer une adresse dans PrestaShop → aucune action dans Odoo
- Il fallait lancer la synchronisation manuelle régulièrement

**Après (v17.0.1.0.75):**
```
PrestaShop: Créer/Modifier/Supprimer une adresse
    ↓ Webhook temps réel
Odoo: Adresse automatiquement créée/mise à jour/supprimée
✅ Synchronisation bidirectionnelle complète en temps réel
```

**Fonctionnalités:**
1. **Création automatique** - Nouvelle adresse dans PrestaShop → Création automatique dans Odoo (child partner)
2. **Mise à jour automatique** - Modification d'adresse → Mise à jour dans Odoo (phone, mobile, street, city, etc.)
3. **Suppression automatique** - Suppression d'adresse → Suppression dans Odoo via mapping

## Fichiers modifiés

### Module Odoo
1. `__manifest__.py` - Version bump 17.0.1.0.74 → 17.0.1.0.75
2. `controllers/prestashop_webhook.py` - Nouveau endpoint `/prestashop/webhook/addresses`
3. `models/prestashop_backend.py` - Nouvelle méthode `_apply_webhook_address()`

### Module PrestaShop (NOUVEAU - v1.1.0)
1. `prestashopodoo.php`:
   - Enregistrement de 3 nouveaux hooks:
     - `actionObjectAddressAddAfter` (création)
     - `actionObjectAddressUpdateAfter` (modification)
     - `actionObjectAddressDeleteAfter` (suppression)
   - Nouvelle méthode `sendAddressWebhook()` pour envoyer les webhooks

2. **IMPORTANT:** Le module PrestaShop DOIT être mis à jour (nouvelle version avec hooks adresses)
   - Nouveau MD5: `54b1c52dc399590752c042fdd0a76cdb`
   - Ancien MD5: `8c2a236aa5e63b17a8df8249992a12f0`

## Instructions de déploiement

### Étape 1: Mise à jour du module Odoo

#### Option A: Via l'interface Odoo (recommandé)
1. Connectez-vous à Odoo en tant qu'administrateur
2. Allez dans **Apps** (Applications)
3. Cherchez "PrestaShop Connector"
4. Cliquez sur les 3 points (...) puis **"Upgrade"**
5. Odoo détectera les changements et mettra à jour

#### Option B: Via ligne de commande
```bash
# Arrêter Odoo
sudo systemctl stop odoo

# Copier les fichiers mis à jour
cd /opt/odoo/addons/prestashop_connector_basic/
# (ou le chemin vers vos addons custom)

# Redémarrer Odoo avec mise à jour du module
sudo -u odoo /opt/odoo/odoo-bin -c /etc/odoo/odoo.conf -u prestashop_connector_basic -d votre_database --stop-after-init

# Redémarrer Odoo normalement
sudo systemctl start odoo
```

### Étape 2: Mise à jour du module PrestaShop (OBLIGATOIRE)

⚠️ **IMPORTANT:** Cette fois, le module PrestaShop DOIT être mis à jour car il contient les nouveaux hooks pour les adresses.

#### Vérification de la version actuelle:
```bash
md5sum prestashopodoo.zip
```

Si le MD5 n'est PAS `54b1c52dc399590752c042fdd0a76cdb`, alors vous DEVEZ mettre à jour:

#### Mise à jour du module PrestaShop:

1. **Désinstaller l'ancien module:**
   - Allez dans **Modules → Module Manager**
   - Cherchez "PrestaShop Odoo Webhook"
   - Cliquez sur **Désinstaller**
   - ⚠️ La désinstallation supprimera la configuration (URL, secret) - notez-les avant!

2. **Installer le nouveau module:**
   - Téléchargez le nouveau `prestashopodoo.zip` depuis `D:\GitHub\prestashopodoo.zip`
   - Allez dans **Modules → Module Manager**
   - Cliquez sur **Téléverser un module**
   - Sélectionnez le nouveau ZIP
   - Cliquez sur **Installer**

3. **Configurer le module:**
   - Webhook URL: `https://votre-odoo.com/prestashop/webhook/consents` (copier depuis Odoo)
   - Shared Secret: (copier depuis Odoo backend)
   - Odoo Backend ID: `1` (ou l'ID de votre backend)
   - Timeout: `10` secondes
   - Enable Webhook: ✅ Activé
   - Verify SSL: ✅ Activé (ou désactivé si dev local)

### Étape 3: Test de la synchronisation des adresses

#### Test 1: Création d'adresse

1. Dans Odoo, importez d'abord un customer:
   - Allez dans **PrestaShop → Backends**
   - Cliquez sur votre backend
   - Cliquez sur **Import Customers** (ou assurez-vous qu'un customer existe déjà)

2. Dans PrestaShop, allez dans **Customers → Addresses**

3. Cliquez sur **Add new address**

4. Remplissez les champs:
   - **Customer:** Sélectionnez un customer existant (celui importé dans Odoo)
   - **Alias:** Test Address
   - **First name:** Jean
   - **Last name:** Test
   - **Address:** 123 Rue de Test
   - **Postal code:** 75001
   - **City:** Paris
   - **Country:** France
   - **Phone:** +33 1 23 45 67 89

5. Sauvegardez

**Vérification dans Odoo:**
1. Allez dans **Contacts**
2. Cherchez le customer (par email)
3. Cliquez sur le customer
4. Vérifiez l'onglet **Contacts & Addresses**
5. L'adresse devrait être **créée automatiquement** avec:
   - Name: "Jean Test - Test Address"
   - Phone: +33 1 23 45 67 89
   - Street: 123 Rue de Test
   - City: Paris

#### Test 2: Modification d'adresse

1. Dans PrestaShop, retournez dans **Customers → Addresses**

2. Cliquez sur l'adresse créée précédemment

3. Modifiez le téléphone: `+33 9 87 65 43 21`

4. Sauvegardez

**Vérification dans Odoo:**
1. Retournez dans le contact dans Odoo
2. Rafraîchissez la page (F5)
3. L'adresse devrait être **mise à jour automatiquement** avec le nouveau téléphone

#### Test 3: Suppression d'adresse

1. Dans PrestaShop, supprimez l'adresse de test

2. Confirmez la suppression

**Vérification dans Odoo:**
1. Retournez dans le contact dans Odoo
2. Rafraîchissez la page (F5)
3. L'adresse devrait être **supprimée automatiquement**

### Étape 4: Vérifier les logs

Dans Odoo:
1. Allez dans **PrestaShop → Logs**
2. Filtrez par opération: `sync_addresses`
3. Vous devriez voir:
   - `ok` - "Webhook address created: address_id=123"
   - `ok` - "Webhook address updated: address_id=123"
   - `ok` - "Webhook address deleted: address_id=123"

Si vous voyez:
- `warning` - "Customer mapping not found" → Le customer n'est pas importé dans Odoo
- `warning` - "Address not found in PrestaShop" → L'API PrestaShop n'a pas retourné l'adresse
- `error` - Vérifiez les détails pour diagnostiquer

### Étape 5: Test de régression

Vérifiez que les fonctionnalités existantes fonctionnent toujours:

1. **Webhook consents** - Modifier newsletter/optin d'un customer → Mise à jour des listes
2. **Import Customers** - Bouton "Import Customers" → Import des nouveaux customers
3. **Sync Addresses (manuel)** - Bouton "Sync Addresses" → Synchronisation manuelle (toujours disponible)
4. **Sync Consents** - Bouton "Presta → Odoo" → Synchronisation des consentements
5. **Push Opt-outs** - Bouton "Odoo → Presta" → Poussée des révocations

## Données synchronisées

### Pour chaque adresse (webhook temps réel):

**De PrestaShop vers Odoo:**
- Alias (alias → name)
- Prénom + Nom (firstname + lastname → name)
- Adresse (address1 + address2 → street + street2)
- Code postal (postcode → zip)
- Ville (city → city)
- Pays (id_country → country_id via ISO code)
- État/Province (id_state → state_id via ISO code)
- Téléphone (phone → phone)
- Téléphone mobile (phone_mobile → mobile)

**Type de contact:** `other` (child partner du customer principal)

## Comportement attendu

### Scénario complet: Nouveau customer avec adresse

```
1. PrestaShop: Nouveau customer inscrit newsletter
    ↓ Webhook consents
2. Odoo: Customer créé automatiquement (v73)

3. PrestaShop: Admin ajoute une adresse au customer
    ↓ Webhook addresses (NOUVEAU v75)
4. Odoo: Adresse créée automatiquement en child partner

5. PrestaShop: Customer modifie son téléphone
    ↓ Webhook addresses
6. Odoo: Adresse mise à jour automatiquement

✅ Synchronisation bidirectionnelle complète en temps réel
```

## Script de test

Un script de test est disponible: `test_webhook_addresses.py`

```bash
# Test création
python test_webhook_addresses.py create

# Test mise à jour
python test_webhook_addresses.py update

# Test suppression
python test_webhook_addresses.py delete
```

**Avant de l'utiliser**, configurez:
- `ODOO_URL`
- `WEBHOOK_SECRET`
- `BACKEND_ID`
- `customer_id` (un customer existant dans Odoo)
- `address_id` (une adresse existante dans PrestaShop)

## Rollback

Si problème, revenir à v17.0.1.0.74:

```bash
cd /opt/odoo/addons/prestashop_connector_basic/
git checkout HEAD~1
sudo systemctl restart odoo
# Puis mettre à jour le module dans Apps
```

**Note:** Les webhooks d'adresses ne fonctionneront plus, mais les fonctionnalités existantes (customers, consents) continueront de fonctionner.

## Support

En cas de problème:
1. Vérifier les logs Odoo: **PrestaShop → Logs** (opération: `sync_addresses`)
2. Vérifier les logs système: `sudo journalctl -u odoo -f`
3. Vérifier les logs PrestaShop: `var/logs/` dans PrestaShop
4. Vérifier que le module PrestaShop est bien la version avec MD5 `54b1c52dc399590752c042fdd0a76cdb`

## Notes techniques

### Performance
- Chaque webhook d'adresse effectue 1 appel API PrestaShop (`GET /addresses/{id}`)
- Timeout par défaut: 10 secondes (configurable)
- Si PrestaShop est lent, augmenter le timeout dans le module PrestaShop

### Sécurité
- Le webhook vérifie toujours la signature HMAC-SHA256
- Seuls les webhooks avec signature valide peuvent créer/modifier/supprimer des adresses
- Les webhooks de test (address_id="0") sont ignorés

### Hooks PrestaShop utilisés
1. `actionObjectAddressAddAfter` - Déclenché après création d'une adresse
2. `actionObjectAddressUpdateAfter` - Déclenché après modification d'une adresse
3. `actionObjectAddressDeleteAfter` - Déclenché après suppression d'une adresse

### Endpoint webhook
- URL: `https://votre-odoo.com/prestashop/webhook/addresses`
- Méthode: POST
- Content-Type: application/json
- Header: `X-Prestashop-Signature` (HMAC-SHA256)

### Payload exemple
```json
{
  "backend_id": "1",
  "customer_id": "123",
  "address_id": "456",
  "action": "create|update|delete",
  "updated_at": "2026-01-25T12:34:56Z",
  "shop_id": "1",
  "shop_url": "https://votre-prestashop.com"
}
```

## Limitations connues

1. Si l'API PrestaShop est down, le webhook log une erreur mais ne bloque pas
2. La suppression échoue silencieusement si l'adresse n'existe pas dans Odoo
3. Les adresses créées avant cette version doivent être synchronisées manuellement via "Sync Addresses" une fois
4. La synchronisation manuelle "Sync Addresses" reste disponible pour rattraper les adresses manquées
