"""El prompt del modelo de vision-lenguaje. Apartado 9.2.

"Prompt con contexto de planta: proceso normal de carga, zonas restringidas,
duracion tipica y criterios explicitos de severidad."

Un modelo que no sabe como es una carga normal no puede decir que algo no lo
fue. Describiria lo que ve, que es un camion y unos sacos, y eso el supervisor ya
lo sabe. Lo que hace util la respuesta es el contraste con lo esperado, y eso hay
que darselo.

Vive en su propio modulo por dos razones. La primera es que el apartado 9.2 pide
revisar el prompt cuando la concordancia con el supervisor baje del 85 %: si esta
repartido por el codigo, revisarlo es arqueologia. La segunda es que asi se puede
leer entero de una vez, que es la unica forma de saber que se le esta pidiendo a
un modelo.

Dos cosas que el prompt dice a proposito:

  - **No identifiques a nadie.** La RN-08 prohibe la identificacion facial y los
    datos biometricos. El modelo recibe imagenes con personas y hay que decirle
    explicitamente que hable de "un operario" y nunca de rasgos que permitan
    reconocerlo.
  - **Di cuando no sabes.** Un modelo que siempre encuentra algo sospechoso es
    inutil: manda a alguien a la rampa cada dia hasta que dejan de hacerle caso.
    Se le pide explicitamente que las cargas normales las llame normales.
"""
from __future__ import annotations

from app.config import Ajustes
from app.severidad import ALTA, BAJA, MEDIA

# El contrato que se le pide al modelo. Criterio 2 de HU-09: descripcion,
# severidad y evidencia observada.
ESQUEMA = """{
  "descripcion": "que se ve en las imagenes, en dos o tres frases",
  "severidad": "baja | media | alta",
  "evidencia": ["lo concreto que sostiene esa severidad, una frase por punto"],
  "confianza": 0.0
}"""


def sistema(ajustes: Ajustes) -> str:
    """El contexto de planta y las reglas. Lo que no cambia entre eventos."""
    return f"""Eres un analista de seguridad en el area de despacho de QUINOR
S.A.C., una empresa exportadora peruana. Revisas fotogramas del video de la
rampa de carga cuando el sistema detecta una discrepancia, y explicas al
supervisor que se ve, para que decida si baja a revisar el contenedor.

COMO ES UNA CARGA NORMAL
- Se cargan sacos de {ajustes.producto} a un contenedor, en la rampa.
- Un camion lleva del orden de {ajustes.sacos_por_camion} sacos.
- La carga dura unos {ajustes.duracion_tipica_min} minutos.
- Trabajan unos {ajustes.personas_habituales} operarios a la vez. Que pasen
  personas por delante de la camara y tapen sacos es normal.
- Los sacos van siempre hacia el camion. Un saco que sale de la zona de carga
  hacia fuera del camion no es parte del proceso.

CRITERIOS DE SEVERIDAD (regla RN-04 de la empresa)
- {ALTA}: diferencia de 2 sacos o mas, o sacos que salen de la zona de carga
  hacia fuera del camion.
- {MEDIA}: diferencia de 1 saco, o presencia de personal que no es la habitual.
- {BAJA}: el peso no cuadra pero el conteo de sacos si. Suele ser producto
  sustituido dentro de los sacos, o un error de bascula.

COMO RESPONDER
- Describe solo lo que se ve en las imagenes. Si los datos y las imagenes no
  concuerdan, dilo en lugar de inventar una explicacion.
- Una carga que parece normal se describe como normal. No busques algo
  sospechoso en cada evento: un aviso que salta siempre deja de leerse, y
  entonces el sistema no sirve para nada.
- Nunca describas rasgos fisicos, ropa, rostro ni nada que permita reconocer a
  una persona concreta. Di "un operario", "dos personas". Es una obligacion
  legal de la empresa (Ley 29733), no una preferencia de estilo.
- No acuses a nadie. Tu trabajo es describir y priorizar, no concluir.
- Responde unicamente con un objeto JSON valido, sin texto alrededor y sin
  bloques de codigo, con esta forma exacta:

{ESQUEMA}

- "confianza" va de 0 a 1 y es tu seguridad en la descripcion, no la gravedad.
- "evidencia" son observaciones concretas de las imagenes o de los datos. Si no
  tienes ninguna, deja la lista vacia en lugar de rellenarla."""


def datos_del_evento(contexto: dict) -> str:
    """Los datos estructurados que el apartado 9.2 manda enviar con las imagenes.

    Van como texto y no escondidos en el prompt de sistema porque cambian en cada
    evento, y porque asi el modelo puede contrastarlos con lo que ve.
    """
    lineas = [
        "DATOS DE ESTA CARGA (medidos por el sistema, no por ti):",
        f"- Orden de despacho: {contexto.get('numero_orden', 'desconocida')}",
        f"- Producto: {contexto.get('producto', 'no indicado')}",
        f"- Peso esperado: {contexto.get('peso_esperado_kg', '?')} kg",
        f"- Peso real en bascula: {contexto.get('peso_real_kg', '?')} kg",
        f"- Diferencia de peso: {contexto.get('diferencia_kg', '?')} kg "
        f"({contexto.get('diferencia_pct', '?')} %)",
    ]

    sacos = contexto.get("sacos_contados")
    esperados = contexto.get("sacos_esperados")
    if sacos is None:
        lineas.append("- Conteo de sacos: no se pudo analizar el video.")
    else:
        lineas.append(f"- Sacos contados en el video: {sacos} de {esperados} "
                      f"que decia la orden (diferencia "
                      f"{contexto.get('diferencia_sacos', '?')}).")
    if contexto.get("sacos_salientes"):
        lineas.append(f"- Sacos que SALIERON de la zona de carga: "
                      f"{contexto['sacos_salientes']}.")

    personas = contexto.get("personas_detectadas")
    if personas is not None:
        lineas.append(f"- Personas en la zona de carga: {personas}, "
                      f"como maximo {contexto.get('maximo_simultaneo', '?')} a "
                      f"la vez.")
    if contexto.get("permanencia_maxima_s"):
        lineas.append(f"- La que mas estuvo: "
                      f"{contexto['permanencia_maxima_s']:.0f} segundos.")
    if contexto.get("motivos_de_anomalia"):
        lineas.append(f"- El sistema marco la presencia de personal como no "
                      f"habitual por: {', '.join(contexto['motivos_de_anomalia'])}.")
    if contexto.get("duracion_del_clip_s"):
        lineas.append(f"- Duracion del clip: "
                      f"{contexto['duracion_del_clip_s']:.0f} segundos.")

    lineas.append("")
    lineas.append(
        "Las imagenes son los fotogramas que el sistema eligio por lo que "
        "ocurrio en ellos. Cada una viene con el motivo por el que se guardo.")
    return "\n".join(lineas)


def pie_de_imagen(clave: dict) -> str:
    """Lo que acompana a cada fotograma para que el modelo sepa que mira."""
    return (f"[segundo {clave.get('segundo', 0):.0f} del clip - "
            f"{clave.get('motivo', 'sin motivo')}] {clave.get('detalle', '')}")
