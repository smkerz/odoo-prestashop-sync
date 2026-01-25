# Module PrestaShop - Setup Complet pour Webhook Bidirectionnel

## Vue d'ensemble

Pour permettre un test webhook complet, le module PrestaShop doit exposer deux nouveaux endpoints :
1. **Webhook Config** : Permet à Odoo de lire la configuration webhook
2. **Webhook Test** : Permet à Odoo de déclencher un webhook de test

---

## 1️⃣ Structure du module PrestaShop

Créez les fichiers suivants dans votre module PrestaShop :

```
yourmodule/
├── yourmodule.php (fichier principal)
├── config.xml (configuration)
├── controllers/
│   └── front/
│       ├── WebhookConfig.php  ← NOUVEAU
│       └── WebhookTest.php     ← NOUVEAU
```

---

## 2️⃣ Code : WebhookConfig.php

**Fichier** : `controllers/front/WebhookConfig.php`

```php
<?php
/**
 * Endpoint pour lire la configuration webhook du module PrestaShop.
 *
 * URL : /module/yourmodule/webhookconfig?ws_key=VOTRE_CLE_WEBSERVICE
 *
 * Retourne :
 * {
 *   "webhook_url": "https://odoo.example.com/prestashop/webhook/consents",
 *   "webhook_secret": "q8Zp9mYv3Lk7T2sX1rQ5wN6bC0uA4fGh",
 *   "backend_id": "1"
 * }
 */

if (!defined('_PS_VERSION_')) {
    exit;
}

class YourModuleWebhookConfigModuleFrontController extends ModuleFrontController
{
    public $ssl = true;

    public function initContent()
    {
        parent::initContent();

        // Vérifier l'authentification via webservice key
        $wsKey = Tools::getValue('ws_key');
        if (!$this->_authenticate($wsKey)) {
            http_response_code(401);
            header('Content-Type: application/json');
            die(json_encode(['error' => 'Unauthorized - Invalid webservice key']));
        }

        // Lire la configuration du module
        $config = [
            'webhook_url' => Configuration::get('YOURMODULE_WEBHOOK_URL'),
            'webhook_secret' => Configuration::get('YOURMODULE_WEBHOOK_SECRET'),
            'backend_id' => Configuration::get('YOURMODULE_BACKEND_ID'),
        ];

        header('Content-Type: application/json');
        die(json_encode($config));
    }

    /**
     * Vérifier que la clé webservice est valide.
     */
    private function _authenticate($wsKey)
    {
        if (empty($wsKey)) {
            return false;
        }

        $sql = 'SELECT id_webservice_account FROM ' . _DB_PREFIX_ . 'webservice_account
                WHERE `key` = "' . pSQL($wsKey) . '" AND active = 1';

        return (bool)Db::getInstance()->getValue($sql);
    }
}
```

---

## 3️⃣ Code : WebhookTest.php

**Fichier** : `controllers/front/WebhookTest.php`

```php
<?php
/**
 * Endpoint pour déclencher un webhook de test vers Odoo.
 *
 * URL : /module/yourmodule/webhooktest?ws_key=VOTRE_CLE_WEBSERVICE
 *
 * Retourne :
 * {
 *   "status": "success",
 *   "http_code": 200,
 *   "response": "{\"status\":\"ok\"}",
 *   "error": null
 * }
 */

if (!defined('_PS_VERSION_')) {
    exit;
}

class YourModuleWebhookTestModuleFrontController extends ModuleFrontController
{
    public $ssl = true;

    public function initContent()
    {
        parent::initContent();

        // Vérifier l'authentification via webservice key
        $wsKey = Tools::getValue('ws_key');
        if (!$this->_authenticate($wsKey)) {
            http_response_code(401);
            header('Content-Type: application/json');
            die(json_encode(['error' => 'Unauthorized - Invalid webservice key']));
        }

        // Récupérer la configuration
        $webhookUrl = Configuration::get('YOURMODULE_WEBHOOK_URL');
        $webhookSecret = Configuration::get('YOURMODULE_WEBHOOK_SECRET');
        $backendId = Configuration::get('YOURMODULE_BACKEND_ID');

        if (!$webhookUrl || !$webhookSecret) {
            http_response_code(400);
            header('Content-Type: application/json');
            die(json_encode([
                'error' => 'Webhook not configured in PrestaShop module',
                'webhook_url' => !empty($webhookUrl),
                'webhook_secret' => !empty($webhookSecret),
            ]));
        }

        // Créer un payload de test
        $payload = [
            'backend_id' => $backendId ?: '0',
            'customer_id' => '0',
            'email' => 'test-from-prestashop@example.invalid',
            'newsletter' => 1,
            'optin' => 0,
            'updated_at' => date('Y-m-d H:i:s'),
            'shop_id' => (string)Context::getContext()->shop->id,
            'shop_url' => Tools::getShopDomain(true),
        ];

        $body = json_encode($payload);
        $signature = hash_hmac('sha256', $body, $webhookSecret);

        // Envoyer le webhook vers Odoo
        $ch = curl_init($webhookUrl);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 30);
        curl_setopt($ch, CURLOPT_HTTPHEADER, [
            'Content-Type: application/json',
            'X-Prestashop-Signature: ' . $signature,
            'X-Prestashop-Test: 1',
        ]);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        // Retourner le résultat
        header('Content-Type: application/json');
        die(json_encode([
            'status' => ($httpCode >= 200 && $httpCode < 300) ? 'success' : 'error',
            'http_code' => $httpCode,
            'response' => $response,
            'error' => $error ?: null,
        ]));
    }

    /**
     * Vérifier que la clé webservice est valide.
     */
    private function _authenticate($wsKey)
    {
        if (empty($wsKey)) {
            return false;
        }

        $sql = 'SELECT id_webservice_account FROM ' . _DB_PREFIX_ . 'webservice_account
                WHERE `key` = "' . pSQL($wsKey) . '" AND active = 1';

        return (bool)Db::getInstance()->getValue($sql);
    }
}
```

---

## 4️⃣ Configuration dans le module principal

Ajoutez ces champs de configuration dans votre interface d'administration (`yourmodule.php`) :

```php
// Dans la méthode getContent() ou renderForm()

$fields_form[0]['form'] = [
    'legend' => [
        'title' => $this->l('Webhook Configuration (Odoo)'),
    ],
    'input' => [
        [
            'type' => 'text',
            'label' => $this->l('Webhook URL'),
            'name' => 'YOURMODULE_WEBHOOK_URL',
            'desc' => $this->l('Example: https://odoo.example.com/prestashop/webhook/consents'),
            'size' => 100,
            'required' => true,
        ],
        [
            'type' => 'text',
            'label' => $this->l('Webhook Secret'),
            'name' => 'YOURMODULE_WEBHOOK_SECRET',
            'desc' => $this->l('Secret key for HMAC signature (must match Odoo)'),
            'size' => 64,
            'required' => true,
        ],
        [
            'type' => 'text',
            'label' => $this->l('Odoo Backend ID'),
            'name' => 'YOURMODULE_BACKEND_ID',
            'desc' => $this->l('The ID of the backend in Odoo'),
            'size' => 10,
        ],
    ],
    'submit' => [
        'title' => $this->l('Save'),
    ],
];
```

---

## 5️⃣ Installation et test

### Étape 1 : Installer le module PrestaShop
1. Uploadez les fichiers dans `/modules/yourmodule/`
2. Installez le module via Back Office > Modules
3. Configurez les 3 paramètres :
   - **Webhook URL** : `https://votre-odoo.com/prestashop/webhook/consents`
   - **Webhook Secret** : La même valeur que dans Odoo
   - **Backend ID** : L'ID du backend dans Odoo (généralement 1)

### Étape 2 : Tester manuellement les endpoints

#### Test 1 : Lire la config
```bash
curl "https://votre-prestashop.com/module/yourmodule/webhookconfig?ws_key=VOTRE_CLE_WEBSERVICE"
```

**Résultat attendu** :
```json
{
  "webhook_url": "https://votre-odoo.com/prestashop/webhook/consents",
  "webhook_secret": "q8Zp9mYv3Lk7T2sX1rQ5wN6bC0uA4fGh",
  "backend_id": "1"
}
```

#### Test 2 : Déclencher un webhook de test
```bash
curl -X POST "https://votre-prestashop.com/module/yourmodule/webhooktest?ws_key=VOTRE_CLE_WEBSERVICE"
```

**Résultat attendu** :
```json
{
  "status": "success",
  "http_code": 200,
  "response": "{\"status\":\"ok\"}",
  "error": null
}
```

### Étape 3 : Tester depuis Odoo
1. Dans Odoo, allez dans le backend PrestaShop
2. Cliquez sur le bouton **"Test Webhook"**
3. Vous devriez voir :

```
✅ Complete webhook test successful!

Validated:
  • PrestaShop API connection
  • Webhook URL matches: https://votre-odoo.com/prestashop/webhook/consents
  • Webhook secret matches
  • PrestaShop → Odoo webhook delivery
  • Odoo webhook signature validation
```

---

## 6️⃣ Dépannage

### Erreur : "Could not read PrestaShop webhook configuration"
- Vérifiez que les fichiers `WebhookConfig.php` et `WebhookTest.php` sont bien uploadés
- Vérifiez que le module est installé et activé
- Testez manuellement l'URL : `/module/yourmodule/webhookconfig?ws_key=...`

### Erreur : "Webhook URL mismatch"
- Copiez l'URL exacte depuis Odoo (champ `webhook_url_auto`)
- Collez-la dans la configuration PrestaShop
- N'ajoutez PAS de slash `/` à la fin

### Erreur : "Webhook secret mismatch"
- Copiez le secret exactement depuis Odoo
- Collez-le dans la configuration PrestaShop
- Pas d'espaces avant/après

### Erreur : "PrestaShop → Odoo webhook test failed"
- Vérifiez que Odoo est accessible depuis PrestaShop
- Vérifiez les logs Nginx/Apache sur le serveur Odoo
- Testez avec `curl` depuis le serveur PrestaShop vers l'URL Odoo

---

## 7️⃣ URLs importantes

Remplacez `yourmodule` par le nom réel de votre module PrestaShop.

- **Config endpoint** : `/module/yourmodule/webhookconfig?ws_key=XXX`
- **Test endpoint** : `/module/yourmodule/webhooktest?ws_key=XXX`
- **Odoo webhook** : `/prestashop/webhook/consents`

---

## 8️⃣ Sécurité

✅ **Bonnes pratiques** :
- Les endpoints utilisent la clé webservice PrestaShop (pas d'endpoint public)
- Le secret webhook est stocké en base (jamais exposé dans les logs)
- La signature HMAC-SHA256 valide chaque webhook
- Le payload de test utilise un email invalide (`@example.invalid`)

❌ **À éviter** :
- Ne jamais exposer le `webhook_secret` dans les logs
- Ne jamais désactiver la vérification de signature en production
- Ne pas utiliser HTTP (toujours HTTPS)

---

## Support

Pour toute question, vérifiez d'abord :
1. Les logs PrestaShop : `/var/log/apache2/error.log` ou `/var/log/php-fpm/error.log`
2. Les logs Odoo : menu Odoo > PrestaShop > Logs
3. Les tests manuels avec `curl` (voir section 5)

Version du document : **17.0.1.0.71**
