# Bug : le lien de désinscription Odoo Email Marketing ne fonctionne pas

## Problème

Quand un utilisateur reçoit un mailing envoyé depuis Odoo Email Marketing (mailing lists),
le lien "Unsubscribe" en bas de l'email pointe vers :

```
https://mcdavidian-test.mcdtoolbox.com/unsubscribe_from_list
```

Cette route nécessite une session authentifiée → l'utilisateur tombe sur la page de login
de la base de données Odoo → **impossible de se désabonner**.

## Comportement attendu

Le lien devrait pointer vers une route **publique** (sans login) comme :
```
/mail/mailing/<id>/unsubscribe?token=...&email=...
```

## Contexte

- Odoo 17 Community (Docker)
- Module `mass_mailing` installé
- Les mailings sont envoyés à des `mailing.list` (mailing contacts)
- Le problème se reproduit aussi bien avec un envoi test qu'un envoi réel
- `web.base.url` = `https://mcdavidian-test.mcdtoolbox.com`

## Ce qu'il faut investiguer

1. Vérifier le template du footer des mailings (`mail.mailing` default body footer)
2. Vérifier si la route `/unsubscribe_from_list` est censée être publique dans Odoo 17
3. Si c'est un bug Odoo, créer un override dans notre module pour exposer une route publique
   `/prestashop/unsubscribe` qui permet le opt-out sans login
4. Quand le opt-out est fait via cette route, notre module `mailing_contact_extend.py`
   poussera automatiquement `newsletter=0` vers PrestaShop (déjà câblé)

## Fichiers liés

- `models/mailing_contact_extend.py` — push temps réel des opt-outs vers PrestaShop
- `controllers/prestashop_webhook.py` — endpoints webhook existants
