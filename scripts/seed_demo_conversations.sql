-- Datos de demostración para el dashboard (conversaciones y propuestas).
-- Identificador: external_user_id LIKE 'seed-demo-%'
-- Idempotente: borra las filas de demo anteriores y las vuelve a insertar.

DELETE FROM conversations WHERE external_user_id LIKE 'seed-demo-%';

-- 1. Activa, apenas saluda
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, status, score,
    score_breakdown, qualification_source, chatwoot_conversation_id,
    created_at, updated_at
  ) VALUES (
    'whatsapp', 'seed-demo-wa-001', 'Luis Hernández', '+52 81 1200 4411',
    'active', 0,
    '{"signals":[]}'::json, 'none', 91001,
    now() - interval '20 minutes', now() - interval '18 minutes'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Hola, buenos días', 'seed-demo-m-001a', now() - interval '20 minutes'),
  ('outbound'::direction, 'Buen día, soy GIA. ¿En qué material te puedo orientar?', 'seed-demo-m-001b', now() - interval '18 minutes')
) AS msgs(d, b, m, t);

-- 2. Activa, explorando lámina, sin volumen
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, status, score,
    score_breakdown, qualification_source, product_interest,
    chatwoot_conversation_id, created_at, updated_at
  ) VALUES (
    'whatsapp', 'seed-demo-wa-002', 'Mónica Ríos', '+52 81 8344 2201',
    'active', 3,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: lámina"},{"name":"multiple_messages","points":1,"matched":true,"evidence":"user messages: 3"}]}'::json,
    'none', 'Lámina galvanizada',
    91002,
    now() - interval '3 hours', now() - interval '2 hours'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Hola, ¿manejan lámina galvanizada?', 'seed-demo-m-002a', now() - interval '3 hours'),
  ('outbound'::direction, 'Sí, galvanizada G60 y G90 en rollo, hoja y cinta, en mayoreo. ¿Qué calibre y presentación necesitas?', 'seed-demo-m-002b', now() - interval '2 hours 50 minutes'),
  ('inbound'::direction, 'Calibre 26, en hoja de 3 por 8', 'seed-demo-m-002c', now() - interval '2 hours 40 minutes'),
  ('outbound'::direction, 'El calibre 26 está en aceros planos. ¿Cuántas toneladas estás contemplando?', 'seed-demo-m-002d', now() - interval '2 hours 30 minutes'),
  ('inbound'::direction, 'Todavía no lo tengo claro, déjame checar con obra', 'seed-demo-m-002e', now() - interval '2 hours')
) AS msgs(d, b, m, t);

-- 3. Calificada: lámina galvanizada 12 ton
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, user_email, status, score,
    score_breakdown, qualification_source, qualification_reason, qualified_at,
    product_interest, lead_summary, budget, timeline, preferred_contact_time,
    chatwoot_conversation_id, created_at, updated_at
  ) VALUES (
    'whatsapp', 'seed-demo-wa-003', 'Constructora del Valle', '+52 81 1555 9033',
    'compras@constructoradelvalle.mx', 'qualified', 12,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: lámina"},{"name":"budget_mentioned","points":3,"matched":true,"evidence":"keyword: toneladas, amount: 12"},{"name":"urgency_signaled","points":2,"matched":true,"evidence":"keyword: este mes"},{"name":"decision_intent","points":4,"matched":true,"evidence":"keyword: quiero cotizar"},{"name":"multiple_messages","points":1,"matched":true,"evidence":"user messages: 4"}]}'::json,
    'chatwoot_agent', 'Pidió cotización de lámina galvanizada G90',
    now() - interval '1 day',
    'Lámina galvanizada G90',
    'Obra de bodega en Apodaca. Necesitan hoja calibre 24, 4''×10''. Entrega en patio de obra.',
    '12 toneladas', 'Este mes', 'Mañanas, 9 a 12',
    91003,
    now() - interval '1 day 2 hours', now() - interval '1 day'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Buen día, quiero cotizar lámina galvanizada G90', 'seed-demo-m-003a', now() - interval '1 day 2 hours'),
  ('outbound'::direction, 'Con gusto. ¿Calibre, medida de hoja y volumen aproximado?', 'seed-demo-m-003b', now() - interval '1 day 1 hour 50 minutes'),
  ('inbound'::direction, 'Calibre 24, hojas de 4 por 10. Unas 12 toneladas', 'seed-demo-m-003c', now() - interval '1 day 1 hour 30 minutes'),
  ('outbound'::direction, '12 toneladas de G90 calibre 24 está dentro de mayoreo. ¿Para cuándo lo necesitas y a nombre de quién cotizamos?', 'seed-demo-m-003d', now() - interval '1 day 1 hour 20 minutes'),
  ('inbound'::direction, 'Para este mes. Somos Constructora del Valle, compras@constructoradelvalle.mx, mejor por la mañana', 'seed-demo-m-003e', now() - interval '1 day 1 hour'),
  ('outbound'::direction, 'Quedó registrada la solicitud. Un asesor de ventas te contacta en horario de mañana para la cotización.', 'seed-demo-m-003f', now() - interval '1 day')
) AS msgs(d, b, m, t);

-- 4. Calificada por score local: varilla 30 ton
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, user_email, status, score,
    score_breakdown, qualification_source, qualification_reason, qualified_at,
    product_interest, lead_summary, budget, timeline, preferred_contact_time,
    chatwoot_conversation_id, created_at, updated_at
  ) VALUES (
    'messenger', 'seed-demo-ms-004', 'Aceros y Estructuras Peña', '+52 81 8001 4470',
    'jpena@aepena.com', 'qualified', 10,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: varilla"},{"name":"budget_mentioned","points":3,"matched":true,"evidence":"keyword: toneladas, amount: 30"},{"name":"decision_intent","points":4,"matched":true,"evidence":"keyword: quiero cotizar"},{"name":"multiple_messages","points":1,"matched":true,"evidence":"user messages: 3"}]}'::json,
    'local_score', 'Qualified by local score',
    now() - interval '2 days',
    'Varilla corrugada',
    'Distribuidor en García, NL. Pide 3/8 y 1/2, un camión. Factura a razón social.',
    '30 toneladas (1 camión)', 'En 2 semanas', 'Después de las 4 pm',
    91004,
    now() - interval '2 days 3 hours', now() - interval '2 days'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Hola, quiero cotizar varilla', 'seed-demo-m-004a', now() - interval '2 days 3 hours'),
  ('outbound'::direction, 'La varilla se maneja desde 25 toneladas, máximo 2 calibres por pedido. ¿Cuáles te interesan?', 'seed-demo-m-004b', now() - interval '2 days 2 hours 40 minutes'),
  ('inbound'::direction, '3/8 y 1/2, unas 30 toneladas para García', 'seed-demo-m-004c', now() - interval '2 days 2 hours'),
  ('outbound'::direction, 'Perfecto, cabe en un camión y son dos calibres. ¿Nombre, correo y cuándo la ocuparías?', 'seed-demo-m-004d', now() - interval '2 days 1 hour 40 minutes'),
  ('inbound'::direction, 'Aceros y Estructuras Peña, jpena@aepena.com, en dos semanas. Me pueden hablar después de las 4', 'seed-demo-m-004e', now() - interval '2 days')
) AS msgs(d, b, m, t);

-- 5. Escalada: tubería urgente
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, user_email, status, score,
    score_breakdown, qualification_source, qualification_reason, qualified_at,
    handed_off_at, product_interest, lead_summary, budget, timeline, preferred_contact_time,
    chatwoot_conversation_id, created_at, updated_at
  ) VALUES (
    'whatsapp', 'seed-demo-wa-005', 'Taller Industrial Ramos', '+52 81 1770 2288',
    'compras@talleramos.mx', 'handed_off', 16,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: tubería"},{"name":"budget_mentioned","points":3,"matched":true,"evidence":"keyword: toneladas, amount: 8"},{"name":"urgency_signaled","points":2,"matched":true,"evidence":"keyword: urgente"},{"name":"decision_intent","points":4,"matched":true,"evidence":"keyword: quiero cotizar"},{"name":"multiple_messages","points":1,"matched":true,"evidence":"user messages: 4"},{"name":"requested_human","points":5,"matched":true,"evidence":"keyword: asesor"}]}'::json,
    'chatwoot_agent', 'Pidió hablar con ventas por tubería urgente',
    now() - interval '6 hours', now() - interval '5 hours 40 minutes',
    'Tubería industrial negra',
    'Cédula no: tubo comercial negro 2" calibre 14, largos de 6 m. Planta en Santa Catarina.',
    '8 toneladas', 'Urgente, esta semana', 'Hoy en la tarde',
    91005,
    now() - interval '8 hours', now() - interval '5 hours'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Necesito cotizar tubería industrial, es urgente', 'seed-demo-m-005a', now() - interval '8 hours'),
  ('outbound'::direction, 'Manejamos tubería de acero negro comercial hasta 3", no cédula ni estructural. ¿Diámetro, calibre y toneladas?', 'seed-demo-m-005b', now() - interval '7 hours 40 minutes'),
  ('inbound'::direction, '2 pulgadas calibre 14, 8 toneladas, largos de 6 metros. Para esta semana', 'seed-demo-m-005c', now() - interval '7 hours'),
  ('outbound'::direction, 'Esa medida está en catálogo. ¿A nombre de quién y cómo te contactamos?', 'seed-demo-m-005d', now() - interval '6 hours 30 minutes'),
  ('inbound'::direction, 'Taller Industrial Ramos, compras@talleramos.mx. Quiero hablar con un asesor hoy en la tarde', 'seed-demo-m-005e', now() - interval '6 hours'),
  ('outbound'::direction, 'Te paso con el equipo de ventas. En un momento te atienden por este mismo chat.', 'seed-demo-m-005f', now() - interval '5 hours 40 minutes')
) AS msgs(d, b, m, t);

-- 6. Escalada con respuesta humana: alambre
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, user_email, status, score,
    score_breakdown, qualification_source, qualification_reason, qualified_at,
    handed_off_at, human_replied_at, product_interest, lead_summary, budget, timeline,
    preferred_contact_time, chatwoot_conversation_id, created_at, updated_at
  ) VALUES (
    'instagram', 'seed-demo-ig-006', 'Alambres del Norte', '+52 81 2099 6612',
    'ventas@alambresnorte.mx', 'handed_off', 14,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: alambre"},{"name":"budget_mentioned","points":3,"matched":true,"evidence":"keyword: toneladas, amount: 5"},{"name":"decision_intent","points":4,"matched":true,"evidence":"keyword: quiero comprar"},{"name":"requested_human","points":5,"matched":true,"evidence":"keyword: vendedor"}]}'::json,
    'meta_agent', 'Cliente pidió vendedor para alambre galvanizado',
    now() - interval '3 days', now() - interval '3 days' + interval '20 minutes',
    now() - interval '3 days' + interval '45 minutes',
    'Alambre galvanizado bajo carbono',
    'Reventa. Calibre 12, mínimo cubierto (5 ton). Recogen en planta.',
    '5 toneladas', 'La próxima semana', 'Cualquier hora hábil',
    91006,
    now() - interval '3 days 1 hour', now() - interval '3 days' + interval '50 minutes'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Quiero comprar alambre galvanizado calibre 12, 5 toneladas', 'seed-demo-m-006a', now() - interval '3 days 1 hour'),
  ('outbound'::direction, 'El mínimo de alambre galvanizado es 3 toneladas, así que 5 entran. ¿Lo recogen o hay que enviar?', 'seed-demo-m-006b', now() - interval '3 days 40 minutes'),
  ('inbound'::direction, 'Lo recogemos. ¿Me puede atender un vendedor?', 'seed-demo-m-006c', now() - interval '3 days 20 minutes'),
  ('outbound'::direction, 'Claro, te comunico con ventas.', 'seed-demo-m-006d', now() - interval '3 days' + interval '10 minutes'),
  ('outbound'::direction, 'Hola, soy Andrea de ventas GIA. Te armo la cotización de 5 ton calibre 12 para recolección. ¿Me confirmas razón social?', 'seed-demo-m-006e', now() - interval '3 days' + interval '45 minutes')
) AS msgs(d, b, m, t);

-- 7. Cerrada: pidió inoxidable (no se vende)
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, status, score,
    score_breakdown, qualification_source, product_interest,
    chatwoot_conversation_id, resolved_at, created_at, updated_at
  ) VALUES (
    'whatsapp', 'seed-demo-wa-007', 'Carlos Medina', '+52 81 1002 7781',
    'closed', 2,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: acero"}]}'::json,
    'none', 'Inoxidable 304',
    91007, now() - interval '4 days',
    now() - interval '4 days 2 hours', now() - interval '4 days'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, '¿Tienen lámina de acero inoxidable 304?', 'seed-demo-m-007a', now() - interval '4 days 2 hours'),
  ('outbound'::direction, 'No manejamos inoxidable (304, 316 ni 430). Si te sirve galvanizado, galvanneal o pintro te puedo orientar.', 'seed-demo-m-007b', now() - interval '4 days 1 hour 40 minutes'),
  ('inbound'::direction, 'No, gracias, lo necesito inoxidable', 'seed-demo-m-007c', now() - interval '4 days 1 hour')
) AS msgs(d, b, m, t);

-- 8. Calificada Instagram: acanalado R-101
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, user_email, status, score,
    score_breakdown, qualification_source, qualification_reason, qualified_at,
    product_interest, lead_summary, budget, timeline, preferred_contact_time,
    chatwoot_conversation_id, created_at, updated_at
  ) VALUES (
    'instagram', 'seed-demo-ig-008', 'Naves Industriales Regio', '+52 81 8333 9090',
    'proyectos@navesregio.com', 'qualified', 11,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: acanalado"},{"name":"budget_mentioned","points":3,"matched":true,"evidence":"keyword: toneladas, amount: 18"},{"name":"urgency_signaled","points":2,"matched":true,"evidence":"keyword: este mes"},{"name":"decision_intent","points":4,"matched":true,"evidence":"keyword: envíen cotización"}]}'::json,
    'chatwoot_agent', 'Cotización de lámina acanalada R-101 pintro',
    now() - interval '5 days',
    'Acanalado R-101 pintro',
    'Cubierta de nave en Escobedo. Largo especial 8.20 m, color blanco. Incluir flete.',
    '18 toneladas', 'Entrega este mes', 'Lunes a viernes 10 a 14',
    91008,
    now() - interval '5 days 4 hours', now() - interval '5 days'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Buenas, envíen cotización de acanalado R-101 pintro blanco', 'seed-demo-m-008a', now() - interval '5 days 4 hours'),
  ('outbound'::direction, 'Fabricamos R-101 galvanizado o pintro, largo estándar o especial. ¿Metros lineales o toneladas, y el largo de la pieza?', 'seed-demo-m-008b', now() - interval '5 days 3 hours 30 minutes'),
  ('inbound'::direction, 'Unas 18 toneladas, largo especial de 8.20 m, para una nave en Escobedo este mes', 'seed-demo-m-008c', now() - interval '5 days 2 hours'),
  ('outbound'::direction, 'Anotado. ¿Razón social y horario para que ventas te llame?', 'seed-demo-m-008d', now() - interval '5 days 1 hour'),
  ('inbound'::direction, 'Naves Industriales Regio, proyectos@navesregio.com, de 10 a 2', 'seed-demo-m-008e', now() - interval '5 days')
) AS msgs(d, b, m, t);

-- 9. Activa: solo horario y ubicación
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, status, score,
    score_breakdown, qualification_source, chatwoot_conversation_id,
    created_at, updated_at
  ) VALUES (
    'messenger', 'seed-demo-ms-009', 'Sofía Garza', '+52 81 1455 0102',
    'active', 0,
    '{"signals":[]}'::json, 'none', 91009,
    now() - interval '40 minutes', now() - interval '30 minutes'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Hola, ¿cuál es su horario y dónde están?', 'seed-demo-m-009a', now() - interval '40 minutes'),
  ('outbound'::direction, 'Atendemos en horario de oficina en planta, Monterrey. ¿Buscas algún material en específico?', 'seed-demo-m-009b', now() - interval '30 minutes')
) AS msgs(d, b, m, t);

-- 10. Escalada: ángulo camero
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, user_email, status, score,
    score_breakdown, qualification_source, qualification_reason, qualified_at,
    handed_off_at, product_interest, lead_summary, budget, timeline, preferred_contact_time,
    chatwoot_conversation_id, created_at, updated_at
  ) VALUES (
    'whatsapp', 'seed-demo-wa-010', 'Estructuras Camargo', '+52 81 1900 3344',
    'ing.camargo@estructurascgo.com', 'handed_off', 13,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: material"},{"name":"budget_mentioned","points":3,"matched":true,"evidence":"keyword: toneladas, amount: 18"},{"name":"decision_intent","points":4,"matched":true,"evidence":"keyword: quiero cotizar"},{"name":"requested_human","points":5,"matched":true,"evidence":"keyword: ejecutivo"}]}'::json,
    'chatwoot_agent', 'Fabricación de ángulo camero por encima del mínimo',
    now() - interval '8 days', now() - interval '8 days' + interval '30 minutes',
    'Ángulo camero',
    'Pedido de fabricación 2×2×1/8, 18 toneladas. Proyecto de racks en Guadalupe.',
    '18 toneladas', 'En 3 semanas', 'Mañana temprano',
    91010,
    now() - interval '8 days 5 hours', now() - interval '8 days' + interval '30 minutes'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Quiero cotizar ángulo camero 2x2 de 1/8, unas 18 toneladas', 'seed-demo-m-010a', now() - interval '8 days 5 hours'),
  ('outbound'::direction, 'El ángulo camero se fabrica con mínimo de 15 toneladas. 18 entran. No manejamos ángulo laminado. ¿Es para fabricación bajo pedido?', 'seed-demo-m-010b', now() - interval '8 days 4 hours'),
  ('inbound'::direction, 'Sí, fabricación. Proyecto en Guadalupe, lo ocupamos en 3 semanas. Que me marque un ejecutivo mañana temprano: ing.camargo@estructurascgo.com', 'seed-demo-m-010c', now() - interval '8 days 3 hours'),
  ('outbound'::direction, 'Listo, dejo el caso con ventas para que te contacten mañana.', 'seed-demo-m-010d', now() - interval '8 days' + interval '30 minutes')
) AS msgs(d, b, m, t);

-- 11. Calificada y resuelta en Chatwoot: rollo HRPO
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, user_email, status, score,
    score_breakdown, qualification_source, qualification_reason, qualified_at,
    product_interest, lead_summary, budget, timeline, preferred_contact_time,
    chatwoot_conversation_id, resolved_at, created_at, updated_at
  ) VALUES (
    'whatsapp', 'seed-demo-wa-011', 'Troquelados Regiomontanos', '+52 81 8120 5566',
    'abastos@troqueladosregio.mx', 'qualified', 12,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: rollo"},{"name":"budget_mentioned","points":3,"matched":true,"evidence":"keyword: toneladas, amount: 40"},{"name":"urgency_signaled","points":2,"matched":true,"evidence":"keyword: este mes"},{"name":"decision_intent","points":4,"matched":true,"evidence":"keyword: quiero cotizar"},{"name":"multiple_messages","points":1,"matched":true,"evidence":"user messages: 3"}]}'::json,
    'chatwoot_agent', 'Rolled HRPO para troquelado, pedido recurrente',
    now() - interval '10 days',
    'Rollo HRPO',
    'Consumo mensual. Ancho 48", calibre 14, decapado y aceitado. Entrega en planta San Nicolás.',
    '40 toneladas', 'Primera entrega este mes', 'Jueves por la mañana',
    91011, now() - interval '9 days',
    now() - interval '10 days 6 hours', now() - interval '9 days'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Quiero cotizar rollo HRPO calibre 14, ancho 48 pulgadas', 'seed-demo-m-011a', now() - interval '10 days 6 hours'),
  ('outbound'::direction, 'HRPO en rollo sí lo manejamos. ¿Tonelaje y si requieren corte a hoja o el rollo completo?', 'seed-demo-m-011b', now() - interval '10 days 5 hours'),
  ('inbound'::direction, '40 toneladas de rollo completo, consumo mensual, entrega en San Nicolás este mes', 'seed-demo-m-011c', now() - interval '10 days 4 hours'),
  ('outbound'::direction, 'Registro la propuesta. Ventas te contacta el jueves en la mañana.', 'seed-demo-m-011d', now() - interval '10 days 3 hours'),
  ('inbound'::direction, 'Gracias, abastos@troqueladosregio.mx', 'seed-demo-m-011e', now() - interval '10 days')
) AS msgs(d, b, m, t);

-- 12. Cerrada: menudeo por debajo del mínimo
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, status, score,
    score_breakdown, qualification_source, qualification_reason, product_interest,
    lead_summary, budget, chatwoot_conversation_id, resolved_at,
    created_at, updated_at
  ) VALUES (
    'instagram', 'seed-demo-ig-012', 'Ferretería La Esquina', '+52 81 1666 4300',
    'closed', 5,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: lámina"},{"name":"budget_mentioned","points":3,"matched":true,"evidence":"keyword: cantidad, amount: 4"}]}'::json,
    'none', 'Menudeo por debajo del mínimo de mayoreo',
    'Lámina galvanizada',
    'Pidió 4 hojas para mostrador. Se explicó que no hay menudeo.',
    '4 hojas',
    91012, now() - interval '6 days',
    now() - interval '6 days 3 hours', now() - interval '6 days'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, '¿Me venden 4 hojas de lámina galvanizada calibre 26?', 'seed-demo-m-012a', now() - interval '6 days 3 hours'),
  ('outbound'::direction, 'Vendemos solo mayoreo, no mostrador ni menudeo. Para lámina el pedido va por toneladas. ¿Tienes un volumen mayor?', 'seed-demo-m-012b', now() - interval '6 days 2 hours 30 minutes'),
  ('inbound'::direction, 'No, solo esas 4 para un cliente del mostrador', 'seed-demo-m-012c', now() - interval '6 days 2 hours'),
  ('outbound'::direction, 'En ese caso no te podemos surtir. Si más adelante juntas un pedido de mayoreo, con gusto te cotizamos.', 'seed-demo-m-012d', now() - interval '6 days')
) AS msgs(d, b, m, t);

-- 13. Activa: deck 25, todavía sin datos de contacto completos
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, status, score,
    score_breakdown, qualification_source, product_interest,
    chatwoot_conversation_id, created_at, updated_at
  ) VALUES (
    'whatsapp', 'seed-demo-wa-013', 'Ing. Patricia Solís', '+52 81 2004 1188',
    'active', 6,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: deck"},{"name":"budget_mentioned","points":3,"matched":true,"evidence":"keyword: toneladas, amount: 10"},{"name":"multiple_messages","points":1,"matched":true,"evidence":"user messages: 3"}]}'::json,
    'none', 'Losacero Deck 25',
    91013,
    now() - interval '90 minutes', now() - interval '25 minutes'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Hola, ¿fabrican losacero deck 25?', 'seed-demo-m-013a', now() - interval '90 minutes'),
  ('outbound'::direction, 'Sí, Deck 25 en galvanizado o pintro, largo estándar o especial. ¿Calibre, largo y toneladas?', 'seed-demo-m-013b', now() - interval '80 minutes'),
  ('inbound'::direction, 'Galvanizado, calibre 22, piezas de 6 m. Como 10 toneladas para un entrepiso', 'seed-demo-m-013c', now() - interval '50 minutes'),
  ('outbound'::direction, '10 toneladas de Deck 25 galvanizado calibre 22 entran en fabricación. ¿Me compartes empresa, correo y para cuándo lo ocupas?', 'seed-demo-m-013d', now() - interval '25 minutes')
) AS msgs(d, b, m, t);

-- 14. Calificada: cinta CR para corte
WITH c AS (
  INSERT INTO conversations (
    channel, external_user_id, user_name, user_phone, user_email, status, score,
    score_breakdown, qualification_source, qualification_reason, qualified_at,
    product_interest, lead_summary, budget, timeline, preferred_contact_time,
    chatwoot_conversation_id, created_at, updated_at
  ) VALUES (
    'messenger', 'seed-demo-ms-014', 'Cintas y Flejes Delta', '+52 81 8340 7721',
    'logistica@cintasdelta.mx', 'qualified', 9,
    '{"signals":[{"name":"product_mentioned","points":2,"matched":true,"evidence":"keyword: cinta"},{"name":"budget_mentioned","points":3,"matched":true,"evidence":"keyword: toneladas, amount: 15"},{"name":"decision_intent","points":4,"matched":true,"evidence":"keyword: me interesa"}]}'::json,
    'local_score', 'Qualified by local score',
    now() - interval '12 hours',
    'Cinta CR',
    'Corte a cinta de rollo CR calibre 20, anchos de 50 y 80 mm. Recogen en planta.',
    '15 toneladas', 'Quincena siguiente', 'Mediodía',
    91014,
    now() - interval '14 hours', now() - interval '12 hours'
  ) RETURNING id
)
INSERT INTO messages (conversation_id, direction, body, raw_payload, external_message_id, created_at)
SELECT id, d, b, '{}'::json, m, t FROM c, (VALUES
  ('inbound'::direction, 'Me interesa cinta de acero CR, corte a 50 y 80 mm', 'seed-demo-m-014a', now() - interval '14 hours'),
  ('outbound'::direction, 'Hacemos corte a cinta. ¿Calibre, toneladas y si el material es CR, galvanizado u otro?', 'seed-demo-m-014b', now() - interval '13 hours 30 minutes'),
  ('inbound'::direction, 'CR calibre 20, 15 toneladas. Lo recogemos la quincena que entra. Cintas y Flejes Delta, logistica@cintasdelta.mx', 'seed-demo-m-014c', now() - interval '12 hours')
) AS msgs(d, b, m, t);
