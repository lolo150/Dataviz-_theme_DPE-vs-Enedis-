# Version complète : correction ciblée des départements

Cette version remplace la livraison restrictive précédente. Le dataset complet est inclus et conservé à l’identique : 67 886 lignes. Aucune consommation ou caractéristique source n’est inventée, supprimée ou modifiée.

## Utilisation
Décompresser dans un nouveau dossier et lancer :

    python -m pip install -r requirements.txt
    python app.py

Ouvrir http://127.0.0.1:8050. Arrêter auparavant l’ancien dashboard s’il utilise le port 8050.
Le filtre Origine commence sur « Toutes les données du fichier ». Les filtres permettent toujours de distinguer les données simulées, les sources originales à vérifier et les comparaisons réelles validées.
Les caractéristiques et les usages disponibles dans la version complète sont conservés. Il n’y a plus de filtrage initial restrictif vers les seules 14 lignes originales.

## Corrections ciblées
- Chaque sélection géographique utilise code_departement et l’année demandée.
- Les quatre vues départementales partagent la même population filtrée, en mode brut ou équilibré.
- Dispersion : écart-type échantillonnal, diviseur n−1. Les classes DPE isolées ne sont plus exclues d’une analyse globale départementale. L’écart-type reste indisponible si moins de deux adresses sont présentes dans le groupe affiché.
- Consommation : moyenne par adresse des valeurs par logement présentes dans le fichier. Les immeubles ne sont pas pondérés par leur nombre de logements.
- Écart : Enedis moins DPE, recalculé à partir des valeurs du fichier.
- Profils : proportions d’adresses selon la caractéristique enregistrée, totalisant 100 % avant arrondi. Les catégories manquantes sont conservées explicitement.
- Boutons Profils : un seul gestionnaire d’événements ouvre explicitement la vue au survol, au clic ou au clavier. Les graphiques précalculés sont utilisés.
- Un changement de sélection masque le cache précédent jusqu’à réception des résultats correspondants.
- Les KPI généraux prennent aussi en compte le mode brut/équilibré lors de la sélection départementale.
- Les résumés des boutons portent sur la sélection réunie ; les graphiques présentent les départements séparément. Ces deux niveaux sont indiqués. La dispersion globale ne se calcule pas en moyennant les dispersions départementales.
- La carte est calculée sur les départements sélectionnés s’il existe une sélection.
- Les effectifs sont libellés en adresses et non en logements.

## Échantillon brut et profils équilibrés
Brut : conserver toutes les adresses répondant aux filtres.
Équilibré : mêmes effectifs dans des profils communs aux départements, avec année, origine, classe DPE, surface en tranche, énergie, type, isolation, construction et installation de chauffage identiques. Tirage reproductible, sans créer de données. Chaque profil nécessite au moins deux adresses dans chaque département.
Les résultats équilibrés peuvent être très peu nombreux. Exemple 2024, toutes origines, Var + Hauts-de-Seine : 674 observations brutes, mais seulement 4 équilibrées dans un profil commun. Cette réduction n’est pas une perte du dataset : c’est un sous-ensemble analytique. Le mode brut permet de retrouver tous les résultats filtrés.

## Contrôles réalisés
- 67 886 lignes chargées : 67 872 simulées et 14 déclarées originales.
- CSV livré identique octet par octet à celui utilisé précédemment.
- Comparaisons testées en 2023 et 2024 : Var seul, Var/Hauts-de-Seine, Corse-du-Sud/Guadeloupe.
- Adresses identiques dans les quatre vues pour chaque sélection.
- Moyennes, écarts et écart-type confrontés à des calculs indépendants.
- Toutes les caractéristiques proposées en Profils produisent des graphiques ; proportions par département égales à 100 %.
- Zéro incohérence entre surface_m2 et tranche_surface avec les bornes 0, 30, 50, 70, 90, 120 et au-delà.
- Le nombre détaillé d’équipements n’est renseigné sur aucune ligne : aucune catégorie numérique d’équipements n’est inventée à partir des consommations.
- Le fichier ne comporte aucun doublon adresse–année.
- Les sources originales et simulées restent distinguables. Les simulations incluent des adresses fictives et certains codes commune fictifs : leur rattachement territorial est celui déclaré par le dataset, pas une adresse réelle vérifiée.

Exemple de contrôle, 2024, toutes origines, mode brut, kWh/logement/an :
| Département | Adresses | Enedis moyen | DPE moyen | Écart moyen | Écart-type |
|---|---:|---:|---:|---:|---:|
| Var (83) | 337 | 10 321,14 | 8 911,84 | +1 409,30 | 3 211,22 |
| Hauts-de-Seine (92) | 337 | 9 609,87 | 8 740,78 | +869,09 | 2 756,41 |
Ces chiffres décrivent ce dataset, incluant les simulations, pas les consommations réelles représentatives des départements.

Pour relancer les contrôles : python verifier_calculs.py.
La syntaxe Python/JavaScript et les réponses HTTP sont vérifiées. Le rendu visuel complet, les survols physiques et l’impression PDF restent à vérifier dans le navigateur local.
