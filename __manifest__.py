# -*- coding: utf-8 -*-
{
    "name": "PrestaShop Connector (Basic)",
    "version": "17.0.1.0.81",
    "category": "Sales",
    "summary": "Basic PrestaShop 1.7 connector for Odoo 17: customers, addresses and marketing consents (Email Marketing lists per site, opt-out/blacklist pushed back to PrestaShop); order import disabled",
    "author": "Metrodyn",
    "license": "LGPL-3",
    "depends": ["sale_management", "stock", "contacts", "sales_team", "mass_mailing"],
    "data": [
        "security/ir.model.access.csv",
        "views/prestashop_cron_shortcut.xml",
        "views/prestashop_reimport_customer_wizard.xml",
        "views/prestashop_contact_views.xml",
        "views/prestashop_backend_views.xml",
        "views/prestashop_log_views.xml",
        "views/prestashop_menu.xml",
        "data/ir_cron.xml",
    ],
    "application": True,
    "installable": True,
}
