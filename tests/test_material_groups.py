"""Tests de agrupación de materiales para el dashboard."""
from app.services.material_groups import group_material_label


def test_group_galvanized_sheet_variants():
    a = 'Lámina galvanizada G90 lisa, calibres 26, 24, 22 y 20, medida 4x10 pies'
    b = "Lámina galvanizada G60/G90, calibres 28 y 26, hoja 4.80 x 5.10 m"
    c = "Lámina galvanizada"
    assert group_material_label(a) == "Lámina galvanizada G90"
    assert group_material_label(b) == "Lámina galvanizada G60/G90"
    assert group_material_label(c) == "Lámina galvanizada"


def test_group_pipe_variants():
    round_pipe = 'Tubería industrial de acero negro, galvanizada, redonda 2" cal 16 x 7.00 m'
    small_pipe = 'Tubería industrial de acero negro, tubo 7/8" calibre 20, largo 6 metros'
    short = "Tubería industrial"
    assert group_material_label(round_pipe) == "Tubería industrial de acero negro cal. 16"
    assert group_material_label(small_pipe) == "Tubería industrial de acero negro cal. 20"
    assert group_material_label(short) == "Tubería industrial de acero negro"


def test_group_profile_tubes_and_deck():
    oval = 'Tubo ovalado 5/8 x 1 1/8" calibre 18, 300 piezas de 6 metros'
    square = 'Tubo cuadrado de 3" calibre reforzado, 6 metros de largo'
    deck = "Steel Deck calibre 22, 12 metros"
    r101 = "Lámina acanalada R-101 Pintro blanca calibre 26 de 6 m; perfiles de acero estructural"
    assert group_material_label(oval) == "Tubería ovalada cal. 18"
    assert group_material_label(square) == "Tubería cuadrada / rectangular cal. reforzado"
    assert group_material_label(deck) == "Steel Deck cal. 22"
    assert group_material_label(r101) == "Lámina acanalada R-101 cal. 26"
