<?php
/**
 * End-to-end test, PrestaShop side. TEST SHOPS ONLY (domain must start with "dev.").
 *
 * Creates customers, addresses and newsletter subscriptions through PrestaShop's
 * own classes, so the prestashopodoo hooks fire exactly as for a real visitor.
 * Works together with e2e_odoo.py (see README.md in this folder).
 *
 *   php e2e_shop.php <shop root> setup   <tag>   create the test data (webhooks go to Odoo)
 *   php e2e_shop.php <shop root> verify  <tag>   check what Odoo pushed back
 *   php e2e_shop.php <shop root> cleanup <tag>   delete the test data
 *
 * <tag> is any short word (letters/digits), the same for every step of a run.
 */
if (PHP_SAPI !== 'cli') {
    exit;
}
if ($argc < 4 || !in_array($argv[2], array('setup', 'verify', 'cleanup'), true) || !preg_match('/^[a-z0-9]{2,12}$/', $argv[3])) {
    fwrite(STDERR, "usage: php e2e_shop.php <shop root> setup|verify|cleanup <tag>\n");
    exit(2);
}
list(, $shopRoot, $phase, $tag) = $argv;

require rtrim($shopRoot, '/') . '/config/config.inc.php';

$domain = Tools::getShopDomain();
if (strpos($domain, 'dev.') !== 0) {
    fwrite(STDERR, "REFUSED: this script only runs on a test shop (domain starting with \"dev.\"), not on $domain\n");
    exit(2);
}
$module = Module::getInstanceByName('prestashopodoo');
if (!$module || !Module::isInstalled('prestashopodoo')) {
    fwrite(STDERR, "REFUSED: module prestashopodoo is not installed on $domain\n");
    exit(2);
}

$failures = 0;

function email($name)
{
    global $tag;
    return "e2e-$tag-$name@example.invalid";
}

function check($label, $ok, $detail = '')
{
    global $failures;
    if (!$ok) {
        $failures++;
    }
    echo ($ok ? 'PASS ' : 'FAIL ') . $label . ($ok || $detail === '' ? '' : "  ($detail)") . "\n";
}

/**
 * The module sends one consent webhook per HTTP request. This script plays many
 * "requests" in one process, so the guard is reset between actions.
 */
function newRequest()
{
    global $module;
    $flag = new ReflectionProperty($module, 'consentWebhookSent');
    $flag->setAccessible(true);
    $flag->setValue($module, false);
}

function createCustomer($name, $newsletter, $optin)
{
    newRequest();
    $c = new Customer();
    $c->firstname = 'Test';
    $c->lastname = 'Synchro';
    $c->email = email($name);
    $c->passwd = Tools::hash(uniqid('e2e', true));
    $c->newsletter = (int)$newsletter;
    $c->optin = (int)$optin;
    $c->id_default_group = (int)Configuration::get('PS_CUSTOMER_GROUP');
    $c->add();
    return $c;
}

function createAddress(Customer $c, $city)
{
    $a = new Address();
    $a->id_customer = (int)$c->id;
    $a->id_country = (int)Configuration::get('PS_COUNTRY_DEFAULT');
    $a->alias = 'Test';
    $a->firstname = 'Test';
    $a->lastname = 'Synchro';
    $a->address1 = '1 rue du Test';
    $a->postcode = '75001';
    $a->city = $city;
    $a->add();
    return $a;
}

function findCustomer($name)
{
    $rows = Customer::getCustomersByEmail(email($name));
    return $rows ? new Customer((int)$rows[0]['id_customer']) : null;
}

/** Same effect as the newsletter block of the footer, without the form (and its captcha). */
function newsletterBlock($name, $subscribe)
{
    $email = email($name);
    $where = 'email = "' . pSQL($email) . '"';
    if ($subscribe) {
        Db::getInstance()->insert('emailsubscription', array(
            'id_shop' => (int)Context::getContext()->shop->id,
            'id_shop_group' => (int)Context::getContext()->shop->id_shop_group,
            'email' => pSQL($email),
            'newsletter_date_add' => date('Y-m-d H:i:s'),
            'ip_registration_newsletter' => '127.0.0.1',
            'http_referer' => 'e2e',
            'active' => 1,
            'id_lang' => (int)Configuration::get('PS_LANG_DEFAULT'),
        ));
    } else {
        Db::getInstance()->update('emailsubscription', array('active' => 0), $where);
    }
    Hook::exec('actionNewsletterRegistrationAfter', array('email' => $email, 'action' => $subscribe ? '0' : '1', 'error' => null));
}

function emailOnlyActive($name)
{
    return Db::getInstance()->getValue(
        'SELECT active FROM ' . _DB_PREFIX_ . 'emailsubscription WHERE email = "' . pSQL(email($name)) . '"'
    );
}

function failedWebhooksSince($since)
{
    return (int)Db::getInstance()->getValue(
        'SELECT COUNT(*) FROM ' . _DB_PREFIX_ . 'log WHERE message LIKE "OdooWebhookClient%" AND date_add >= "' . pSQL($since) . '"'
    );
}

echo "== $phase on $domain, tag $tag ==\n";

if ($phase === 'setup') {
    $started = date('Y-m-d H:i:s');
    check('webhook configured and enabled',
        Configuration::get('PSODOO_WEBHOOK_URL') && Configuration::get('PSODOO_WEBHOOK_SECRET') && Configuration::get('PSODOO_WEBHOOK_ENABLED'));
    check('ps_emailsubscription installed', (bool)Module::isInstalled('ps_emailsubscription'));

    createCustomer('c1news', 1, 0);
    createCustomer('c2offers', 0, 1);

    $c = createCustomer('c3toggle', 1, 0);
    newRequest();
    $c->newsletter = 0;
    $c->update();

    $c = createCustomer('c4old', 1, 0);
    newRequest();
    $c->email = email('c4new');
    $c->update();

    $c = createCustomer('c5addr', 0, 0);
    $kept = createAddress($c, 'Paris');
    $kept->city = 'Lyon';
    $kept->update();
    $removed = createAddress($c, 'Marseille');
    $removed->delete();

    createCustomer('c6optout', 1, 1);
    createCustomer('c7black', 1, 1);

    newsletterBlock('e1sub', true);
    newsletterBlock('e2unsub', true);
    newsletterBlock('e2unsub', false);
    newsletterBlock('e3optout', true);
    newsletterBlock('e4deact', true);
    // Deactivated straight in the database, with no hook: only the Odoo cron can see it.
    Db::getInstance()->update('emailsubscription', array('active' => 0), 'email = "' . pSQL(email('e4deact')) . '"');

    check('7 test customers created', count(array_filter(array(
        findCustomer('c1news'), findCustomer('c2offers'), findCustomer('c3toggle'), findCustomer('c4new'),
        findCustomer('c5addr'), findCustomer('c6optout'), findCustomer('c7black'),
    ))) === 7);
    $failed = failedWebhooksSince($started);
    check('every webhook was accepted by Odoo', $failed === 0, "$failed failed, see the PrestaShop logs");
    echo "Next: run e2e_odoo.py with E2E_PHASE=check, then this script with \"verify\".\n";
}

if ($phase === 'verify') {
    $c = findCustomer('c6optout');
    check('c6: Odoo opt-out switched newsletter off, optin untouched',
        $c && (int)$c->newsletter === 0 && (int)$c->optin === 1,
        $c ? "newsletter={$c->newsletter} optin={$c->optin}" : 'customer not found');
    $c = findCustomer('c7black');
    check('c7: Odoo blacklist switched both consents off',
        $c && (int)$c->newsletter === 0 && (int)$c->optin === 0,
        $c ? "newsletter={$c->newsletter} optin={$c->optin}" : 'customer not found');
    $c = findCustomer('c1news');
    check('c1: untouched customer is still subscribed', $c && (int)$c->newsletter === 1);
    $c = findCustomer('c2offers');
    check('c2: untouched customer still has optin', $c && (int)$c->optin === 1 && (int)$c->newsletter === 0);
    check('e3: Odoo opt-out deactivated the email-only row', (string)emailOnlyActive('e3optout') === '0');
    check('e1: untouched email-only row is still active', (string)emailOnlyActive('e1sub') === '1');
}

if ($phase === 'cleanup') {
    $ids = Db::getInstance()->executeS(
        'SELECT id_customer FROM ' . _DB_PREFIX_ . 'customer WHERE email LIKE "' . pSQL("e2e-$tag-") . '%@example.invalid"'
    ) ?: array();
    foreach ($ids as $row) {
        $c = new Customer((int)$row['id_customer']);
        $c->delete();
    }
    Db::getInstance()->delete('emailsubscription', 'email LIKE "' . pSQL("e2e-$tag-") . '%@example.invalid"');
    echo count($ids) . " test customers and their email-only rows deleted.\n";
}

echo $failures ? "\n$failures check(s) FAILED\n" : "\nOK\n";
exit($failures ? 1 : 0);
