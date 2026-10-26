# StructuLab

Je suis étudiant, actuellement en stage chez Convera où je travaille sur le pricing de produits FX pour des clients corporate (KIKO, TARF, accumulateurs), et je cherche un stage en structuration cross-asset.

J'ai lancé ce projet pour préparer mes entretiens. En lisant *Exotic Options and Hybrids* (Bouzoubaa & Osseiran), je voulais vérifier que je savais vraiment faire ce qu'on attend d'un structureur : partir des règles d'un produit, le décomposer en briques simples, puis comprendre d'où vient le coupon et quels risques prend la banque.

L'outil fonctionne ainsi : on décrit un produit (coupon, rappel, barrière...), il reconnaît de quel produit il s'agit, le décompose, calcule le coupon qu'on peut offrir pour une marge donnée et génère une fiche produit en PDF. Ce qui m'a le plus appris, c'est l'effet du skew : sur un Phoenix worst-of, le coupon passe d'environ 7 % à 11 % quand on en tient compte.

Il prolonge mon projet précédent de [pricing d'options par différences finies](https://github.com/alexmagnan12/option-pricing-finite-differences). J'ai développé le code avec l'aide d'un assistant IA ; j'ai défini ce que l'outil devait faire et travaillé à comprendre chaque étape.

Présentation en 3 pages : [output/StructuLab_en_3_pages.pdf](output/StructuLab_en_3_pages.pdf)

## Produits traités

- **Phoenix** : coupon versé si le sous-jacent reste au-dessus d'une barrière, avec ou sans effet mémoire
- **Athena** : coupons accumulés, versés au moment du rappel
- **Reverse Convertible à barrière** : coupon fixe élevé contre un risque de baisse
- **Warrant** : call ou put coté

Le skew peut être pris en compte (vol locale déduite d'un smile simple).

## Utilisation

On décrit le produit **en français**, sans donner son nom :

```
python -m structlab "Produit 5 ans sur le CAC 40, coupon versé chaque trimestre si le CAC est au-dessus de 70 %, remboursement anticipé à partir de 1 an si le CAC est au-dessus de 100 %, capital protégé jusqu'à une baisse de 40 %"
```

L'outil affiche ce qu'il a compris (et les valeurs par défaut qu'il a prises), reconnaît le produit, le décompose, calcule le coupon et crée la term sheet dans `output/`.

Autres façons de l'utiliser :

```
python -m structlab                                   # mode interactif : on tape la description
python -m structlab examples/textes/phoenix.txt       # description dans un fichier texte
python -m structlab examples/phoenix_memoire.yaml     # description détaillée, paramètre par paramètre
```

Ce que l'outil sait lire dans le texte : les sous-jacents (principaux indices et quelques actions), la durée, la fréquence d'observation, le coupon (fixe, conditionnel, avec mémoire, accumulé), le remboursement anticipé (niveau, première date, barrière dégressive), la protection du capital (niveau, observée à l'échéance ou en continu), la marge et la corrélation. Si un coupon est donné sans marge, l'outil calcule la valeur du produit ; sinon il cherche le coupon qui respecte la marge (2 % par défaut).

Installation : `pip install -r requirements.txt`. Sans rien installer : bouton **Code → Codespaces → Create codespace**, puis les mêmes commandes dans le terminal.

## Décrire un produit en détail (fichier YAML)

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
