# Déploiement version 17.0.1.0.73

Date: 2026-01-25

## Nouvelles fonctionnalités

### 1. Création automatique de customers via webhook
- Le webhook crée maintenant automatiquement les nouveaux customers dans Odoo
- Plus besoin d'import manuel pour les nouvelles inscriptions newsletter
- Synchronisation en temps réel complète

### 2. Onglet Orders caché
- L'onglet Orders est maintenant invisible (sera implémenté plus tard)

## Fichiers modifiés

1. `__manifest__.py` - Version bump 17.0.1.0.72 → 17.0.1.0.73
2. `models/prestashop_backend.py` - Nouvelle méthode `_fetch_and_create_customer_from_webhook()`
3. `views/prestashop_backend_views.xml` - Onglet Orders avec `invisible="1"`

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

### Étape 2: Vérifier le module PrestaShop

Le module PrestaShop n'a pas besoin d'être mis à jour si vous avez déjà installé la version avec le fix des valeurs par défaut (MD5: `8c2a236aa5e63b17a8df8249992a12f0`).

Vérification:
```bash
md5sum prestashopodoo.zip
# Doit afficher: 8c2a236aa5e63b17a8df8249992a12f0
```

Si différent, réinstallez le module PrestaShop:
1. Désinstaller l'ancien module "PrestaShop Odoo Webhook"
2. Téléverser et installer `D:\GitHub\prestashopodoo.zip`
3. Configurer:
   - Webhook URL: (copiée depuis Odoo)
   - Shared Secret: (copié depuis Odoo)
   - Odoo Backend ID: `1` (ou l'ID de votre backend Odoo)

### Étape 3: Test de la création automatique

#### Test 1: Nouveau client avec newsletter
1. Sur PrestaShop, allez dans le formulaire d'inscription newsletter (footer)
2. Entrez un email de test: `test-auto-create@example.com`
3. Cochez "J'accepte de recevoir la newsletter"
4. Soumettez le formulaire

**Vérification dans Odoo:**
1. Allez dans **Contacts**
2. Cherchez `test-auto-create@example.com`
3. Le contact devrait être **créé automatiquement** avec:
   - Tag "Client Prestashop"
   - Présent dans la liste "Newsletter"

#### Test 2: Nouveau client créé dans PrestaShop
1. Dans le back-office PrestaShop, créez un nouveau client
2. Email: `test-nouveau-client@example.com`
3. Cochez "Newsletter" et/ou "Offres partenaires"
4. Sauvegardez

5. Dans Odoo, allez dans le backend PrestaShop
6. Cliquez sur "Test Connection" puis "Webhook"
7. Le test devrait réussir (6 étapes validées)

8. Retournez à la page cliente dans PrestaShop
9. Modifiez n'importe quel champ (ex: prénom) et sauvegardez
   → Ceci déclenche le webhook

**Vérification dans Odoo:**
1. Cherchez `test-nouveau-client@example.com` dans Contacts
2. Le client devrait être **créé automatiquement**
3. Vérifiez les listes Email Marketing correspondantes

### Étape 4: Vérifier les logs

Dans Odoo:
1. Allez dans **PrestaShop → Logs**
2. Filtrez par opération: `webhook_create_customer`
3. Vous devriez voir:
   - `ok` - "Customer 123 created via webhook"
   - ou `ok` - "Customer 123 updated via webhook"

Si vous voyez:
- `warning` - "Customer 123 not found in PrestaShop" → L'API PrestaShop n'a pas retourné le customer
- `error` - Vérifiez les détails pour diagnostiquer

### Étape 5: Test de régression

Vérifiez que les fonctionnalités existantes fonctionnent toujours:

1. **Import manuel**: Bouton "Import Customers" → Devrait importer les customers non encore synchro
2. **Sync Consents**: Bouton "Presta → Odoo" → Devrait synchroniser les consentements
3. **Push Opt-outs**: Bouton "Odoo → Presta" → Devrait pousser les révocations
4. **Webhook existant**: Modifier un client existant → Devrait mettre à jour les listes

## Comportement attendu

### Avant (v17.0.1.0.72)
```
PrestaShop: Nouveau client inscrit newsletter
    ↓ Webhook
Odoo: Partner not found → SKIP
Admin: Doit lancer "Import Customers" manuellement
Odoo: Client créé + ajouté à Newsletter
```

### Après (v17.0.1.0.73)
```
PrestaShop: Nouveau client inscrit newsletter
    ↓ Webhook
Odoo: Partner not found
    ↓ GET /customers/123 (API PrestaShop)
Odoo: Crée automatiquement le partner + mapping
Odoo: Applique les consentements → ajout à Newsletter
✅ Synchronisation complète en temps réel
```

## Rollback

Si problème, revenir à v17.0.1.0.72:
```bash
cd /opt/odoo/addons/prestashop_connector_basic/
git checkout HEAD~1
sudo systemctl restart odoo
# Puis mettre à jour le module dans Apps
```

## Support

En cas de problème:
1. Vérifier les logs Odoo: **PrestaShop → Logs**
2. Vérifier les logs système: `sudo journalctl -u odoo -f`
3. Vérifier les logs PrestaShop: `var/logs/` dans PrestaShop

## Notes techniques

### Performance
- Chaque webhook de nouveau client effectue 1 appel API PrestaShop supplémentaire (`GET /customers/{id}`)
- Timeout par défaut: 10 secondes (configurable)
- Si PrestaShop est lent, augmenter le timeout dans le module PrestaShop

### Sécurité
- Le webhook vérifie toujours la signature HMAC-SHA256
- Seuls les webhooks avec signature valide peuvent créer des customers
- Les guests peuvent être exclus via `include_guest_customers=False`

### Limitations connues
- Si l'API PrestaShop est down, le webhook log une erreur mais ne bloque pas
- La création échoue silencieusement (log only) pour ne pas perturber PrestaShop
- Un cron manuel peut être utilisé pour rattraper les customers manqués
