"""Disable tracking on peppol_eas to prevent KeyError on UAE contacts."""

from odoo import models, fields


class ResPartner(models.Model):
    _inherit = "res.partner"

    # Override peppol_eas to disable tracking.
    # The base module account_edi_ubl_cii defines this as a tracked selection
    # field, but the value '0235' (UAE) causes a KeyError in
    # mail.tracking.value._create_tracking_values when the selection list
    # changes between module versions.
    peppol_eas = fields.Selection(tracking=False)
