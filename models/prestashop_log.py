# -*- coding: utf-8 -*-
from odoo import fields, models

class PrestashopSyncLog(models.Model):
    _name = "prestashop.sync.log"
    _description = "PrestaShop Sync Log"
    _order = "create_date desc"

    backend_id = fields.Many2one("prestashop.backend", required=True, ondelete="cascade", index=True)
    operation = fields.Selection([
        ("import_orders", "Import Orders"),
        ("import_customers", "Import Customers"),
        ("sync_addresses", "Sync Addresses"),
        ("sync_email_marketing", "Sync Email Marketing"),
        ("preview_consents", "Preview Consents"),
        ("sync_consents", "Sync Consents (Webhook)"),
        ("sync_consents_odoo_to_prestashop", "Consents Odoo → PrestaShop"),
        ("webhook_create_customer", "Webhook Create Customer"),
    ], required=True)
    status = fields.Selection([
        ("ok", "OK"),
        ("info", "Info"),
        ("warning", "Warning"),
        ("error", "Error"),
    ], required=True, default="ok")
    message = fields.Char(required=True)
    details = fields.Text()
    prestashop_id = fields.Char(index=True)
    duration_sec = fields.Float(string="Duration (s)")
