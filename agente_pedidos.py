import os
import requests
from datetime import datetime, timezone, timedelta
from anthropic import Anthropic

HUBSPOT_TOKEN     = os.environ["HUBSPOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CALLMEBOT_PHONE   = os.environ["CALLMEBOT_PHONE"]
CALLMEBOT_APIKEY  = os.environ["CALLMEBOT_APIKEY"]

headers = {"Authorization": f"Bearer {HUBSPOT_TOKEN}",
           "Content-Type": "application/json"}
base = "https://api.hubapi.com"

# Las etapas de negociacion viven en los "Pipelines", no en la propiedad
# dealstage directamente. Por eso leemos aqui, no en /properties/deals/dealstage.
respuesta_pipelines = requests.get(f"{base}/crm/v3/pipelines/deals",
                                   headers=headers)
datos_pipelines = respuesta_pipelines.json()
etapas = {}
for pipeline in datos_pipelines.get("results", []):
    for etapa in pipeline.get("stages", []):
        etapas[etapa["id"]] = etapa["label"]

if not etapas:
    print("ADVERTENCIA: no se pudo leer la lista de etapas de HubSpot.")
    print("Codigo de respuesta:", respuesta_pipelines.status_code)
    print("Respuesta completa:", respuesta_pipelines.text[:1500])

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
    codigo_etapa = p.get("dealstage")
    etapa = etapas.get(codigo_etapa, "(etapa sin identificar)")
    lineas.append(
        f"- {p.get('dealname') or '(sin nombre)'} | "
        f"Etapa: {etapa} | Monto: {p.get('amount') or '0'} | "
        f"Cierra: {(p.get('closedate') or 'sin fecha')[:10]}"
    )
texto_pedidos = "\n".join(lineas)

hoy = datetime.now(timezone(timedelta(hours=-5))).strftime("%Y-%m-%d")
INSTRUCCIONES = f"""
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
- NUNCA muestres codigos ni numeros de etapa internos (por ejemplo cosas
  como "65922067" o "closedwon"). Usa SIEMPRE el nombre de etapa tal cual
  aparece en el texto de cada pedido (ej. "Produccion", "Presupuesto").
  Si un pedido dice "(etapa sin identificar)", escribe exactamente esa
  frase, nunca un codigo.
"""

client = Anthropic(api_key=ANTHROPIC_API_KEY)
respuesta = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=800,
    messages=[{"role": "user",
               "content": INSTRUCCIONES + "\n\nPEDIDOS:\n" + texto_pedidos}],
)
resumen = respuesta.content[0].text
print(resumen)

envio = requests.get("https://api.callmebot.com/whatsapp.php", params={
    "phone": CALLMEBOT_PHONE,
    "text": resumen,
    "apikey": CALLMEBOT_APIKEY,
})
print("\nEnvío a WhatsApp:", envio.status_code, "-", envio.text[:200])
