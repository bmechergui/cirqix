# module-esp32-c3 — ESP32-C3-DevKitM-1 porté par la carte

**Question** : une carte qui PORTE un module du commerce se place-t-elle
proprement, le module appelé comme un composant dès le schéma ?

D-2026-09-27-a (validée par l'utilisateur le 2026-09-27) : « une carte qui
porte le module », « tu l'utilises comme tu appelles un composant dès la
fabrication du schéma ». Le module est le composant KiCad `RF_Module:ESP32-C3-DevKitM-1`
(empreinte `RF_Module:ESP32-C3-DevKitM-1`) ; on ne reconstruit ni sa carte ni ses connecteurs, et le
contour de notre carte reste libre autour de lui.

Circuit (`input/circuit.json`) : `A1` = ESP32-C3-DevKitM-1 ; 6 LED, chacune
derrière sa résistance de 330 Ω, sur les broches IO4, IO5, IO6, IO7, IO10, IO1 ;
anode côté résistance, cathode à la masse ; `J1` amène 5V et GND.

⚠️ KiCad n'a pas de module ESP32-DevKitC (ESP32 classique) : le DevKitM-1
(ESP32-C3) est le module ESP32 de ses bibliothèques.

Taille de départ 90 × 60 mm, NON imposée : le contour se resserre
sur le placement, comme en production.

Mesuré par `scripts/banc_exemples.py` (référence : jamais livrée).
