"""Verificacion del dashboard con una API simulada (critica de UX del 15/11/2026).

No forma parte de la suite: la convencion 4 pide pruebas contra cosas reales y
esto usa respuestas de mentira. Sirve para comprobar el comportamiento de las
pantallas sin levantar el entorno. Uso, desde despacho/api:

    python docs/ux/verificar_puntos_criticos.py

Necesita streamlit==1.41.1 y httpx. Termina con "TODO OK" o se detiene en la
primera comprobacion que falle.
"""
import sys, httpx, pathlib
APP=str(pathlib.Path(__file__).resolve().parents[2]/"dashboard"/"app.py")
from streamlit.testing.v1 import AppTest
SALUD_OK=True
BASCULA="ok"
def fila(i,estado="pendiente"):
    return dict(id=i,creado_en="2026-11-15T09:12:00",numero_orden=f"ORD-{i}",cliente="Cliente demo",diferencia_kg="-350.00",diferencia_pct="-1.75",sacos_esperados=400,sacos_contados=400,diferencia_sacos=0,personas_detectadas=3,personal_anomalo=True,severidad="alta",estado=estado,tiene_clip=True)
def detalle(i,dif=-350.0):
    return dict(id=i,estado="pendiente",numero_orden=f"ORD-{i}",cliente="Cliente demo",producto="Quinua blanca",inicio_carga="2026-11-15T08:57:00",segundo_de_entrada=412,
      pesos=dict(esperado_kg="20000",real_kg=str(20000+dif),diferencia_kg=str(dif),diferencia_pct=str(dif/200),tolerancia_aplicada_kg="100",exceso_sobre_la_tolerancia_kg="250"),
      sacos=dict(analizado=True,esperados=400,contados=400,diferencia=0),peso_corto_con_sacos_completos=dif<0,
      clip=dict(desde="2026-11-15T08:52:10",hasta="2026-11-15T09:14:05",camara="camara-rampa-01",reproducible=True,formato="mkv",completo=True,cobertura_pct=100,motivo_sin_clip=None,enlace=dict(url="http://x/clip.mkv",minutos=15,explicacion=None,direccion=None)),
      fotogramas=[dict(motivo=m,segundo=sg,fotograma=sg*25,detalle=None,enlace=dict(reproducible=False,url=None,explicacion="sin imagen en la prueba")) for m,sg in (("pico_de_personas",412),("primer_saco",130),("ultimo_saco",1180))],
      anomalia=dict(es_anomalia=True,motivo="pico_de_personas",segundo=412),
      analisis=dict(severidad="alta",hay_descripcion=True,descripcion="desc",evidencia=["a"],discrepan=False,severidad_ia="alta"),
      personas=dict(analizado=True,detectadas=1,personal_anomalo=True,presencias=[dict(id_temporal=1,segundos_en_zona=112,primer_fotograma=1,ultimo_fotograma=2)],nota="nota.",permanencia_maxima_s=112,segundos_totales=112),
      veredicto=None,decisiones=[],clasificaciones_posibles=["confirmado","falso_positivo","en_revision"])
LLAMADAS=[]
def falso(metodo,url,**k):
    r=url.split("//",1)[1].split("/",1)[1]; r="/"+r; LLAMADAS.append((metodo,r,k.get("json"),k.get("params")))
    def R(c,j): return httpx.Response(c,json=j)
    if r=="/salud":
        return R(200,dict(estado="ok" if SALUD_OK else "error",componentes=[dict(componente="camara-rampa-01",estado="ok" if SALUD_OK else "error",mensaje="m"),dict(componente="camara-rampa-02",estado="ok",mensaje="m"),dict(componente="bascula",estado=BASCULA,mensaje="m")]))
    if r=="/salud/historial": return R(200,[])
    if r=="/eventos/bandeja":
        f=[fila(214),fila(213),fila(212)]
        return R(200,dict(filas=f,filtros=dict(por_defecto=["estado","desde"]),resumen=dict(abiertos=3,con_faltante_de_sacos=0,con_personal_anomalo=3),total=3,desde_fila=1,hasta_fila=3,pagina=1,paginas=1,segundos=0.1,dentro_del_criterio=True))
    if r.endswith("/detalle"): return R(200,detalle(int(r.split("/")[2]), 350.0 if r.split("/")[2]=="212" else -350.0))
    if r.endswith("/avisos"): return R(200,dict(notificaciones=[]))
    if r.endswith("/veredicto"): return R(201,dict(evento_id=int(r.split("/")[2]),estado=k["json"]["estado_nuevo"]))
    if r=="/eventos": return R(200,[])
    if r=="/pesadas" and metodo=="GET": return R(200,[])
    if r=="/pesadas": return R(201,dict(id=1,numero_orden="ORD-1",peso_real_kg="19650",peso_esperado_kg="20000",origen="manual",fecha_hora="2026-11-15T10:00:00",bascula_id="B1",evento=None))
    if r=="/ordenes": return R(200,[])
    if r.startswith("/ordenes/"): return R(200,dict(numero_orden="ORD-1",cliente="C",producto="Quinua blanca",peso_esperado_kg="20000",sacos_esperados=400,fecha="2026-11-15",sincronizado_en="2026-11-15T10:00:00"))
    if r=="/cargas": return R(200,[])
    if r.endswith("/aplicada"): return R(200,dict(tolerancia_efectiva_kg=100,manda="kg",equivalente_del_pct_kg=150))
    if r=="/configuracion": return R(200,[])
    if r=="/auth/tokens": return R(200,[])
    if r=="/usuarios": return R(200,[])
    raise AssertionError(r)
httpx.request=falso
# AppTest no sabe pulsar el menu de st.navigation cuando las pantallas son
# funciones. Se elige la pantalla por su titulo con la variable PANTALLA, y se
# guarda el menu que la aplicacion construyo para poder comprobarlo.
import streamlit as st
PANTALLA=None; MENU_VISTO={}
_nav=st.navigation
def _navegar(menu,*a,**k):
    actual=_nav(menu,*a,**k)
    MENU_VISTO.clear(); MENU_VISTO.update({g:[p.title for p in ps] for g,ps in menu.items()})
    for ps in menu.values():
        for p in ps:
            if PANTALLA and p.title.startswith(PANTALLA):
                p._can_be_called=True; return p
    return actual
st.navigation=_navegar

# AppTest 1.41 no sabe reenviar el valor de st.pills / segmented_control en modo
# de seleccion unica (trata el texto como lista). Se corrige solo para la prueba.
from streamlit.testing.v1 import element_tree as _et
def _indices(self):
    v=self.value
    vals=[] if v is None else (list(v) if isinstance(v,(list,tuple)) else [v])
    return [list(self.options).index(self.format_func(x)) for x in vals]
_et.ButtonGroup.indices=property(_indices)
def nueva():
    import streamlit as st; st.cache_data.clear()   # la cabecera guarda /salud 20 s
    at=AppTest.from_file(APP,default_timeout=30)
    at.session_state["token"]="t"; at.session_state["usuario"]=dict(nombre="S",correo="s@q",rol="supervisor")
    return at.run()
def textos(at): return " | ".join([m.value for m in at.markdown]+[c.value for c in at.caption])
def boton(at,et): return [b for b in at.button if b.label==et][0]
ok=lambda c,m: print(("OK   " if c else "FALLA")+" "+m) or (c or sys.exit(1))

at=nueva(); ok(not at.exception,"la bandeja dibuja sin excepciones")
ok("Sistema en línea · 2 cámaras grabando" in textos(at),"5: cabecera con estado real (ok)")
ok("Rampa 1 · En línea" not in textos(at),"5: ya no hay texto fijo")
ok(not [e for e in at.expander if e.label=="Detalle del evento"],"3: ya no hay desplegable de detalle al final")
# filtro y luego abrir evento
at.selectbox(key="filtro_severidad").set_value("alta").run()
[b for b in at.button if b.key=="revisar_213"][0].click().run()
ok(not at.exception,"la pagina del evento dibuja sin excepciones")
ok("Evento 2 de 3 de la bandeja" in textos(at),"3: pagina propia con posicion")
ok(not [b for b in at.button if b.label=="Revisar"],"3: la bandeja no se dibuja debajo")
ok(at.error[0].value.startswith("Falta peso y los bultos cuadran"),"4: la conclusion va primero")
m=[x for x in at.metric if x.label=="Diferencia de peso"][0]
ok(m.proto.color==0 or True,"metric presente"); print("     delta_color proto:",m.proto.color, m.delta)
ok(len([x for x in at.metric if x.label=="Diferencia de sacos"])==1,"etiqueta 'Diferencia de sacos'")
ok(len(at.radio)==1 and at.text_area[0].label.startswith("Justificación"),"4: formulario de clasificacion presente")
# navegar
boton(at,"Siguiente").click().run()
ok("Evento 3 de 3 de la bandeja" in textos(at) and boton(at,"Siguiente").disabled,"3: Siguiente llega al ultimo y se desactiva")
m2=[x for x in at.metric if x.label=="Diferencia de peso"][0]; print("     sobrepeso delta_color proto:",m2.proto.color)
ok(m.proto.color==0 and m2.proto.color==0,"2: faltante y sobrepeso salen en ROJO (0=RED)")
boton(at,"Anterior").click().run()
# clasificar
at.text_area[0].set_value("Revisado el clip completo, faltan kilos."); boton(at,"Registrar clasificación").click().run()
ok(any("clasificado como Confirmado" in s.value for s in at.success),"clasificar: confirma en la misma pagina")
ok(any(l[1]=="/eventos/213/veredicto" for l in LLAMADAS),"clasificar: llamo a la API del evento correcto")
boton(at,"← Volver a Eventos").click().run()
ok(len([b for b in at.button if b.label=="Revisar"])==3,"3: volver muestra la bandeja")
ok(at.selectbox(key="filtro_severidad").value=="alta","3: los filtros se conservan al volver")
ok(LLAMADAS[-1][0]=="GET","sin escrituras al volver")
# salud caida
SALUD_OK=False; at=nueva()
ok("1 componente con falla: camara-rampa-01" in textos(at),"5: cabecera en rojo con la camara caida")
SALUD_OK=True
BASCULA="advertencia"; at=nueva()
ok("1 componente con advertencia: bascula" in textos(at) and "con falla" not in textos(at) and "q-vivo q-aviso" in textos(at),"5: la bascula en movimiento es advertencia (ambar), no falla")
BASCULA="error"; at=nueva()
ok("1 componente con falla: bascula" in textos(at),"5: la bascula sin respuesta si es falla")
BASCULA="ok"; at=nueva(); n=len(LLAMADAS); at.run(); at.run()
ok(not [l for l in LLAMADAS[n:] if l[1]=="/salud"],"5: la cabecera no vuelve a sondear /salud en cada pasada (20 s)")
# pesada manual (AppTest 1.41 no sabe pulsar segmented_control: se fija su valor)
import streamlit as st; st.segmented_control=lambda *a,**k:"Ingreso manual"
PANTALLA='Registro de pesada'
at=nueva(); at.text_input[[t.label for t in at.text_input].index("Número de orden de despacho")].set_value("ORD-1")
boton(at,"Consultar orden").click().run()
# Fase 5: los pasos se abren de uno en uno; se salta la marca de inicio.
boton(at,"La carga ya terminó: pesar sin marcar el inicio").click().run()
ni=[n for n in at.number_input if n.label=="Peso real (kg)"]
ok(ni and ni[0].value is None,"1: el peso manual empieza vacio")
ok(not any("dentro de la tolerancia" in s.value for s in at.success),"1: sin aviso verde antes de escribir")
n=len(LLAMADAS); boton(at,"Registrar pesada").click().run()
ok(any("Escriba el peso real" in w.value for w in at.warning) and not any(l[0]=="POST" for l in LLAMADAS[n:]),"1: no registra sin peso")
ni=[n for n in at.number_input if n.label=="Peso real (kg)"][0]; ni.set_value(19650.0).run()
ok(any("supera la tolerancia" in e.value for e in at.error),"1: con peso escrito, avisa del evento")
print("TODO OK")
