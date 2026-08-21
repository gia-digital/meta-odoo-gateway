#!/usr/bin/env python3
"""Importa agent_info/ o un ZIP hacia el knowledge store (Postgres).

Ejemplos:

  # Tras deploy: aplicar el agent_info del contenedor
  docker compose -f docker-compose.prod.yml --env-file .deploy.env exec api \\
    python -m scripts.import_knowledge --from-agent-info

  # Desde un ZIP exportado
  python -m scripts.import_knowledge --zip ./gia-knowledge.zip --include-files

  # Desde un directorio local
  python -m scripts.import_knowledge --dir ./agent_info --deactivate-missing
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def _run(
    *,
    zip_path: Path | None,
    dir_path: Path | None,
    from_agent_info: bool,
    include_files: bool,
    deactivate_missing: bool,
) -> dict:
    from app.models.db import SessionLocal
    from app.services.knowledge.import_agent_info import (
        import_agent_info_bundle,
        load_bundle_from_dir,
        load_bundle_from_zip,
    )
    from app.services.knowledge.seed import AGENT_INFO

    if from_agent_info:
        bundle = load_bundle_from_dir(AGENT_INFO)
    elif zip_path is not None:
        bundle = load_bundle_from_zip(zip_path.read_bytes())
    elif dir_path is not None:
        bundle = load_bundle_from_dir(dir_path)
    else:
        raise SystemExit("Indica --zip, --dir o --from-agent-info")

    async with SessionLocal() as db:
        return await import_agent_info_bundle(
            db,
            bundle,
            include_files=include_files,
            deactivate_missing=deactivate_missing,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import knowledge ← agent_info / ZIP")
    parser.add_argument("--zip", type=Path, help="ZIP exportado")
    parser.add_argument("--dir", type=Path, help="Directorio agent_info/")
    parser.add_argument(
        "--from-agent-info",
        action="store_true",
        help="Usa agent_info/ embebido en el contenedor/repo",
    )
    parser.add_argument(
        "--include-files",
        action="store_true",
        help="También importa PDFs/archivos",
    )
    parser.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="Desactiva filas que no vienen en el paquete",
    )
    args = parser.parse_args()
    counts = asyncio.run(
        _run(
            zip_path=args.zip,
            dir_path=args.dir,
            from_agent_info=args.from_agent_info,
            include_files=args.include_files,
            deactivate_missing=args.deactivate_missing,
        )
    )
    print("Import OK")
    for key, val in counts.items():
        print(f"  {key}={val}")


if __name__ == "__main__":
    main()
