# StructuLab

Un petit outil pour comprendre les produits structurés : on décrit les règles d'un produit, et l'outil dit de quel produit il s'agit, le décompose en briques simples, calcule le coupon qu'on peut offrir et génère une fiche produit en PDF.

Présentation en 3 pages : [output/StructLab_en_3_pages.pdf](output/StructLab_en_3_pages.pdf)

## Produits traités

- **Phoenix** : coupon versé si le sous-jacent reste au-dessus d'une barrière, avec ou sans effet mémoire
- **Athena** : coupons accumulés, versés au moment du rappel
- **Reverse Convertible à barrière** : coupon fixe élevé contre un risque de baisse
- **Warrant** : call ou put coté

Le skew peut être pris en compte (vol locale déduite d'un smile simple).

## Lancer l'outil

```
pip install -r requirements.txt
python -m structlab examples/phoenix_memoire.yaml
```

La fiche PDF est créée dans `output/`. Pour tester un autre produit, copiez un fichier de `examples/` et modifiez ses paramètres.

Sans rien installer : bouton **Code → Codespaces → Create codespace**, puis la même commande dans le terminal.

## Décrire un produit

```
maturity: 5
frequency: quarterly            # annual, semiannual, quarterly, monthly
underlyings:
  - {name: Euro Stoxx 50, vol: 18%, div: 3.2%, skew: -0.25, smile: 0.10}
correlation: 0.65               # si plusieurs sous-jacents (on regarde le moins performant)
market: {rate: 2.5%, issuer_spread: 0.8%}
coupon: {type: conditional, rate: 8%, barrier: 65%, memory: true}   # none, fixed, conditional, snowball
autocall: {barrier: 100%, start: 4, stepdown: 1%, floor: 80%}         # optionnel
redemption: {type: barrier, barrier: 60%, monitoring: european}     # ou american ; type full = capital garanti
pricing: {target_price: 98%}    # l'outil cherche le coupon qui donne ce prix
```

## Comment ça marche

1. **Simulation** : 20 000 scénarios de marché pour les sous-jacents (Monte Carlo, corrélation, skew optionnel).
2. **Règles du produit** : sur chaque scénario, l'outil applique les coupons, le rappel automatique et le remboursement final.
3. **Prix** : moyenne des flux actualisés ; le coupon est ajusté jusqu'à atteindre le prix cible.
4. **Fiche** : décomposition, scénarios, probabilités et sensibilités (vol, corrélation, dividendes, taux).

## Limites

Smile simplifié (même pente pour toutes les maturités), taux et dividendes fixes, barrières observées chaque semaine. Les paramètres de marché des exemples sont illustratifs.
