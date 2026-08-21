# Business Info — agente GIA (Chatwoot)

Fuente: `agent_info/business_info.json` (seed a Postgres).

## business_description

Grupo Industrial Acerero, S.A. de C.V. (GIA), RFC GIA971119FV5, empresa 100% mexicana (antes UNIACERO) con más de 30 años en comercialización y transformación de acero. Centro de servicio en Francisco Villa No. 27, Col. Jardines de Xalostoc, C.P. 55330, Ecatepec de Morelos, Estado de México: 40,000 m², almacenamiento de 35,000 ton y capacidad de transformación de hasta 5,000 toneladas mensuales. Más de 200 colaboradores, transporte propio y maquinaria (niveladoras, cizallas, slitters, molinos de tubería, cortadoras y acanaladoras). Fabricamos lámina acanalada KR-18, R-101, R-72 y Steel Deck; comercializamos aceros planos (HR, HRPO, CR, galvanizada G60/G90, Galvanneal, electrogalvanizada, Ecogal/zintroalum, Pintro), tubería industrial de acero negro comercial, varilla y alambre. Certificación NMX-CC/ISO 9001 (en proceso IATF 16949), trazabilidad por número de lote y certificados de calidad vía vendedor. Operamos ventas spot/piso, desarrollo de producto y back-to-back; entregas DDP o FOB. Sitio: https://giacerero.com — Términos: https://giacerero.com/terminos-y-condiciones. Negocio de mayoreo industrial (no menudeo ni mostrador).

## purchase_info

Solo mayoreo. Pedido mínimo oficial: 1 tonelada por partida y 3 toneladas en total (varilla 25 ton / 1 camión máx. 2 calibres; ángulo camero 15 ton bajo fabricación; alambre 3 ton). El asesor cotiza por kilo + IVA (MXN o USD); el agente NUNCA da precios (ni por kilo, pieza, tonelada, rangos ni estimaciones). Lista de precios y cotización formal: solo el asesor humano. Mejoras por volumen y vigencia típica (1 día) las confirma el asesor. Antes de pasar a ventas se captura RFQ: material, calibre, acabado, medidas, tonelaje/piezas, ficha técnica si aplica, y si ya es cliente GIA (para canalizar con su vendedor). Medidas especiales sí se fabrican; el peso teórico es orientativo y rige la báscula de GIA. Cuando el prospecto pide cotización con volumen/urgencia/contacto, el agente debe usar el tool `create_lead` para registrar el lead calificado.

## payment_method

Solo transferencia o depósito a cuentas BBVA a nombre de GRUPO INDUSTRIAL ACERERO, S.A. DE C.V. (RFC GIA971119FV5). No manejamos efectivo ni venta de mostrador. Contado — medidas estándar: mínimo 80% con la orden de compra para iniciar producción y 20% contra factura; medidas especiales: 100% por adelantado. No sale camión sin el 100% cubierto (bloqueo por sistema). Los datos bancarios los envía ÚNICAMENTE el vendedor humano con el documento oficial actualizado; el agente NUNCA dicta CLABE ni cuentas por chat. Referencia de pago: solo los 7 últimos dígitos del folio de factura, sin diagonal ni espacios. Facturamos siempre (PDF/XML). Crédito: se inicia de contado; con 3 meses de compras continuas se arma historial para evaluación del Gerente de Crédito (ext. 158).

## delivery_and_shipping

Material en piso/spot: 3 a 4 días hábiles con anticipo. Fabricación/desarrollo especial: aprox. 25 a 30 días hábiles. Tolerancia de entrega ±10%; facturación sobre peso neto. Flete sin costo en zona metropolitana; envíos a toda la República (foráneo se cotiza); DDP o FOB. Entregas libres de maniobras (descarga con personal/montacargas del cliente). Antes de programar entrega se captura horario de recibo, si el punto está techado y ubicación exacta. Recolección en planta (preferida): carta membretada a C.P. Juan Manuel Toledo con datos de unidad, OC y operador (INE, licencia, seguro, EPP); horario L-V 9:00–16:00, Ecatepec.

## return_policy

GIA no otorga garantía ilimitada por la naturaleza del acero; toda reclamación la autoriza GIA tras inspección (el agente nunca acepta ni rechaza). Para reclamar se requieren 4 datos: lote del rollo, número de parte/código, cantidad sospechosa y defecto (muestra si no es visible). Rechazo aceptado: recolección en máximo 10 días y nota de crédito (no hay cambio físico de material). Garantía por óxido: con aceite 45 días desde embarque; pasivado sin aceite 30 días; seco / HRPO-CR secos sin garantía. Golpes, mojado o embalaje: notificar en máximo 48 horas con fotos y en presencia del operador. Diferencias de báscula < ±1.0% son normales (ASTM A700); mayores requieren certificado de calibración EMA. Términos: https://giacerero.com/terminos-y-condiciones.

## contact_info

- **email:** contacto@unigiasa.com.mx
- **hours_of_operation:** Atención comercial en horario laboral. Recolección en planta: lunes a viernes de 9:00 a 16:00. Conmutador: 55 5755 7009 / 55 5791 6725 (y extensiones publicadas). Fuera de horario puede enviarse mensaje; un asesor da seguimiento al retomar actividades.
- **address:** Francisco Villa No. 27, Col. Jardines de Xalostoc, C.P. 55330, Ecatepec de Morelos, Estado de México, México
