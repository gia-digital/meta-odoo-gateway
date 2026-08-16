"""Acciones del agente (solo lectura en el dashboard)."""

REGISTERED_TOOLS = [
    {
        "name": "create_lead",
        "label": "Registrar prospecto",
        "source": "sistema",
        "when": (
            "Prospecto calificado: material del catálogo GIA y mayoreo "
            "(o pidió hablar con ventas). Nunca inoxidable/aluminio ni menudeo bajo mínimo."
        ),
    },
    {
        "name": "escalate_to_human",
        "label": "Pasar a un asesor",
        "source": "sistema",
        "when": (
            "Cotización formal, datos bancarios, reclamación, cliente con vendedor, "
            "o el cliente pide una persona. Abre el ticket; el bot sigue hasta que "
            "un humano escriba al cliente."
        ),
    },
    {
        "name": "search_knowledge",
        "label": "Consultar knowledge",
        "source": "sistema",
        "when": (
            "Si necesita más detalle de productos, FAQs, skills o archivos para responder bien."
        ),
    },
    {
        "name": "send_catalog",
        "label": "Enviar catálogo",
        "source": "sistema",
        "when": (
            "Si piden catálogo, carta de presentación, brochure o el PDF de líneas GIA. "
            "No usar para lista de precios mensual ni para la presentación corporativa 2027."
        ),
    },
    {
        "name": "check_sales_hours",
        "label": "Consultar horario de ventas",
        "source": "sistema",
        "when": (
            "Antes de decir cuándo un asesor puede contactar, o si el cliente "
            "propone un día/hora. No inventar franjas ni usar el horario de planta."
        ),
    },
]
