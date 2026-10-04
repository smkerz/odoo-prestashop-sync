# -*- coding: utf-8 -*-
from odoo import fields, models

class PrestashopBindingMixin(models.AbstractModel):
    _name = "prestashop.binding.mixin"
    _description = "PrestaShop Binding Mixin"
    _rec_name = "prestashop_id"

    backend_id = fields.Many2one("prestashop.backend", required=True, ondelete="cascade", index=True)
    prestashop_id = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("prestashop_id_backend_uniq", "unique(backend_id, prestashop_id)", "PrestaShop ID must be unique per backend."),
    ]

class PrestashopCustomerMap(models.Model):
    _name = "prestashop.customer.map"
    _inherit = "prestashop.binding.mixin"
    _description = "PrestaShop Customer Mapping"

    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade", index=True)

    # Convenience related fields for list/search views (read-only)
    partner_name = fields.Char(related="partner_id.name", store=False, readonly=True)
    partner_email = fields.Char(related="partner_id.email", store=False, readonly=True)
    partner_phone = fields.Char(related="partner_id.phone", store=False, readonly=True)

class PrestashopProductMap(models.Model):
    _name = "prestashop.product.map"
    _inherit = "prestashop.binding.mixin"
    _description = "PrestaShop Product Mapping"

    product_id = fields.Many2one("product.product", required=True, ondelete="cascade", index=True)
    default_code = fields.Char(related="product_id.default_code", store=False)

class PrestashopOrderMap(models.Model):
    _name = "prestashop.order.map"
    _inherit = "prestashop.binding.mixin"
    _description = "PrestaShop Order Mapping"

    sale_order_id = fields.Many2one("sale.order", required=True, ondelete="cascade", index=True)
    prestashop_reference = fields.Char(index=True)


class PrestashopAddressMap(models.Model):
    _name = "prestashop.address.map"
    _inherit = "prestashop.binding.mixin"
    _description = "PrestaShop Address Mapping"

    # The Odoo address record is a res.partner child of the main customer partner.
    address_partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade", index=True)
    parent_partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade", index=True)
