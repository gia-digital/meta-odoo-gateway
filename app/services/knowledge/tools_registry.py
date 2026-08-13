"""Tools programados (solo lectura en el dashboard)."""

REGISTERED_TOOLS = [
    {
        "name": "create_lead",
        "source": "código · app/services/gia_agent.py",
        "when": (
            "Prospecto calificado: material del catálogo GIA y mayoreo "
            "(o pidió hablar con ventas). Nunca inoxidable/aluminio ni menudeo bajo mínimo."
        ),
    },
    {
        "name": "escalate_to_human",
        "source": "código · app/services/gia_agent.py",
        "when": (
            "Cotización formal, datos bancarios, reclamación, cliente con vendedor, "
            "o el cliente pide una persona. Abre el ticket en Chatwoot."
        ),
    },
    {
        "name": "search_knowledge",
        "source": "código · app/services/gia_agent.py",
        "when": (
            "El contexto RAG del turno no alcanza: busca FAQs, skills o archivos "
            "en pgvector con una consulta concreta."
        ),
    },
]
