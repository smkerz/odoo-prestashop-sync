# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PrestashopReimportCustomerWizard(models.TransientModel):
    _name = "prestashop.reimport.customer.wizard"
    _description = "Reimport PrestaShop Customer by ID"

    backend_id = fields.Many2one(
        "prestashop.backend",
        required=True,
        ondelete="cascade",
        default=lambda self: self._default_backend_id(),
    )
    prestashop_customer_id = fields.Integer(string="PrestaShop Customer ID", required=True)

    @api.model
    def _default_backend_id(self):
        ctx = self.env.context
        if ctx.get("default_backend_id"):
            return ctx["default_backend_id"]
        if ctx.get("active_model") == "prestashop.backend" and ctx.get("active_id"):
            return ctx["active_id"]
        return False

    def action_reimport(self):
        self.ensure_one()
        if not self.backend_id:
            raise UserError(_("Missing backend."))
        if not self.prestashop_customer_id or self.prestashop_customer_id <= 0:
            raise UserError(_("Please provide a valid PrestaShop customer ID (> 0)."))

        msg = self.backend_id._reimport_customer_by_presta_id(int(self.prestashop_customer_id))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("PrestaShop"),
                "message": msg or _("Customer reimport finished."),
                "sticky": False,
            },
        }
