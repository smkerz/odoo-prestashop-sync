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
        ("import_products", "Import Products"),
        ("reimport_customer", "Reimport Customer by Presta ID"),
        ("sync_addresses", "Sync Customer Addresses"),
        ("sync_newsletter_tags", "Sync Newsletter Tags"),
        ("sync_partner_offers_tags", "Sync Partner Offers Tags"),
        ("sync_newsletter_marketing", "Sync Newsletter to Email Marketing"),
        ("sync_partner_offers_marketing", "Sync Partner Offers to Email Marketing"),
        ("sync_email_marketing", "Sync Email Marketing Lists"),
        ("preview_consents", "Preview Consents"),
        ("sync_consents", "Sync Consents"),
        ("push_opt_out_to_prestashop", "Push Opt-outs to PrestaShop"),
        ("sync_consents_odoo_to_prestashop", "Sync Consents Odoo -> PrestaShop"),
    ], required=True)
    status = fields.Selection([("ok", "OK"), ("warning", "Warning"), ("error", "Error")], required=True, default="ok")
    message = fields.Char(required=True)
    details = fields.Text()
    prestashop_id = fields.Char(index=True)
    duration_sec = fields.Float(string="Duration (s)")
