"""
Cliente JSON-RPC para Odoo Enterprise.

Odoo expone /jsonrpc para operaciones CRUD sobre cualquier modelo.
Soportamos autenticación con API Key (Odoo Enterprise) en vez de password.
"""
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.schemas import OdooLeadCreate

logger = get_logger(__name__)


class OdooError(Exception):
    pass


class OdooClient:
    """Cliente async para Odoo vía JSON-RPC."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._uid: Optional[int] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "OdooClient":
        self._client = httpx.AsyncClient(
            base_url=self.settings.odoo_url.rstrip("/"),
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )
        await self._authenticate()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()

    async def _authenticate(self) -> None:
        """Autentica vía common.authenticate y obtiene el uid."""
        assert self._client is not None
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "common",
                "method": "authenticate",
                "args": [
                    self.settings.odoo_db,
                    self.settings.odoo_username,
                    self.settings.odoo_api_key,
                    {},
                ],
            },
        }
        r = await self._client.post("/jsonrpc", json=payload)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise OdooError(f"Auth failed: {data['error']}")
        self._uid = data.get("result")
        if not self._uid:
            raise OdooError("Authentication returned no uid")
        logger.info("odoo_authenticated", uid=self._uid)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def execute_kw(
        self,
        model: str,
        method: str,
        args: List[Any],
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Ejecuta object.execute_kw — la entrada principal de la API de Odoo."""
        assert self._client is not None and self._uid is not None
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.settings.odoo_db,
                    self._uid,
                    self.settings.odoo_api_key,
                    model,
                    method,
                    args,
                    kwargs or {},
                ],
            },
        }
        r = await self._client.post("/jsonrpc", json=payload)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            logger.error("odoo_error", model=model, method=method, error=data["error"])
            raise OdooError(str(data["error"]))
        return data.get("result")

    # =================================================
    # Operaciones de alto nivel
    # =================================================

    async def find_partner_by_phone(self, phone: str) -> Optional[int]:
        """Busca un res.partner por teléfono o móvil. Devuelve el id o None."""
        # Normalizar: quitar espacios y caracteres no numéricos comunes
        normalized = phone.replace(" ", "").replace("-", "")
        domain = ["|", ("phone", "ilike", normalized), ("mobile", "ilike", normalized)]
        ids = await self.execute_kw("res.partner", "search", [domain], {"limit": 1})
        return ids[0] if ids else None

    async def find_partner_by_email(self, email: str) -> Optional[int]:
        ids = await self.execute_kw(
            "res.partner", "search", [[("email", "=ilike", email)]], {"limit": 1}
        )
        return ids[0] if ids else None

    async def create_partner(
        self,
        name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> int:
        """Crea un res.partner básico."""
        vals: Dict[str, Any] = {"name": name, "is_company": False}
        if phone:
            vals["mobile"] = phone
        if email:
            vals["email"] = email
        partner_id = await self.execute_kw("res.partner", "create", [vals])
        logger.info("odoo_partner_created", partner_id=partner_id, name=name)
        return partner_id

    async def create_lead(self, lead: OdooLeadCreate) -> int:
        """Crea un crm.lead con los datos de la conversación."""
        vals: Dict[str, Any] = {
            "name": lead.name,
            "type": "lead",
            "priority": lead.priority,
            "team_id": lead.team_id or self.settings.odoo_default_sales_team_id,
            "user_id": lead.user_id or self.settings.odoo_default_salesperson_id,
        }
        if lead.contact_name:
            vals["contact_name"] = lead.contact_name
        if lead.partner_name:
            vals["partner_name"] = lead.partner_name
        if lead.phone:
            vals["phone"] = lead.phone
        if lead.mobile:
            vals["mobile"] = lead.mobile
        if lead.email_from:
            vals["email_from"] = lead.email_from
        if lead.description:
            vals["description"] = lead.description
        if lead.source:
            # Buscar o crear utm.source
            source_id = await self._get_or_create_utm_source(lead.source)
            if source_id:
                vals["source_id"] = source_id
        if lead.tag_ids:
            vals["tag_ids"] = [(6, 0, lead.tag_ids)]

        lead_id = await self.execute_kw("crm.lead", "create", [vals])
        logger.info("odoo_lead_created", lead_id=lead_id, name=lead.name)
        return lead_id

    async def _get_or_create_utm_source(self, source_name: str) -> Optional[int]:
        ids = await self.execute_kw(
            "utm.source", "search", [[("name", "=", source_name)]], {"limit": 1}
        )
        if ids:
            return ids[0]
        try:
            return await self.execute_kw("utm.source", "create", [{"name": source_name}])
        except OdooError:
            return None

    async def post_internal_note(self, lead_id: int, body: str) -> None:
        """
        Agrega una nota interna al lead (no se envía al cliente).
        message_type='comment' + subtype 'mail.mt_note' = nota interna.
        """
        await self.execute_kw(
            "crm.lead",
            "message_post",
            [lead_id],
            {
                "body": body,
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_note",
            },
        )

    async def create_activity(
        self,
        lead_id: int,
        summary: str,
        note: str,
        user_id: Optional[int] = None,
        activity_type_id: int = 4,  # 4 = "To Do" por defecto
    ) -> int:
        """Crea una mail.activity (tarea) sobre el lead."""
        # Obtener res_model_id para crm.lead
        model_ids = await self.execute_kw(
            "ir.model", "search", [[("model", "=", "crm.lead")]], {"limit": 1}
        )
        vals = {
            "res_model_id": model_ids[0],
            "res_id": lead_id,
            "summary": summary,
            "note": note,
            "user_id": user_id or self.settings.odoo_default_salesperson_id,
            "activity_type_id": activity_type_id,
        }
        return await self.execute_kw("mail.activity", "create", [vals])
