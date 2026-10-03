# module-arduino-uno — Arduino Uno porté par la carte

**Question** : une carte qui PORTE un module du commerce se place-t-elle
proprement, le module appelé comme un composant dès le schéma ?

D-2026-09-27-a (validée par l'utilisateur le 2026-09-27) : « une carte qui
porte le module », « tu l'utilises comme tu appelles un composant dès la
fabrication du schéma ». Le module est le composant KiCad `MCU_Module:Arduino_UNO_R3`
(empreinte `Module:Arduino_UNO_R3`) ; on ne reconstruit ni sa carte ni ses connecteurs, et le
contour de notre carte reste libre autour de lui.

Circuit (`input/circuit.json`) : `A1` = Arduino_UNO_R3 ; 12 LED, chacune
derrière sa résistance de 330 Ω, sur les broches D2, D3, D4, D5, D6, D7, D8, D9, D10, D11, D12, D13 ;
anode côté résistance, cathode à la masse ; `J1` amène VIN et GND.

Taille de départ 110 × 85 mm, NON imposée : le contour se resserre
sur le placement, comme en production.

Mesuré par `scripts/banc_exemples.py` (référence : jamais livrée).
