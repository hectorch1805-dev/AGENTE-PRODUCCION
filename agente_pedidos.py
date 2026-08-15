import os
import requests
from datetime import datetime, timezone, timedelta
from anthropic import Anthropic

HUBSPOT_TOKEN     = os.environ["HUBSPOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CALLMEBOT_PHONE   = os.environ["CALLMEBOT_PHONE"]
CALLMEBOT_APIKEY  = os.environ["CALLMEBOT_APIKEY"]
# Link publico de tu dashboard (GitHub Pages). Actualiza esto cuando
# actives Pages en tu repositorio, con tu URL real.
URL_DASHBOARD = "https://hectorch1805-dev.github.io/AGENTE-PRODUCCION/"

headers = {"Authorization": f"Bearer {HUBSPOT_TOKEN}",
           "Content-Type": "application/json"}
base = "https://api.hubapi.com"
client = Anthropic(api_key=ANTHROPIC_API_KEY)
hoy_dt = datetime.now(timezone(timedelta(hours=-5)))
hoy = hoy_dt.strftime("%Y-%m-%d")


def leer_etapas(tipo_objeto):
    """Lee las etapas de un pipeline (deals o tickets) y las traduce
    de codigo a nombre real, sin importar el pipeline al que pertenezcan."""
    r = requests.get(f"{base}/crm/v3/pipelines/{tipo_objeto}", headers=headers)
    datos = r.json()
    etapas = {}
    for pipeline in datos.get("results", []):
        for etapa in pipeline.get("stages", []):
            etapas[etapa["id"]] = etapa["label"]
    return etapas


def enviar_whatsapp(texto):
    envio = requests.get("https://api.callmebot.com/whatsapp.php", params={
        "phone": CALLMEBOT_PHONE,
        "text": texto,
        "apikey": CALLMEBOT_APIKEY,
    })
    print("Envio a WhatsApp:", envio.status_code, "-", envio.text[:200])


def pedir_resumen_a_claude(instrucciones):
    respuesta = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": instrucciones}],
    )
    return respuesta.content[0].text


def texto_a_html(texto):
    """Convierte el texto de Claude (con **negritas**, ## titulos y
    guiones) a HTML simple, listo para mostrar en la pagina."""
    html = []
    dentro_lista = False
    for linea in texto.strip().split("\n"):
        linea = linea.strip()
        if not linea:
            if dentro_lista:
                html.append("</ul>")
                dentro_lista = False
            continue
        # negritas **texto**
        while "**" in linea:
            linea = linea.replace("**", "<strong>", 1)
            linea = linea.replace("**", "</strong>", 1)
        if linea.startswith("##"):
            if dentro_lista:
                html.append("</ul>")
                dentro_lista = False
            html.append(f"<h3>{linea.lstrip('#').strip()}</h3>")
        elif linea.startswith("-"):
            if not dentro_lista:
                html.append("<ul>")
                dentro_lista = True
            html.append(f"<li>{linea[1:].strip()}</li>")
        else:
            if dentro_lista:
                html.append("</ul>")
                dentro_lista = False
            html.append(f"<p>{linea}</p>")
    if dentro_lista:
        html.append("</ul>")
    return "\n".join(html)


# ===================================================================
# RONDA 1: PEDIDOS (deals)
# ===================================================================
etapas_deals = leer_etapas("deals")

cuerpo = {
    "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "DESCENDING"}],
    "properties": ["dealname", "dealstage", "amount", "closedate"],
    "limit": 20,
}
pedidos = requests.post(f"{base}/crm/v3/objects/deals/search",
                        headers=headers, json=cuerpo).json()["results"]

lineas = []
for pedido in pedidos:
    p = pedido["properties"]
    etapa = etapas_deals.get(p.get("dealstage"), "(etapa sin identificar)")
    lineas.append(
        f"- {p.get('dealname') or '(sin nombre)'} | "
        f"Etapa: {etapa} | Monto: {p.get('amount') or '0'} | "
        f"Cierra: {(p.get('closedate') or 'sin fecha')[:10]}"
    )
texto_pedidos = "\n".join(lineas)

INSTRUCCIONES_PEDIDOS = f"""
Hoy es {hoy}. Eres el asistente de pedidos de una imprenta.
Revisa la lista de pedidos y escribe un resumen BREVE y claro para el dueño,
en español, con este formato:

1) 🔴 Requieren acción hoy: pedidos vencidos o que cierran hoy y que siguen
   en etapas de producción (aún no entregados). Explica por qué en pocas palabras.
2) 🟡 Ojo esta semana: pedidos grandes atascados en etapas tempranas, o que
   cierran en los próximos 2-3 días.
3) 🟢 Una línea final tranquilizadora sobre el resto.

Reglas estrictas:
- Sé concreto, usa los nombres de los pedidos y no inventes datos.
- Si un pedido no tiene fecha, no lo trates como vencido.
- NUNCA muestres codigos ni numeros de etapa internos. Usa SIEMPRE el nombre
  de etapa tal cual aparece en el texto de cada pedido.

PEDIDOS:
""" + texto_pedidos

resumen_pedidos = pedir_resumen_a_claude(INSTRUCCIONES_PEDIDOS)
print("=== RESUMEN DE PEDIDOS ===")
print(resumen_pedidos)


# ===================================================================
# RONDA 2: TICKETS + seguimiento de calidad (basado en el informe)
# ===================================================================
etapas_tickets = leer_etapas("tickets")

cuerpo_tickets = {
    "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "DESCENDING"}],
    "properties": ["subject", "hs_pipeline_stage", "hs_ticket_priority",
                   "createdate", "closed_date", "source_type"],
    "limit": 100,
}
respuesta_tickets = requests.post(f"{base}/crm/v3/objects/tickets/search",
                                  headers=headers, json=cuerpo_tickets)
datos_tickets = respuesta_tickets.json()
if "results" not in datos_tickets:
    print("ADVERTENCIA: no se pudo leer la lista de tickets de HubSpot.")
    print("Codigo de respuesta:", respuesta_tickets.status_code)
    print("Respuesta completa:", respuesta_tickets.text[:1500])
tickets = datos_tickets.get("results", [])

lineas_tickets = []
conteo_etapas = {}
conteo_prioridad = {}
conteo_canal = {}
total = len(tickets)
con_cierre_correcto = 0
con_fecha_futura = 0

for ticket in tickets:
    t = ticket["properties"]
    codigo_etapa = t.get("hs_pipeline_stage")
    etapa = etapas_tickets.get(codigo_etapa, "(etapa sin identificar)")
    prioridad = t.get("hs_ticket_priority") or "SIN ASIGNAR"
    canal = t.get("source_type") or "SIN CANAL"

    conteo_etapas[etapa] = conteo_etapas.get(etapa, 0) + 1
    conteo_prioridad[prioridad] = conteo_prioridad.get(prioridad, 0) + 1
    conteo_canal[canal] = conteo_canal.get(canal, 0) + 1

    if etapa.upper() == "PEDIDO FINALIZADO":
        con_cierre_correcto += 1

    fecha_cierre = t.get("closed_date")
    if fecha_cierre:
        try:
            fc = datetime.fromisoformat(fecha_cierre.replace("Z", "+00:00"))
            if fc > hoy_dt:
                con_fecha_futura += 1
        except ValueError:
            pass

    lineas_tickets.append(
        f"- {t.get('subject') or '(sin asunto)'} | "
        f"Etapa: {etapa} | Prioridad: {prioridad} | "
        f"Creado: {(t.get('createdate') or 'sin fecha')[:10]}"
    )
texto_tickets = "\n".join(lineas_tickets[:20])  # los 20 mas recientes para el texto

pct_cierre_correcto = round(100 * con_cierre_correcto / total, 1) if total else 0
pct_fecha_futura = round(100 * con_fecha_futura / total, 1) if total else 0
llamadas = conteo_canal.get("PHONE", 0)

INSTRUCCIONES_TICKETS = f"""
Hoy es {hoy}. Eres el asistente de soporte de una imprenta.
Revisa la lista de tickets recientes y escribe un resumen BREVE y claro
para el dueño, en español, con este formato:

1) 🔴 Prioridad alta o urgente: explica por qué en pocas palabras.
2) 🟡 En proceso, sin urgencia inmediata.
3) 🟢 Una línea final tranquilizadora sobre el resto.

Reglas estrictas:
- Sé concreto, usa los asuntos de los tickets y no inventes datos.
- NUNCA muestres codigos ni numeros de etapa internos. Usa SIEMPRE el nombre
  de etapa tal cual aparece en el texto de cada ticket.

TICKETS RECIENTES:
""" + texto_tickets

resumen_tickets = pedir_resumen_a_claude(INSTRUCCIONES_TICKETS)
print("\n=== RESUMEN DE TICKETS ===")
print(resumen_tickets)
print(f"\nKPI cierre correcto: {pct_cierre_correcto}%  |  "
      f"KPI fecha futura: {pct_fecha_futura}%  |  Llamadas: {llamadas}")


# ===================================================================
# RONDA 3: REPORTE SEMANAL (solo se genera los viernes)
# ===================================================================
if True:  # PRUEBA TEMPORAL: forzado a generar siempre. Volver a "hoy_dt.weekday() == 4" despues.
    inicio_semana = (hoy_dt - timedelta(days=4)).replace(hour=0, minute=0, second=0, microsecond=0)
    inicio_mes = hoy_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def owners_por_id():
        """Trae los nombres del equipo para no mostrar solo IDs numericos."""
        r = requests.get(f"{base}/crm/v3/owners", headers=headers, params={"limit": 100})
        datos = r.json()
        if "results" not in datos:
            print("ADVERTENCIA: no se pudo leer la lista de miembros del equipo.")
            print("Respuesta:", r.status_code, "-", r.text[:500])
            return {}
        return {str(o["id"]): f"{o.get('firstName', '')} {o.get('lastName', '')}".strip()
                for o in datos["results"]}

    nombres_equipo = owners_por_id()

    # --- 1) Negocios creados esta semana (lunes a viernes) ---
    cuerpo_creados = {
        "filterGroups": [{"filters": [
            {"propertyName": "createdate", "operator": "GTE",
             "value": str(int(inicio_semana.timestamp() * 1000))},
        ]}],
        "properties": ["dealname"],
        "limit": 100,
    }
    creados = requests.post(f"{base}/crm/v3/objects/deals/search",
                            headers=headers, json=cuerpo_creados).json().get("results", [])
    total_creados = len(creados)

    # --- 2) Negocios pasados a produccion esta semana ---
    cuerpo_produccion = {
        "filterGroups": [{"filters": [
            {"propertyName": "fecha_confirmacion_produccion", "operator": "GTE",
             "value": str(int(inicio_semana.timestamp() * 1000))},
        ]}],
        "properties": ["dealname"],
        "limit": 100,
    }
    pasaron_produccion = requests.post(f"{base}/crm/v3/objects/deals/search",
                            headers=headers, json=cuerpo_produccion).json().get("results", [])
    total_produccion = len(pasaron_produccion)

    # --- 3) Cierre dentro del mes actual en Produccion/Factura/Ganado, por cliente ---
    cuerpo_mes = {
        "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "DESCENDING"}],
        "properties": ["dealname", "dealstage", "amount", "closedate"],
        "limit": 100,
    }
    todos_deals = requests.post(f"{base}/crm/v3/objects/deals/search",
                                headers=headers, json=cuerpo_mes).json().get("results", [])

    acumulado_por_cliente = {}
    for d in todos_deals:
        p = d["properties"]
        etapa = etapas_deals.get(p.get("dealstage"), "").upper()
        if not any(clave in etapa for clave in ["PRODUCCION", "FACTURA", "GANADO"]):
            continue
        cierre = p.get("closedate")
        if not cierre:
            continue
        try:
            fc = datetime.fromisoformat(cierre.replace("Z", "+00:00"))
        except ValueError:
            continue
        if fc < inicio_mes:
            continue
        nombre = p.get("dealname") or "(sin nombre)"
        # Se asume el formato CLIENTE - PRODUCTO para identificar al cliente
        cliente = nombre.split(" - ")[0].strip().upper()
        monto = float(p.get("amount") or 0)
        acumulado_por_cliente[cliente] = acumulado_por_cliente.get(cliente, 0) + monto

    # --- 4) Tickets por miembro del equipo, esta semana ---
    cuerpo_tickets_semana = {
        "filterGroups": [{"filters": [
            {"propertyName": "createdate", "operator": "GTE",
             "value": str(int(inicio_semana.timestamp() * 1000))},
        ]}],
        "properties": ["hubspot_owner_id", "hs_ticket_priority"],
        "limit": 100,
    }
    tickets_semana = requests.post(f"{base}/crm/v3/objects/tickets/search",
                        headers=headers, json=cuerpo_tickets_semana).json().get("results", [])

    tickets_por_persona = {}
    alta_urgente_semana = 0
    for t in tickets_semana:
        p = t["properties"]
        owner_id = p.get("hubspot_owner_id")
        nombre = nombres_equipo.get(owner_id, "Sin asignar")
        tickets_por_persona[nombre] = tickets_por_persona.get(nombre, 0) + 1
        if (p.get("hs_ticket_priority") or "").upper() in ("HIGH", "URGENT"):
            alta_urgente_semana += 1
    pct_alta_urgente_semana = (round(100 * alta_urgente_semana / len(tickets_semana), 1)
                                if tickets_semana else 0)

    # --- Extra: tickets creados vs cerrados esta semana ---
    cerrados_semana = sum(
        1 for t in tickets_semana
        if etapas_tickets.get(t["properties"].get("hs_pipeline_stage"), "").upper() == "PEDIDO FINALIZADO"
    )

    # --- Extra: negocios estancados (+10 dias sin moverse, no cerrados) ---
    limite_estancado = hoy_dt - timedelta(days=10)
    estancados = []
    cuerpo_estancados = {
        "filterGroups": [{"filters": [
            {"propertyName": "hs_lastmodifieddate", "operator": "LTE",
             "value": str(int(limite_estancado.timestamp() * 1000))},
        ]}],
        "properties": ["dealname", "dealstage", "hs_lastmodifieddate"],
        "limit": 50,
        "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}],
    }
    posibles_estancados = requests.post(f"{base}/crm/v3/objects/deals/search",
                        headers=headers, json=cuerpo_estancados).json().get("results", [])
    for d in posibles_estancados:
        p = d["properties"]
        etapa = etapas_deals.get(p.get("dealstage"), "")
        if "GANADO" in etapa.upper() or "PERDIDO" in etapa.upper():
            continue
        estancados.append((p.get("dealname") or "(sin nombre)", etapa,
                           (p.get("hs_lastmodifieddate") or "")[:10]))

    # --- Armar el HTML del reporte semanal ---
    filas_clientes = "".join(
        f"<tr><td>{c}</td><td>S/ {m:,.2f}</td></tr>\n"
        for c, m in sorted(acumulado_por_cliente.items(), key=lambda x: -x[1])
    )
    filas_equipo = "".join(
        f"<tr><td>{persona}</td><td>{cant}</td></tr>\n"
        for persona, cant in sorted(tickets_por_persona.items(), key=lambda x: -x[1])
    )
    filas_estancados = "".join(
        f"<tr><td>{nom}</td><td>{et}</td><td>{fecha}</td></tr>\n"
        for nom, et, fecha in estancados[:15]
    ) or "<tr><td colspan=3>Ninguno detectado</td></tr>"

    html_semanal = f"""
<h2 id="semanal">📅 Reporte Semanal — Semana del {inicio_semana.strftime('%d/%m')} al {hoy_dt.strftime('%d/%m')}</h2>

<div class="kpis">
  <div class="kpi"><div class="valor">{total_creados}</div><div class="label">Negocios creados<br>esta semana</div></div>
  <div class="kpi"><div class="valor">{total_produccion}</div><div class="label">Pasaron a Producción<br>esta semana</div></div>
  <div class="kpi"><div class="valor">{len(tickets_semana)}</div><div class="label">Tickets creados<br>esta semana</div></div>
  <div class="kpi"><div class="valor">{cerrados_semana}</div><div class="label">Tickets cerrados<br>esta semana</div></div>
  <div class="kpi"><div class="valor {'rojo' if pct_alta_urgente_semana > 40 else 'verde'}">{pct_alta_urgente_semana}%</div><div class="label">Tickets Alta/Urgente<br>esta semana</div></div>
</div>

<div class="card">
<h3>Acumulado por cliente este mes (Producción / Factura / Ganado)</h3>
<table><tr><th>Cliente</th><th>Monto acumulado</th></tr>
{filas_clientes}
</table>
</div>

<div class="card">
<h3>Tickets por miembro del equipo (esta semana)</h3>
<table><tr><th>Persona</th><th>Tickets</th></tr>
{filas_equipo}
</table>
</div>

<div class="card">
<h3>⚠️ Negocios estancados (+10 días sin movimiento)</h3>
<table><tr><th>Negocio</th><th>Etapa</th><th>Última actividad</th></tr>
{filas_estancados}
</table>
</div>
"""
else:
    html_semanal = ""


# ===================================================================
# GENERAR EL DASHBOARD (pagina HTML) Y GUARDARLO
# ===================================================================
def filas_conteo(diccionario):
    filas = ""
    for clave, valor in sorted(diccionario.items(), key=lambda x: -x[1]):
        pct = round(100 * valor / total, 1) if total else 0
        filas += f"<tr><td>{clave}</td><td>{valor}</td><td>{pct}%</td></tr>\n"
    return filas


alerta_llamadas = (
    '<p class="alerta">⚠️ 0 llamadas registradas como ticket en este lote — '
    'revisar si se estan perdiendo pedidos por telefono.</p>'
    if llamadas == 0 else ""
)

html_final = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard de Pedidos y Tickets</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; background: #0f1115;
         color: #e6e6e6; margin: 0; padding: 24px; }}
  h1 {{ font-size: 20px; }}
  h2 {{ margin-top: 40px; border-bottom: 2px solid #333; padding-bottom: 8px; }}
  h3 {{ color: #9ecbff; }}
  .fecha {{ color: #888; font-size: 13px; margin-bottom: 24px; }}
  .card {{ background: #1a1d24; border-radius: 10px; padding: 18px; margin: 14px 0; }}
  .kpis {{ display: flex; gap: 14px; flex-wrap: wrap; }}
  .kpi {{ background: #1a1d24; border-radius: 10px; padding: 16px 20px; min-width: 160px; }}
  .kpi .valor {{ font-size: 28px; font-weight: bold; }}
  .kpi .label {{ font-size: 13px; color: #aaa; }}
  .rojo {{ color: #ff6b6b; }}
  .verde {{ color: #6bff95; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  td, th {{ padding: 6px 8px; border-bottom: 1px solid #2a2d34; text-align: left; }}
  ul {{ margin: 6px 0; padding-left: 20px; }}
  .alerta {{ background: #3a2323; border-left: 4px solid #ff6b6b; padding: 10px; border-radius: 6px; }}
</style>
</head>
<body>
<h1>📊 Dashboard — Pedidos y Tickets</h1>
<div class="fecha">Actualizado: {hoy_dt.strftime("%d/%m/%Y %H:%M")} (hora Perú)</div>

<h2 id="pedidos">📦 Pedidos</h2>
<div class="card">
{texto_a_html(resumen_pedidos)}
</div>

<h2 id="tickets">🎫 Tickets</h2>

<div class="kpis">
  <div class="kpi">
    <div class="valor {'verde' if pct_cierre_correcto >= 80 else 'rojo'}">{pct_cierre_correcto}%</div>
    <div class="label">Cierre correcto<br>(etapa = Pedido finalizado)</div>
  </div>
  <div class="kpi">
    <div class="valor {'verde' if pct_fecha_futura == 0 else 'rojo'}">{pct_fecha_futura}%</div>
    <div class="label">Con fecha de cierre<br>futura (inconsistente)</div>
  </div>
  <div class="kpi">
    <div class="valor">{total}</div>
    <div class="label">Tickets analizados<br>(mas recientes)</div>
  </div>
</div>

{alerta_llamadas}

<div class="card">
<h3>Resumen</h3>
{texto_a_html(resumen_tickets)}
</div>

<div class="card">
<h3>Por etapa</h3>
<table><tr><th>Etapa</th><th>Cantidad</th><th>%</th></tr>
{filas_conteo(conteo_etapas)}
</table>
</div>

<div class="card">
<h3>Por prioridad</h3>
<table><tr><th>Prioridad</th><th>Cantidad</th><th>%</th></tr>
{filas_conteo(conteo_prioridad)}
</table>
</div>

<div class="card">
<h3>Por canal</h3>
<table><tr><th>Canal</th><th>Cantidad</th><th>%</th></tr>
{filas_conteo(conteo_canal)}
</table>
</div>

{html_semanal}

</body>
</html>
"""

os.makedirs("docs", exist_ok=True)
with open("docs/index.html", "w", encoding="utf-8") as f:
    f.write(html_final)
print("\nDashboard guardado en docs/index.html")


# ===================================================================
# ENVIAR LOS DOS WHATSAPPS CON LINK AL DASHBOARD
# ===================================================================
enviar_whatsapp(f"📦 Reporte de pedidos de hoy ({hoy}). Mira el detalle: {URL_DASHBOARD}#pedidos")
enviar_whatsapp(f"🎫 Reporte de tickets de hoy ({hoy}). Cierre correcto: {pct_cierre_correcto}% | Ver detalle: {URL_DASHBOARD}#tickets")

if True:  # PRUEBA TEMPORAL: forzado a generar siempre. Volver a "hoy_dt.weekday() == 4" despues.
    enviar_whatsapp(
        f"📅 Reporte semanal ({hoy}). Negocios creados: {total_creados} | "
        f"Pasaron a Producción: {total_produccion} | "
        f"Tickets Alta/Urgente: {pct_alta_urgente_semana}% | "
        f"Ver detalle completo: {URL_DASHBOARD}#semanal"
    )
