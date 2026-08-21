#!/usr/bin/env python3
"""Exporta el knowledge store a un directorio (formato agent_info/).

Uso en el servidor (con DATABASE_URL del API):

  docker compose -f docker-compose.prod.yml --env-file .deploy.env exec api \\
    python -m scripts.export_knowledge --out /tmp/agent_info_export

O localmente apuntando a la misma DB:

  DATABASE_URL=postgresql+asyncpg://... python -m scripts.export_knowledge --out ./agent_info_export
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def _run(out: Path) -> dict:
    from app.models.db import SessionLocal
    from app.services.knowledge.export import write_export_to_dir

    async with SessionLocal() as db:
        return await write_export_to_dir(db, out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export knowledge → agent_info format")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("agent_info_export"),
        help="Directorio de salida (default: ./agent_info_export)",
    )
    args = parser.parse_args()
    counts = asyncio.run(_run(args.out.resolve()))
    print(f"Exportado en {args.out.resolve()}")
    print(
        f"  faqs={counts['faqs']} skills={counts['skills']} "
        f"products={counts['products']} files={counts['files_copied']}"
    )


if __name__ == "__main__":
    main()
