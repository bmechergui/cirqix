"""La réparation des nets orphelins doit fonctionner sur un board KiCad 10.

⚠️ MESURE DU 2026-09-08. Deux écritures coexistent pour la même information :

    (net 3 "GND")     ← kicad-tools, et KiCad ≤ 9
    (net "GND")       ← pcbnew de KiCad 10 (`generator_version "10.0"`)

`_patch_floating_nets` n'acceptait que la première, dans TROIS expressions
indépendantes. Or **tous** nos boards sortent de pcbnew 10 :

    carte-02   numérotés=0   nus=93
    carte-04   numérotés=0   nus=181
    carte-07   numérotés=0   nus=570
    carte-10   numérotés=0   nus=988

`net_id_to_name` était donc TOUJOURS vide, la réparation ne touchait RIEN, et
la fonction rendait son entrée inchangée — sans le moindre message.

Conséquence mesurée sur le banc : **six cartes sur onze** livrent des pastilles
portant un net orphelin alors que le SCHÉMA les nomme, et ce sont des broches
d'ALIMENTATION.

    carte-04   2 perdues   U1.36, U1.48        attendu +3V3
    carte-05   2 perdues   U1.36, U1.48        attendu +3V3
    carte-07   5 perdues   C3.1, U1.36, U1.48, U2.2  attendu +3V3
    carte-08   5 perdues   idem
    carte-09   5 perdues   idem
    carte-10   5 perdues   idem

`U2.2` est la SORTIE du régulateur AMS1117-3.3 : sur `carte-07`, le régulateur
n'alimentait rien. C'est ce que montre la capture de l'utilisateur.

⚠️ POURQUOI LE DRC NE POUVAIT PAS LE VOIR. Un net orphelin est un net à part
entière : il n'a aucune connexion manquante à signaler. Le board sort donc
« 100 % routé, 0 erreur ». Même famille que le composant absent de `carte-05`,
et que toutes les autres de cette semaine : **l'absence se lit comme un succès.**

⚠️ C'est le MÊME piège de forme que `_NET_DECL_RE` le 2026-08-20 — corrigé
là-bas, jamais ici. Quand une forme de fichier trompe une expression, il faut
chercher SES SŒURS : elles ont été écrites le même jour, sur la même hypothèse.

⚠️ Toutes les broches orphelines ne sont pas des défauts : une GPIO de MCU non
utilisée porte légitimement `Net-(U1-10)`. Le défaut, c'est une broche que le
schéma NOMME et que le board a perdue. La garde ne doit pas confondre les deux.
"""
from __future__ import annotations

NL = chr(10)
T = chr(9)

import re
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import pcb as P  # noqa: E402


class _Broche:
    def __init__(self, ref: str, pin) -> None:
        self.ref, self.pin = ref, pin


class _Net:
    def __init__(self, name: str, pins: list[_Broche]) -> None:
        self.name, self.pins = name, pins


def _board(forme_numerotee: bool) -> str:
    """Un board minimal dans l'une ou l'autre ecriture.

    ⚠️ LA FIXTURE IMITE UN VRAI FICHIER pcbnew 10 : TABULATIONS et
    pastilles MULTI-LIGNES, la derniere suivie de `(embedded_fonts no)`.
    Une premiere version, ecrite avec des espaces et des pastilles d une seule
    ligne, faisait passer un decoupage qui rate la derniere pastille de chaque
    empreinte sur les vrais boards. Une fixture dit ce qu on a imagine ; seul
    un fichier reel dit ce qui est.
    """
    if forme_numerotee:
        entete = T + '(net 0 "")' + NL + T + '(net 1 "GND")' + NL + T + '(net 2 "Net-(U2-2)")'
        def pad(n):
            return '(net 2 "%s")' % n
    else:
        entete = T + '(net "")' + NL + T + '(net "GND")' + NL + T + '(net "Net-(U2-2)")'
        def pad(n):
            return '(net "%s")' % n

    def bloc_pad(num, net):
        return (T * 2 + '(pad "%s" smd roundrect' % num + NL
                + T * 3 + "(at 0 0)" + NL
                + T * 3 + "(size 1 1)" + NL
                + T * 3 + '(layers "F.Cu" "F.Mask" "F.Paste")' + NL
                + T * 3 + pad(net) + NL
                + T * 3 + '(uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")' + NL
                + T * 2 + ")")

    return ("(kicad_pcb" + NL
            + T + '(version 20241229)' + NL
            + T + '(generator "pcbnew")' + NL
            + T + '(generator_version "10.0")' + NL
            + entete + NL
            + T + '(footprint "Package_TO_SOT_SMD:SOT-223-3_TabPin2"' + NL
            + T * 2 + '(property "Reference" "U2")' + NL
            + bloc_pad("1", "GND") + NL
            + bloc_pad("2", "Net-(U2-2)") + NL
            # ⚠️ La languette porte AUSSI le numero 2 : c est le meme
            # noeud electrique, et elle est la DERNIERE pastille du boitier —
            # donc celle que l ancien decoupage n atteignait jamais.
            + bloc_pad("2", "Net-(U2-2)") + NL
            + T * 2 + "(embedded_fonts no)" + NL
            + T + ")" + NL
            + ")")


_CONNEXIONS = [_Net("+3V3", [_Broche("U2", 2)])]


class TestFormeKicad10:
    def test_un_board_kicad10_est_REPARE(self):
        """Le cas réel : aucun numéro nulle part."""
        avant = _board(forme_numerotee=False)
        assert "Net-(U2-2)" in avant
        apres = P._patch_floating_nets(avant, _CONNEXIONS)
        assert '"+3V3"' in apres, "la sortie du regulateur n'a pas ete rattachee"
        assert 'Net-(U2-2)"' not in apres.split("(footprint")[1], (
            "la pastille porte encore son net orphelin")

    def test_la_forme_ANCIENNE_marche_toujours(self):
        """On ajoute une écriture, on n'en retire aucune."""
        apres = P._patch_floating_nets(_board(forme_numerotee=True), _CONNEXIONS)
        assert '"+3V3"' in apres

    def test_on_ecrit_dans_la_forme_RECUE(self):
        """Mélanger les deux écritures ferait trancher au hasard le lecteur suivant."""
        apres = P._patch_floating_nets(_board(forme_numerotee=False), _CONNEXIONS)
        bloc = apres[apres.index("(footprint"):]
        assert re.search(r'\(net\s+"\+3V3"\)', bloc), (
            "un numero a ete reintroduit dans un board KiCad 10")

        apres_num = P._patch_floating_nets(_board(forme_numerotee=True), _CONNEXIONS)
        bloc_num = apres_num[apres_num.index("(footprint"):]
        assert re.search(r'\(net\s+\d+\s+"\+3V3"\)', bloc_num), (
            "le numero a disparu d'un board qui en portait")


class TestNeCasseRien:
    def test_une_broche_que_le_schema_ne_nomme_PAS_reste_orpheline(self):
        """Une GPIO inutilisee porte legitimement `Net-(U1-10)`.

        La reparation ne doit inventer aucun rattachement.
        """
        apres = P._patch_floating_nets(_board(forme_numerotee=False), [])
        assert "Net-(U2-2)" in apres


class TestCablage:
    def test_les_trois_expressions_acceptent_le_numero_optionnel(self):
        """Une regle correcte a un seul des trois endroits ne repare rien.

        ⚠️ Le defaut vivait dans TROIS expressions independantes de la meme
        fonction. Corriger la premiere sans les autres donnait un dictionnaire
        rempli et une lecture de pastille toujours aveugle — donc toujours
        aucune reparation, et l illusion d avoir corrige.
        """
        src = "\n".join(
            l for l in P._patch_floating_nets.__doc__ .splitlines()) if False else ""
        import inspect
        code = inspect.getsource(P._patch_floating_nets)
        # On ne compte que le CODE : un commentaire qui cite l ancienne forme
        # ne doit pas faire echouer la garde. Piege deja rencontre le 2026-09-08
        # sur `test_references_stables.py`.
        code = "\n".join(l.split("#")[0] for l in code.splitlines())
        assert r'\(net\s+\d+\s+"' not in code, (
            "une expression exige encore un numero de net")
        assert code.count(r'(?:\d+\s+)?') >= 1 or code.count(r'(\d+\s+)?') >= 1
