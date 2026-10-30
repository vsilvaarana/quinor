"""Estilo compartido de los bocetos a lapiz de QUINOR.

El trazo se dibuja en una capa propia y filtrada con una turbulencia SVG: asi la
linea tiembla como un lapiz y el texto de encima se queda nitido. Todo lo demas
es gris: un boceto discute que va en la pantalla y en que orden, no colores.
"""
from __future__ import annotations

CSS = """
:root{ --tinta:#4a4a4a; --tinta-suave:#8a8a8a; --papel:#fbfaf6; --relleno:#e8e6e0; }
*{box-sizing:border-box;}
body{
  margin:0; padding:34px 30px 44px;
  background:
    repeating-linear-gradient(0deg,#e9e7df 0 1px,transparent 1px 22px),
    repeating-linear-gradient(90deg,#e9e7df 0 1px,transparent 1px 22px);
  background-color:var(--papel);
  font-family:"Liberation Mono","DejaVu Sans Mono",monospace; color:var(--tinta);
}
.hoja{max-width:1400px; margin:0 auto; display:flex; gap:30px; align-items:flex-start;}
.cuerpo{flex:1; min-width:0; position:relative;}

.caja{position:relative; padding:14px 16px;}
.trazo{position:absolute; inset:0; border:2px solid var(--tinta); border-radius:4px;
       filter:url(#rugoso); pointer-events:none;}
.trazo.fino{border-width:1.4px; border-color:var(--tinta-suave);}
.trazo.doble{border-style:double; border-width:4px;}
.trazo.punteado{border-style:dashed; border-width:1.4px; border-color:var(--tinta-suave);}

.sello{position:absolute; top:-10px; right:0; transform:rotate(-4deg);
       font-size:13px; letter-spacing:3px; color:#9a4a3a; border:2px solid #9a4a3a;
       padding:5px 12px; border-radius:3px; filter:url(#rugoso);}
h1{font-size:17px; margin:0 0 4px; letter-spacing:1px;}
.sub{font-size:12px; color:var(--tinta-suave); margin-bottom:18px;}
.pie-hoja{margin-top:24px; font-size:11.5px; color:var(--tinta-suave); line-height:1.6;}

.fila{display:flex; gap:14px; margin-bottom:14px; align-items:stretch;}
.col{flex:1; min-width:0;}

.barra{height:9px; background:var(--relleno); border-radius:2px; margin:5px 0;}
.barra.corta{width:45%;} .barra.media{width:70%;} .barra.larga{width:92%;}

.etiqueta{font-size:11px; letter-spacing:1.5px; text-transform:uppercase;
          color:var(--tinta-suave); margin-bottom:6px;}
.cifra{font-size:23px; letter-spacing:-0.5px;}
.cifra small{font-size:12px; color:var(--tinta-suave);}
.nota{font-size:11px; color:var(--tinta-suave); line-height:1.55;}
.texto{font-size:12.5px; line-height:1.6;}

.marco-media{position:relative; display:flex; align-items:center;
             justify-content:center; font-size:12px; letter-spacing:2px;
             color:var(--tinta-suave); text-align:center;}
.aspa{position:absolute; inset:0; width:100%; height:100%; filter:url(#rugoso);}
.aspa line{stroke:var(--tinta-suave); stroke-width:1.2;}

.pastilla{display:inline-block; padding:5px 12px; font-size:11px;
          letter-spacing:1px; position:relative; margin-right:6px;}
.pastilla.apagada{opacity:.5;}

.campo{position:relative; padding:11px 12px; font-size:12px; min-height:40px;}
.campo .rotulo{position:absolute; top:-8px; left:9px; background:var(--papel);
               padding:0 6px; font-size:10px; letter-spacing:1.2px;
               text-transform:uppercase; color:var(--tinta-suave);}
.campo .flecha{position:absolute; right:12px; top:12px; color:var(--tinta-suave);}
.campo.apagado{opacity:.5;}
.campo .valor{color:var(--tinta);}
.campo .hueco{color:#b9b5ac;}

.casilla{display:inline-block; width:13px; height:13px; position:relative;
         vertical-align:-2px; margin-right:8px;}

table{width:100%; border-collapse:collapse; font-size:11.5px;}
th{font-size:10px; letter-spacing:1.2px; text-transform:uppercase;
   color:var(--tinta-suave); text-align:left; padding:6px 7px; white-space:nowrap;}
td{padding:7px 7px; white-space:nowrap;}
tr+tr td{border-top:1px dashed #cdcac2;}
td.der, th.der{text-align:right;}

.margen{width:252px; flex:none; padding-top:52px;}
.margen .linea{display:flex; gap:9px; margin-bottom:16px; line-height:1.5;
               font-size:11.5px; color:#7a6a52;}
.globo{width:22px; height:22px; border:1.6px solid #7a6a52; border-radius:50%;
       display:flex; align-items:center; justify-content:center; font-size:11px;
       filter:url(#rugoso); flex:none;}
.margen .titulin{font-size:10px; letter-spacing:1.2px; text-transform:uppercase;
                 color:var(--tinta-suave); display:block; margin-bottom:2px;}

.lateral{width:168px; flex:none;}
.principal{flex:1; min-width:0; padding-left:36px;}

/* El numero del margen, repetido junto al bloque que explica: sin esto el
   lector tiene que adivinar a que parte del dibujo se refiere cada nota. */
.conmarca{position:relative;}
.conmarca>.marca{position:absolute; left:-32px; top:9px; width:22px; height:22px;
                 border:1.6px solid #7a6a52; border-radius:50%; color:#7a6a52;
                 display:flex; align-items:center; justify-content:center;
                 font-size:11px; filter:url(#rugoso);}

/* Catorce columnas no caben a tamano normal. */
.apretada{letter-spacing:0;}
.apretada th, .apretada td{padding:4px 3px; font-size:9px;}
.apretada th{letter-spacing:.4px;}
.marco{display:flex; gap:16px; align-items:flex-start;}
"""

FILTRO = """
<svg width="0" height="0" aria-hidden="true">
  <filter id="rugoso" x="-6%" y="-6%" width="112%" height="112%">
    <feTurbulence type="fractalNoise" baseFrequency="0.016" numOctaves="3" seed="11" result="ruido"/>
    <feDisplacementMap in="SourceGraphic" in2="ruido" scale="2.6"
                       xChannelSelector="R" yChannelSelector="G"/>
  </filter>
</svg>
"""

PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>{titulo}</title>
<style>{css}</style></head>
<body>
{filtro}
<div class="hoja">
  <div class="cuerpo">
    <div class="sello">{sello}</div>
    <h1>{encabezado}</h1>
    <div class="sub">{subtitulo}</div>
    {contenido}
    <div class="pie-hoja">{pie}</div>
  </div>
  <div class="margen">{anotaciones}</div>
</div>
</body></html>
"""


# ------------------------------------------------------------------ ladrillos
def caja(contenido: str, trazo: str = "", estilo: str = "") -> str:
    estilo = f' style="{estilo}"' if estilo else ""
    return (f'<div class="caja"{estilo}><span class="trazo {trazo}"></span>'
            f'{contenido}</div>')


def campo(rotulo: str, valor: str = "", *, hueco: bool = False,
          flecha: bool = False, apagado: bool = False, estilo: str = "") -> str:
    clase = "campo apagado" if apagado else "campo"
    estilo = f' style="{estilo}"' if estilo else ""
    texto = (f'<span class="hueco">{valor}</span>' if hueco
             else f'<span class="valor">{valor}</span>')
    punta = '<span class="flecha">&#9662;</span>' if flecha else ""
    return (f'<div class="{clase}"{estilo}><span class="trazo fino"></span>'
            f'<span class="rotulo">{rotulo}</span>{texto}{punta}</div>')


def metrica(rotulo: str, valor: str, pie: str = "", trazo: str = "") -> str:
    extra = f'<div class="nota">{pie}</div>' if pie else ""
    return caja(f'<div class="etiqueta">{rotulo}</div>'
                f'<div class="cifra">{valor}</div>{extra}', trazo)


def barra(clase: str = "larga") -> str:
    return f'<div class="barra {clase}"></div>'


def pastilla(texto: str, *, activa: bool = False) -> str:
    clase = "pastilla" if activa else "pastilla apagada"
    trazo = "" if activa else "fino"
    return (f'<span class="{clase}"><span class="trazo {trazo}"></span>'
            f'{texto}</span>')


def casilla(texto: str) -> str:
    return (f'<span class="casilla"><span class="trazo fino"></span></span>'
            f'<span style="font-size:12px;">{texto}</span>')


def aspa() -> str:
    return ('<svg class="aspa" preserveAspectRatio="none" viewBox="0 0 100 100">'
            '<line x1="0" y1="0" x2="100" y2="100" vector-effect="non-scaling-stroke"/>'
            '<line x1="100" y1="0" x2="0" y2="100" vector-effect="non-scaling-stroke"/>'
            '</svg>')


def media(texto: str, alto: int = 200, *, trazo: str = "", con_aspa: bool = True) -> str:
    cruz = aspa() if con_aspa else ""
    return (f'<div class="caja marco-media" style="height:{alto}px;">'
            f'<span class="trazo {trazo}"></span>{cruz}'
            f'<div style="position:relative;">{texto}</div></div>')


def tabla(cabeceras: list[str], filas: list[list[str]],
          derecha: tuple[int, ...] = (), clase: str = "") -> str:
    # Ojo: no llamar a esta funcion "clase", que es el nombre del parametro y
    # lo tapaba. El atributo salia con el repr de la funcion y la tabla
    # ancha nunca recibia su clase.
    def alineacion(i):
        return ' class="der"' if i in derecha else ""
    cab = "".join(f"<th{alineacion(i)}>{c}</th>" for i, c in enumerate(cabeceras))
    cuerpo = "".join(
        "<tr>" + "".join(f"<td{alineacion(i)}>{v}</td>" for i, v in enumerate(f))
        + "</tr>" for f in filas)
    return f'<table class="{clase}"><tr>{cab}</tr>{cuerpo}</table>'


def marca(numero: int, contenido: str) -> str:
    """Pone el numero del margen junto al bloque que explica."""
    return (f'<div class="conmarca"><span class="marca">{numero}</span>'
            f'{contenido}</div>')


def anotacion(numero: int, titulo: str, texto: str) -> str:
    return (f'<div class="linea"><span class="globo">{numero}</span>'
            f'<span><span class="titulin">{titulo}</span>{texto}</span></div>')


def separacion(alto: int) -> str:
    return f'<div style="height:{alto}px;"></div>'


# ------------------------------------------------------- el marco del dashboard
PESTANAS = ["Eventos", "Salud", "Tolerancias", "Mis tokens", "Usuarios"]


def marco(activa: str, contenido: str, *, rol: str = "administrador") -> str:
    """La barra lateral y las pestanas que rodean a toda pantalla interna."""
    pestanas = "".join(pastilla(p, activa=(p == activa))
                       for p in PESTANAS
                       if rol == "administrador" or p != "Usuarios")
    lateral = caja(
        f'<div class="etiqueta" style="margin:0;">Usuario</div>'
        f'{barra("corta")}'
        f'<div class="nota" style="margin-bottom:12px;">rol {rol}</div>'
        f'{pastilla("Salir", activa=True)}'
        f'<div style="height:8px;"></div>'
        f'{pastilla("Actualizar", activa=True)}', "fino")
    return f"""
<div class="marco">
  <div class="lateral">{lateral}</div>
  <div class="principal">
    <div style="font-size:15px; letter-spacing:1px; margin-bottom:2px;">
      QUINOR S.A.C. · CONTROL DE DESPACHO</div>
    <div class="nota" style="margin-bottom:12px;">Alternativa 1</div>
    <div style="margin-bottom:16px;">{pestanas}</div>
    {contenido}
  </div>
</div>"""
