# Question : relier deux îlots de plan de masse quand aucun via ne suffit

Tu n'as **rien à modifier**. Je veux ton avis technique sur une approche, et
les objections que tu vois. Réponds en français, court et précis.

## Le contexte, mesuré

Chaîne de conception PCB automatique (KiCad, Freerouting). Quatre cartes de
test. **Tous les signaux sont routés à 100 %.** Il ne reste que des connexions
de masse manquantes :

```
carte          manquantes   plan↔plan (îlots)   pastille↔plan
nucleo-f401         1              1                  0
stm32-30            2              2                  0
stm32-60            2              2                  0
stm32-100           7              3                  3
```

Zéro erreur DRC sur les quatre : elles sont fabricables, mais pas complètes.

## La géométrie exacte du problème

Le plan de masse est coulé sur les deux faces (F.Cu et B.Cu). Les pistes de
signal le découpent en îlots. Analyse des dix îlots de `nucleo-f401` :

```
F.Cu  11002 mm²   cuivre de masse en face = oui
B.Cu  11002 mm²   cuivre de masse en face = oui
F.Cu   1480 mm²   cuivre de masse en face = oui
B.Cu    238 mm²   cuivre de masse en face = NON     <- îlot orphelin
F.Cu    128 mm²   cuivre de masse en face = NON     <- îlot orphelin
F.Cu     75 · 60 · 50 · 8 · 4 mm²   en face = oui
```

Les îlots orphelins n'ont **aucun cuivre de masse en vis-à-vis, nulle part
sous leur surface**. Un via traversant posé dedans débouche sur du vide : il
ne relie rien.

## Ce qui a déjà été essayé, et mesuré

**① Un via par îlot, sans regarder en face** — comportement d'origine. Pose des
vias borgnes sur les îlots orphelins.

**② EXIGER du cuivre en face avant de percer** — testé, **réfuté par la
mesure** : la carte passe de 1 à 4 connexions manquantes. La condition refusait
des sites sans en chercher d'autres, donc moins de vias posés au total.

**③ PRÉFÉRER les points qui relient, sans les exiger** — livré. Gain réel mais
modeste : une connexion sur quatre cartes. Confirme que les îlots orphelins
n'ont de cuivre en face nulle part.

## L'approche que j'envisage — le pont

Pour un îlot orphelin :

```
1. poser un via V1 dans l'îlot
2. sur la face opposée, tracer une piste de masse de V1
   jusqu'au bord du plan principal de cette face
3. si nécessaire, un via V2 pour remonter
```

## Mes questions

1. **Est-ce la bonne approche**, ou existe-t-il un procédé standard que
   j'ignore pour raccorder un îlot de plan orphelin ?

2. **Comment choisir le trajet de la piste** sans entrer en conflit avec les
   pistes de signal déjà routées ? Faut-il un vrai routeur pour ce segment, ou
   une heuristique suffit-elle ?

3. **Un îlot orphelin de 128 mm² mérite-t-il d'être relié**, ou vaut-il mieux
   le **supprimer** du plan ? Un îlot de masse flottant est une antenne ; le
   retirer supprimerait aussi la connexion manquante au DRC.

4. Quels **pièges** vois-tu — création de boucles de masse, isolement
   insuffisant, fragilité en fabrication ?

5. Y a-t-il une raison de **préférer élargir le plan** (retoucher la zone pour
   qu'elle contourne les pistes) plutôt que d'ajouter du cuivre ?

Réponds sur le fond. Si tu penses que la question est mal posée, dis-le.
