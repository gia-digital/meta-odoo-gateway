"""Convierte agent_info/product_specs.json en entradas de knowledge_products."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[3]
SPECS_PATH = ROOT / "agent_info" / "product_specs.json"


def load_product_specs(path: Path | None = None) -> Dict[str, Any]:
    p = path or SPECS_PATH
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _fmt_weights(weights: Dict[str, Any]) -> str:
    parts = [f"{size}: {val} kg" for size, val in weights.items()]
    return "; ".join(parts)


def _flat_rows_text(rows: List[Dict[str, Any]]) -> str:
    lines = [
        "Calibre | mm | pulg | 3'x6' | 3'x8' | 3'x10' | 4'x8' | 4'x10' (kg/pieza)",
        "---",
    ]
    for row in rows:
        w = row.get("weights_kg") or {}
        lines.append(
            f"{row['caliber']} | {row['mm']} | {row['inch']} | "
            f"{w.get('3x6', '-')} | {w.get('3x8', '-')} | {w.get('3x10', '-')} | "
            f"{w.get('4x8', '-')} | {w.get('4x10', '-')}"
        )
    return "\n".join(lines)


def _tube_round_text(rows: List[Dict[str, Any]]) -> str:
    lines = ["Diámetro | Calibres (kg/ml / kg por 6 m) | Pzas/atado", "---"]
    for row in rows:
        cal_lines = []
        for c in row.get("calibers") or []:
            cal_lines.append(f"cal.{c['gauge']}: {c['kg_ml']} / {c['kg_6m']}")
        lines.append(
            f"{row['diameter']} | {' · '.join(cal_lines)} | {row.get('pieces_per_bundle', '-')}"
        )
    return "\n".join(lines)


def _tube_profile_text(rows: List[Dict[str, Any]]) -> str:
    lines = ["Medida | Calibres (kg/ml / kg por 6 m) | Pzas/atado", "---"]
    for row in rows:
        cal_lines = []
        for c in row.get("calibers") or []:
            cal_lines.append(f"cal.{c['gauge']}: {c['kg_ml']} / {c['kg_6m']}")
        lines.append(
            f"{row['profile']} | {' · '.join(cal_lines)} | {row.get('pieces_per_bundle', '-')}"
        )
    return "\n".join(lines)


def _corrugated_text(rows: List[Dict[str, Any]]) -> str:
    lines = ["Perfil | Ancho/peralte | Calibres (kg/ml / kg/m²)", "---"]
    for row in rows:
        cal_lines = []
        for c in row.get("calibers") or []:
            cal_lines.append(f"cal.{c['gauge']}: {c['kg_ml']} / {c['kg_m2']}")
        lines.append(
            f"{row['profile']} | {row.get('width_pitch', '')} | {' · '.join(cal_lines)}"
        )
    return "\n".join(lines)


def _wire_text(rows: List[Dict[str, Any]]) -> str:
    lines = ["Calibre | mm | pulg | rendimiento (m/kg)", "---"]
    for row in rows:
        lines.append(f"{row['caliber']} | {row['mm']} | {row['inch']} | {row['yield_m_per_kg']}")
    return "\n".join(lines)


def _rebar_text(rows: List[Dict[str, Any]]) -> str:
    lines = ["Medida | kg/ml", "---"]
    for row in rows:
        lines.append(f"{row['size']} | {row['kg_ml']}")
    return "\n".join(lines)


def _angle_text(rows: List[Dict[str, Any]]) -> str:
    lines = ["Largo (m) | kg/pieza", "---"]
    for row in rows:
        lines.append(f"{row['length_m']} | {row['kg_per_piece']}")
    return "\n".join(lines)


def specs_to_product_items(data: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """Genera items compatibles con products.json / import."""
    payload = data if data is not None else load_product_specs()
    if not payload:
        return []

    items: List[Dict[str, Any]] = []
    meta = payload.get("meta") or {}
    formulas = meta.get("formulas") or {}

    for block in payload.get("specs") or []:
        spec_id = (block.get("id") or "").strip()
        name = (block.get("name") or "").strip()
        if not name:
            continue

        applies = block.get("applies_to") or []
        valid = block.get("valid_calibers") or []
        notes = (block.get("notes") or "").strip()
        spec_type = (block.get("type") or "").strip()

        summary_parts = []
        if valid:
            summary_parts.append(
                f"Calibres GIA: {', '.join(str(c) for c in valid)}. "
                f"Fuera de esta lista no se maneja."
            )
        if block.get("caliber_range"):
            cr = block["caliber_range"]
            summary_parts.append(
                f"Rango espesor: {cr.get('min_mm')}–{cr.get('max_mm')} mm "
                f"(cal. {cr.get('min_gauge')} a {cr.get('max_gauge')})."
            )
        if block.get("lengths_m"):
            summary_parts.append(f"Largos: {block['lengths_m']}.")
        if block.get("min_order_ton"):
            summary_parts.append(f"Pedido mínimo: {block['min_order_ton']} ton.")

        detail_lines = []
        if applies:
            detail_lines.append(f"Aplica a: {', '.join(applies)}.")
        if block.get("standard_sheet_sizes"):
            detail_lines.append(
                "Medidas estándar de hoja: "
                + ", ".join(block["standard_sheet_sizes"])
                + "."
            )
        if formulas.get("sheet_kg"):
            detail_lines.append(f"Peso teórico hoja: {formulas['sheet_kg']}.")
        if formulas.get("strip_kg_ml"):
            detail_lines.append(f"Peso teórico cinta/ml: {formulas['strip_kg_ml']}.")
        if formulas.get("tube_round_kg_ml"):
            detail_lines.append(f"Tubo redondo: {formulas['tube_round_kg_ml']}.")
        detail_lines.append(
            "Pesos teóricos con densidad 7,850 kg/m³; rige la báscula de GIA."
        )
        if notes:
            detail_lines.append(notes)

        rows = block.get("rows") or []
        if spec_type == "flat_sheets":
            detail_lines.append("\n" + _flat_rows_text(rows))
        elif spec_type == "tube_round":
            detail_lines.append("\n" + _tube_round_text(rows))
        elif spec_type == "tube_profile":
            detail_lines.append("\n" + _tube_profile_text(rows))
        elif spec_type == "corrugated":
            detail_lines.append("\n" + _corrugated_text(rows))
        elif spec_type == "wire":
            detail_lines.append("\n" + _wire_text(rows))
        elif spec_type == "rebar":
            detail_lines.append("\n" + _rebar_text(rows))
        elif spec_type == "angle":
            detail_lines.append("\n" + _angle_text(rows))

        aliases = block.get("aliases") or ""
        if valid:
            alias_cal = ", ".join(f"calibre {c}" for c in valid[:12])
            if len(valid) > 12:
                alias_cal += f", calibre {' '.join(str(c) for c in valid[12:20])}"
            aliases = f"{aliases}, {alias_cal}".strip(", ")

        items.append(
            {
                "name": name,
                "kind": "product",
                "category": "especificaciones",
                "sort_order": int(block.get("sort_order") or 500),
                "aliases": aliases,
                "summary": " ".join(summary_parts).strip(),
                "details": "\n".join(detail_lines).strip(),
                "spec_id": spec_id,
            }
        )

    return items


def _caliber_list_text(valid: List[Any]) -> str:
    return ", ".join(str(c) for c in valid)


def _flat_caliber_quick_ref(rows: List[Dict[str, Any]]) -> str:
    """Tabla compacta calibre → mm para pegar en cada línea de acero plano."""
    lines = ["Calibres GIA (mismo para todas las líneas planas):", ""]
    lines.append("Calibre | mm | pulg")
    lines.append("---")
    for row in rows:
        lines.append(f"{row['caliber']} | {row['mm']} | {row['inch']}")
    lines.append("")
    lines.append(
        "Pesos por hoja estándar (kg/pieza): ver producto "
        "«Aceros planos — calibres, espesores y pesos (Anexo A.1)» "
        "o la Carta de Presentación GIA."
    )
    return "\n".join(lines)


def _corrugated_for_product(product_name: str, rows: List[Dict[str, Any]]) -> Optional[str]:
    """Devuelve calibres del perfil que coincide con el nombre del producto."""
    name_cf = product_name.casefold()
    profile_keys = {
        "r-72": "R-72",
        "r-101": "R-101",
        "o-100": "O-100",
        "o-30": "O-30",
        "rn-100": "RN-100/35",
        "kr-18": "KR-18",
        "deck": "DECK 25",
    }
    for key, profile in profile_keys.items():
        if key in name_cf:
            row = next((r for r in rows if r.get("profile") == profile), None)
            if not row:
                return None
            cals = [str(c["gauge"]) for c in row.get("calibers") or []]
            lines = [
                f"Perfil {profile} ({row.get('width_pitch', '')}).",
                f"Calibres GIA: {', '.join(cals)}.",
                "",
            ]
            for c in row.get("calibers") or []:
                lines.append(
                    f"  cal. {c['gauge']}: {c['kg_ml']} kg/ml · {c['kg_m2']} kg/m²"
                )
            lines.append("Largos 6.10–12 m; galvanizado o pintro.")
            return "\n".join(lines)
    return None


def _spec_snippet_for_product(product_name: str, block: Dict[str, Any]) -> Optional[str]:
    """Texto de calibres/espesores para inyectar en un producto concreto."""
    spec_type = (block.get("type") or "").strip()
    rows = block.get("rows") or []
    valid = block.get("valid_calibers") or []

    if spec_type == "flat_sheets":
        return _flat_caliber_quick_ref(rows)

    if spec_type == "corrugated":
        return _corrugated_for_product(product_name, rows)

    if spec_type == "tube_round":
        lines = ["Tubería redonda — calibres por diámetro (largo estándar 6 m):", ""]
        for row in rows:
            cals = ", ".join(f"cal.{c['gauge']}" for c in row.get("calibers") or [])
            lines.append(f"{row['diameter']}: {cals} ({row.get('pieces_per_bundle', '-')} pzas/atado)")
        return "\n".join(lines)

    if spec_type == "tube_profile":
        lines = ["Tubería cuadrada/rectangular/ovalada — calibres por medida:", ""]
        for row in rows:
            cals = ", ".join(f"cal.{c['gauge']}" for c in row.get("calibers") or [])
            lines.append(f"{row['profile']}: {cals}")
        return "\n".join(lines)

    if spec_type == "rebar" and valid:
        lines = ["Varilla — peso por metro lineal:", ""]
        for row in rows:
            lines.append(f"{row['size']}: {row['kg_ml']} kg/ml")
        return "\n".join(lines)

    if spec_type == "wire" and valid:
        return (
            f"Calibres GIA: {_caliber_list_text(valid)}.\n"
            "Rendimiento (m/kg): ver «Alambre pulido — calibre, espesor y rendimiento (Anexo A.7)»."
        )

    if spec_type == "angle" and valid:
        lines = ["Ángulo camero 2 x 1 1/4\" cal. 14 — peso por largo:", ""]
        for row in rows:
            lines.append(f"{row['length_m']} m: {row['kg_per_piece']} kg/pieza")
        return "\n".join(lines)

    if valid:
        return f"Calibres GIA: {_caliber_list_text(valid)}."
    return None


SPEC_MARKER = "\n\n--- CALIBRES Y ESPECIFICACIONES (Anexo A) ---\n"


def _strip_spec_section(details: str) -> str:
    marker = SPEC_MARKER.strip()
    if marker in (details or ""):
        return (details or "").split(marker)[0].strip()
    return (details or "").strip()


def enrich_products_with_specs(
    products: List[Dict[str, Any]], specs_data: Dict[str, Any] | None = None
) -> List[Dict[str, Any]]:
    """Inyecta calibres/espesores en cada producto al que aplica una spec."""
    payload = specs_data if specs_data is not None else load_product_specs()
    if not payload:
        return products

    by_name = {(p.get("name") or "").strip(): p for p in products if p.get("name")}
    for block in payload.get("specs") or []:
        applies = block.get("applies_to") or []
        valid = block.get("valid_calibers") or []
        for pname in applies:
            product = by_name.get(pname)
            if not product:
                continue
            snippet = _spec_snippet_for_product(pname, block)
            if not snippet:
                continue

            base_details = _strip_spec_section(product.get("details") or "")
            product["details"] = base_details + SPEC_MARKER + snippet

            if valid and block.get("type") == "flat_sheets":
                product["summary"] = (
                    (product.get("summary") or "").strip()
                    + f" Calibres GIA: {_caliber_list_text(valid)}."
                ).strip()
            elif valid and block.get("type") not in ("corrugated", "tube_round", "tube_profile"):
                product["summary"] = (
                    (product.get("summary") or "").strip()
                    + f" Calibres: {_caliber_list_text(valid)}."
                ).strip()
            elif block.get("type") == "corrugated":
                cals_line = snippet.split("\n")[1] if "\n" in snippet else snippet
                if cals_line.startswith("Calibres"):
                    product["summary"] = (
                        (product.get("summary") or "").strip() + f" {cals_line}"
                    ).strip()

    return products


def merge_specs_into_products(products_data: Dict[str, Any]) -> Dict[str, Any]:
    """Añade productos Anexo A e inyecta calibres en las líneas que aplican."""
    merged = dict(products_data)
    specs_data = load_product_specs()
    base_products = list(merged.get("products") or [])
    if specs_data:
        base_products = enrich_products_with_specs(base_products, specs_data)

    spec_items = specs_to_product_items(specs_data)
    if not spec_items:
        merged["products"] = base_products
        return merged

    by_spec_id = {
        (p.get("spec_id") or p.get("name") or "").casefold(): p for p in base_products
    }
    for item in spec_items:
        key = (item.get("spec_id") or item.get("name") or "").casefold()
        existing = by_spec_id.get(key)
        if existing:
            existing.update({k: v for k, v in item.items() if k != "spec_id"})
        else:
            base_products.append({k: v for k, v in item.items() if k != "spec_id"})
            by_spec_id[key] = base_products[-1]

    merged["products"] = base_products
    sources = list(merged.get("generated_from") or [])
    if "agent_info/product_specs.json" not in sources:
        sources.append("agent_info/product_specs.json")
    merged["generated_from"] = sources
    return merged
