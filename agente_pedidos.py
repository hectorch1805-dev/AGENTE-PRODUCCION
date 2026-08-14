import os
import requests
from datetime import datetime, timezone, timedelta
from anthropic import Anthropic

# Las llaves llegan seguras desde los "secretos" de GitHub
HUBSPOT_TOKEN     = os.environ["HUBSPOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CALLMEBOT_PHONE   = os.environ["CALLMEBOT_PHONE"]
CALLMEBOT_APIKEY  = os.environ["CALLMEBOT_APIKEY"]

# ===== 1) LEER PEDIDOS DE HUBSPOT =====
headers = {"Authorization": f"Bearer {HUBSPOT_TOKEN}",
           "Content-Type": "application/json"}
base = "https://api.hubapi.com"
etapas = {op["value"]: op["label"] for op in
          requests.get(f"{base}/crm/v3/properties/deals/dealstage",
                       headers=headers).json()["options"]}
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
    etapa = etapas.get(p.get("dealstage"), p.get("dealstage"))
    lineas.append(
        f"- {p.get('dealname') or '(sin nombre)'} | "
        f"Etapa: {etapa} | Monto: {p.get('amount') or '0'} | "
        f"Cierra: {(p.get('closedate') or 'sin fecha')[:10]}"
    )
texto_pedidos = "\n".join(lineas)

# ===== 2) INSTRUCCIONES (edita a tu gusto) =====
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

Sé concreto, usa los nombres de los pedidos y no inventes datos.
Si un pedido no tiene fecha, no lo trates como vencido.
"""

# ===== 3) CLAUDE ARMA EL RESUMEN =====
client = Anthropic(api_key=ANTHROPIC_API_KEY)
respuesta = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=800,
    messages=[{"role": "user",
               "content": INSTRUCCIONES + "\n\nPEDIDOS:\n" + texto_pedidos}],
)
resumen = respuesta.content[0].text
print(resumen)

# ===== 4) ENVIAR A WHATSAPP =====
envio = requests.get("https://api.callmebot.com/whatsapp.php", params={
    "phone": CALLMEBOT_PHONE,
    "text": resumen,
    "apikey": CALLMEBOT_APIKEY,
})
print("\nEnvío a WhatsApp:", envio.status_code, "-", envio.text[:200])
