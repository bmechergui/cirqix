# module-nucleo-64 — Nucleo-64 portée par la carte

**Question** : une carte qui PORTE un module du commerce se place-t-elle
proprement, le module appelé comme un composant dès le schéma ?

D-2026-09-27-a (validée par l'utilisateur le 2026-09-27) : « une carte qui
porte le module », « tu l'utilises comme tu appelles un composant dès la
fabrication du schéma ». Le module est le composant KiCad `MCU_Module:NUCLEO64-F411RE`
(empreinte `Module:ST_Morpho_Connector_144_STLink`) ; on ne reconstruit ni sa carte ni ses connecteurs, et le
contour de notre carte reste libre autour de lui.

Circuit (`input/circuit.json`) : `A1` = NUCLEO64-F411RE ; 8 LED, chacune
derrière sa résistance de 330 Ω, sur les broches PA5, PA6, PA7, PB6, PC7, PA9, PA8, PB10 ;
anode côté résistance, cathode à la masse ; `J1` amène VIN et GND.

⚠️ L'empreinte par défaut du symbole KiCad est `ST_Morpho_Connector_144_STLink`
(connecteurs morpho), celle que KiCad associe à ce module.

Taille de départ 170 × 110 mm, NON imposée : le contour se resserre
sur le placement, comme en production.

Mesuré par `scripts/banc_exemples.py` (référence : jamais livrée).
