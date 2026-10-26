# StructLab — un assistant de structuration

> **En 3 pages :** [output/StructLab_en_3_pages.pdf](output/StructLab_en_3_pages.pdf) · **Exemple de fiche générée :** [output/phoenix_memoire.pdf](output/phoenix_memoire.pdf)

Tu décris un payoff, et l'outil :
1. **identifie le produit** (Phoenix, Athena, Autocall, Range Accrual, Twin Win, Reverse Convertible, note protégée, Warrant…) ;
2. le **décompose en briques** (zéro-coupon, digitales, puts à barrière, call spreads, options bermudéennes) ;
3. le **price** en Monte Carlo et **résout le coupon** (ou la participation) pour un prix cible ;
4. génère une **mini term sheet PDF** avec les scénarios, les probabilités, les sensibilités et la position de risque de la banque.

## Installation

```bash
pip install numpy scipy matplotlib pyyaml reportlab
```

Il faut ensuite se placer dans le dossier `structlab/`, celui qui contient ce README.

## Utilisation en 3 étapes

**1. Décrire le produit dans un fichier YAML.** Copie un fichier du dossier `examples/` et modifie-le. On ne donne jamais le nom du produit, seulement ses caractéristiques.

**2. Lancer l'analyse :**
```bash
python -m structlab examples/phoenix_memoire.yaml               # résumé + fiche PDF dans output/
python -m structlab examples/phoenix_memoire.yaml -o ma_fiche.pdf
python -m structlab examples/*.yaml                             # tous les exemples
python -m structlab examples/athena.yaml --no-pdf               # résumé console seulement
python -m structlab examples/athena.yaml --paths 50000          # plus de précision
```

**3. Ouvrir la fiche** dans `output/`.

On peut aussi passer par Python :
```python
from structlab import load_spec, analyze, build_termsheet
spec = load_spec("examples/phoenix_memoire.yaml")
res = analyze(spec)
print(res["solved"], res["fair_value"], res["p_loss"])
build_termsheet(spec, res, "phoenix.pdf")
```

Pour régénérer le document de présentation : `python -m structlab.demo`.

## Les champs du fichier YAML

Les pourcentages s'écrivent au choix `65%`, `65` ou `0.65`.

| Bloc | Champs | Valeurs |
|---|---|---|
| général | `maturity`, `frequency`, `notional`, `currency` | `frequency` : annual, semiannual, quarterly, monthly |
| `underlyings` | liste de `{name, vol, div, skew, smile}` (+ `spot` pour un warrant) | `vol` = vol ATM ; `skew` = pente du smile (ex. −0.25) ; `smile` = courbure (ex. 0.10) ; 0 = pas de skew |
| | `correlation`, `basket` | un nombre ou une matrice ; `worst_of`, `best_of`, `average` |
| `market` | `rate`, `issuer_spread` | taux sans risque, spread de financement de l'émetteur |
| `coupon` | `type` | `none`, `fixed`, `conditional`, `snowball`, `range_accrual` |
| | `rate`, `barrier`, `memory`, `lower`, `upper` | taux annuel, barrière coupon, mémoire, bornes du corridor |
| `autocall` | `barrier`, `start`, `stepdown`, `floor` | `start` = numéro de la 1re date de rappel |
| `redemption` | `type` | `barrier`, `protected`, `twin_win`, `full` |
| | `barrier`, `monitoring`, `strike`, `participation`, `cap`, `protection`, `down_participation` | `monitoring` : `european` ou `american` |
| `callable` | `start`, `price` | rappel au gré de l'émetteur |
| `puttable` | `start`, `price` | revente au gré de l'investisseur |
| `warrant` | `type`, `strike`, `parity` | + `product: warrant` |
| `pricing` | `paths`, `steps_per_year`, `seed`, `target_price`, `solve` | `solve` : `coupon` ou `participation` (choisi automatiquement par défaut) |

## Comment l'outil reconnaît le produit

| Caractéristiques | Produit identifié |
|---|---|
| rappel automatique + coupon conditionnel | Phoenix (Mémoire si `memory: true`) |
| rappel automatique + coupon `snowball` | Athena |
| rappel automatique + coupon fixe | Autocall à coupon fixe |
| coupon conditionnel + `callable`, sans rappel automatique | Phoenix Callable |
| coupon `range_accrual` | Range Accrual |
| remboursement `twin_win` | Twin Win |
| remboursement `barrier` + coupon fixe | (Barrier) Reverse Convertible |
| remboursement `protected` | Note à capital protégé (avec cap si `cap`) |
| `warrant` | Warrant Call / Put |

Le nom est complété par le type de panier (Worst-of…) et par les options embarquées (Callable, Puttable).

## Organisation du code

```
structlab/
  spec.py       lecture et validation du YAML
  market.py     simulation Monte Carlo multi-actifs corrélée
  engine.py     règles du produit (coupons, rappel, barrières) + Longstaff-Schwartz
  analytics.py  prix, résolution du coupon, statistiques, sensibilités, scénarios
  identify.py   identification, décomposition en briques, profil client
  warrant.py    Black-Scholes et grecques
  charts.py     graphiques
  report.py     fiche produit PDF
  demo.py       document de présentation
  cli.py        ligne de commande
examples/       un fichier par produit
```

## Hypothèses

Quand `skew` ou `smile` sont renseignés, la diffusion utilise une volatilité locale de Dupire déduite du smile paramétrique vol(k) = vol ATM + skew × k + smile × k², avec k = ln(strike/forward). Les vanilles repricées retrouvent ce smile, à environ 1 point de vol près, sauf très loin de la monnaie. Sans skew, le modèle est un Black-Scholes à volatilité constante. La corrélation est constante, et les taux et les dividendes sont déterministes. L'actualisation se fait au taux sans risque plus le spread de l'émetteur. Les barrières sont observées sur une grille hebdomadaire. Les options callable et puttable sont évaluées par Longstaff-Schwartz. Il s'agit d'un outil pédagogique : les paramètres de marché des exemples sont illustratifs.
