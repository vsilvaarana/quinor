"""Verificacion del dashboard con una API simulada (critica de UX del 15/11/2026).

No forma parte de la suite: la convencion 4 pide pruebas contra cosas reales y
esto usa respuestas de mentira. Sirve para comprobar el comportamiento de las
pantallas sin levantar el entorno. Uso, desde despacho/api:

    python docs/ux/verificar_fases_5_y_6.py

Necesita streamlit==1.41.1 y httpx. Termina con "TODO OK" o se detiene en la
primera comprobacion que falle.
"""
import sys, httpx, pathlib
APP=str(pathlib.Path(__file__).resolve().parents[2]/"dashboard"/"app.py")
from streamlit.testing.v1 import AppTest
SALUD_OK=True
ROL1="administrador"
def fila(i,estado="pendiente",**k):
    return dict(id=i,creado_en="2026-11-15T09:12:00",numero_orden=f"ORD-{i}",cliente="Cliente demo",diferencia_kg="-350.00",diferencia_pct="-1.75",sacos_esperados=400,sacos_contados=400,diferencia_sacos=0,personas_detectadas=3,personal_anomalo=True,severidad="alta",estado=estado,tiene_clip=True)|k
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
PREVIA="fuera"; EVENTOS_CAIDO=False; CARGA_ABIERTA=False
ROL_SESION="supervisor"
def falso(metodo,url,**k):
    global ROL1, CARGA_ABIERTA
    r=url.split("//",1)[1].split("/",1)[1]; r="/"+r; LLAMADAS.append((metodo,r,k.get("json"),k.get("params")))
    def R(c,j): return httpx.Response(c,json=j)
    if r=="/salud":
        return R(200,dict(estado="ok" if SALUD_OK else "error",componentes=[dict(componente="camara-rampa-01",estado="ok" if SALUD_OK else "error",mensaje="m"),dict(componente="camara-rampa-02",estado="ok",mensaje="m"),dict(componente="bascula",estado="ok",mensaje="m")]))
    if r=="/salud/historial": return R(200,[])
    if r=="/eventos/bandeja":
        f=[fila(214),fila(213,sacos_contados=397,diferencia_sacos=-3,diferencia_kg="-150.00"),fila(212,sacos_contados=None,diferencia_sacos=None,severidad=None)]
        return R(200,dict(filas=f,filtros=dict(por_defecto=["estado","desde"]),resumen=dict(abiertos=3,con_faltante_de_sacos=1,con_peso_corto_y_sacos_completos=1,con_personal_anomalo=3),total=120,desde_fila=1,hasta_fila=3,pagina=(k.get("params") or {}).get("pagina",1),paginas=3,segundos=0.1,dentro_del_criterio=True))
    if r.endswith("/detalle"): return R(200,detalle(int(r.split("/")[2]), 350.0 if r.split("/")[2]=="212" else -350.0))
    if r.endswith("/avisos"): return R(200,dict(notificaciones=[]))
    if r.endswith("/veredicto"): return R(201,dict(evento_id=int(r.split("/")[2]),estado=k["json"]["estado_nuevo"]))
    if r=="/eventos": return R(500,dict(detail="x")) if EVENTOS_CAIDO else R(200,[dict(id=214,pesada_id=531)])
    if r=="/pesadas/lectura-previa":
        if PREVIA=="caida": return R(503,dict(detail="la bascula BASCULA-01 no respondio en 5 s"))
        if PREVIA=="movimiento": return R(200,dict(numero_orden="ORD-1",bascula_id="BASCULA-01",peso_kg="19700.00",estable=False,leido_en="2026-11-15T10:00:05",peso_esperado_kg="20000.00",diferencia_kg=None,diferencia_pct=None,tolerancia_kg=None,generaria_evento=None))
        if PREVIA=="sin_tolerancia": return R(200,dict(numero_orden="ORD-1",bascula_id="BASCULA-01",peso_kg="19650.00",estable=True,leido_en="2026-11-15T10:00:05",peso_esperado_kg="20000.00",diferencia_kg="-350.00",diferencia_pct="-1.75",tolerancia_kg=None,generaria_evento=None))
        kg={"fuera":"19650.00","dentro":"19990.00"}[PREVIA]; d=float(kg)-20000
        return R(200,dict(numero_orden="ORD-1",bascula_id="BASCULA-01",peso_kg=kg,estable=True,leido_en="2026-11-15T10:00:05",peso_esperado_kg="20000.00",diferencia_kg=f"{d:.2f}",diferencia_pct=f"{d/200:.2f}",tolerancia_kg="100.00",generaria_evento=abs(d)>100))
    if r=="/pesadas" and metodo=="GET":
        return R(200,[dict(id=531,numero_orden="ORD-0148",cliente="C",producto="Quinua blanca",bascula_id="BASCULA-01",peso_real_kg="19650.00",peso_esperado_kg="20000.00",fecha_hora="2026-11-15T09:12:04",origen="bascula"),
                      dict(id=530,numero_orden="ORD-0147",cliente="C",producto="Quinua blanca",bascula_id="BASCULA-01",peso_real_kg="14985.00",peso_esperado_kg="15000.00",fecha_hora="2026-11-15T08:03:51",origen="manual")])
    if r=="/pesadas": return R(201,dict(id=1,numero_orden="ORD-1",peso_real_kg="19650",peso_esperado_kg="20000",origen="manual",fecha_hora="2026-11-15T10:00:00",bascula_id="B1",evento=None))
    if r=="/ordenes": return R(200,[])
    if r.startswith("/ordenes/"): return R(200,dict(numero_orden="ORD-1",cliente="C",producto="Quinua blanca",peso_esperado_kg="20000",sacos_esperados=400,fecha="2026-11-15",sincronizado_en="2026-11-15T10:00:00"))
    if r=="/cargas": return R(200,[dict(numero_orden="ORD-1",inicio="2026-11-15T09:45:00",bascula_id="BASCULA-01")] if CARGA_ABIERTA else [])
    if r.startswith("/cargas/"):
        CARGA_ABIERTA=True; return R(201,{})
    if r.endswith("/aplicada"): return R(200,dict(tolerancia_efectiva_kg=100,manda="kg",equivalente_del_pct_kg=150))
    if r=="/configuracion": return R(200,[
        dict(id=1,producto="Quinua blanca",tolerancia_kg="50.00",tolerancia_pct="0.50",canales_por_severidad={"alta":["sms","slack"],"media":["slack","correo"],"baja":[]},actualizado_por=1,actualizado_por_nombre="Ana Admin",fecha="2026-10-02T10:15:00"),
        dict(id=2,producto="Quinua roja",tolerancia_kg="50.00",tolerancia_pct="0.50",canales_por_severidad={"alta":["sms"],"media":["correo"],"baja":["correo"]},actualizado_por=None,actualizado_por_nombre=None,fecha="2026-09-14T00:00:00")])
    if r.endswith("/historial") and r.startswith("/configuracion/"): return R(200,[dict(id=1,fecha="2026-10-02T10:15:00",usuario_id=1,usuario_nombre="Ana Admin",detalle=dict(antes=dict(kg="40.00",pct="0.50"),despues=dict(kg="50.00",pct="0.50")))] if "blanca" in r else [])
    if r.startswith("/configuracion/") and metodo=="PATCH": return R(200,{})
    if r=="/auth/tokens": return R(200,[dict(id=7,nombre="Laptop rampa 1",expira_en="2026-11-16T10:00:00",ultimo_uso_en=None,revocado_en=None)])
    if r.startswith("/auth/tokens/"): return R(200,dict(id=7))
    if r=="/usuarios": return R(200,[dict(id=1,nombre="Ana Admin",correo="a@q",rol=ROL1,activo=True),dict(id=2,nombre="Luis Super",correo="l@q",rol="supervisor",activo=True)])
    if r.startswith("/usuarios/"):
        if r.endswith("/rol"): ROL1=k["json"]["rol"]
        return R(200,{})
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
# AppTest tampoco simula el redibujado parcial de st.dialog: al pulsar un boton
# de dentro vuelve a correr todo el script y el dialogo ya no se abre. En el
# navegador solo se vuelve a ejecutar el dialogo. Para imitarlo, el boton que lo
# abrio se mantiene pulsado mientras su clave este en ABIERTOS.
from streamlit.delta_generator import DeltaGenerator as _DG
ABIERTOS=set(); _boton=_DG.button
def _boton_pegado(self,label,*a,**k):
    r=_boton(self,label,*a,**k)
    return True if k.get("key") in ABIERTOS else r
_DG.button=_boton_pegado
def nueva():
    at=AppTest.from_file(APP,default_timeout=30)
    at.session_state["token"]="t"; at.session_state["usuario"]=dict(nombre="S",correo="s@q",rol=ROL_SESION)
    return at.run()
def textos(at): return " | ".join([m.value for m in at.markdown]+[c.value for c in at.caption])
def boton(at,et): return [b for b in at.button if b.label==et][0]
ok=lambda c,m: print(("OK   " if c else "FALLA")+" "+m) or (c or sys.exit(1))



import streamlit as st
ORIGEN="Báscula"; st.segmented_control=lambda *a,**k: ORIGEN   # AppTest 1.41 no sabe pulsarlo
def post(n): return [(l[1],l[2]) for l in LLAMADAS[n:] if l[0]=="POST"]
def orden(at):
    at.text_input[[t.label for t in at.text_input].index("Número de orden de despacho")].set_value("ORD-1")
    boton(at,"Consultar orden").click().run(); return at

# ================================================================ FASE 5
PANTALLA="Registro de pesada"; at=nueva(); ok(not at.exception,"F5: Registro de pesada dibuja sin excepciones")
ok(not [b for b in at.button if b.label in ("Iniciar carga","Leer báscula","Registrar pesada")],"F5: sin orden solo se ofrece el paso 1")
orden(at); ok(not at.exception,"F5: tras consultar la orden, sin excepciones")
t=textos(at)
ok("ORD-1" in t and "20,000 kg" in t and boton(at,"Cambiar orden"),"F5: el paso 1 queda resumido, con Cambiar orden")
ok(boton(at,"Iniciar carga") and not [b for b in at.button if b.label=="Leer báscula"],"F5: en el paso 2 todavia no se puede pesar")
n=len(LLAMADAS); boton(at,"Iniciar carga").click().run()
ok(("/cargas/ORD-1/inicio",{}) in post(n),"F5: Iniciar carga marca el inicio en la API")
ok(boton(at,"Leer báscula") and not [b for b in at.button if b.label=="Iniciar carga"],"F5: con la carga iniciada se pasa al paso 3")
ok(not [b for b in at.button if b.label.startswith("Registrar pesada")],"F5: no se puede registrar con bascula sin haberla leido")
# lectura fuera de tolerancia
n=len(LLAMADAS); boton(at,"Leer báscula").click().run()
ok(post(n)==[("/pesadas/lectura-previa",{"numero_orden":"ORD-1"})],"F5: Leer bascula pide la lectura previa y nada mas")
ok("q-lectura'>19,650 kg" in textos(at),"F5: muestra el peso leido")
ok(any("Supera la tolerancia de 100 kg" in e.value for e in at.error),"F5: avisa ANTES de registrar de que se creara un evento")
ok(any("quedó registrada con su usuario" in c.value for c in at.caption),"F5: dice que la lectura queda registrada")
m=[x for x in at.metric if x.label=="Diferencia"][0]; ok(m.value=="-350 kg","F5: diferencia contra la orden")
# registrar: no viaja el peso
n=len(LLAMADAS); boton(at,"Registrar pesada y cerrar carga").click().run()
ok(post(n)==[("/pesadas",{"numero_orden":"ORD-1"})],"F5: al registrar NO se envia el peso de la pantalla; la API vuelve a leer")
ok(not at.exception and boton(at,"Registrar otra pesada"),"F5: tras registrar se ve el resultado")
boton(at,"Registrar otra pesada").click().run()
ok(boton(at,"Consultar orden") and not [b for b in at.button if b.label=="Cambiar orden"],"F5: Registrar otra pesada vuelve al paso 1")
# dentro de tolerancia
PREVIA="dentro"; orden(at); boton(at,"Leer báscula").click().run()
ok(any("Dentro de la tolerancia de 100 kg" in s_.value for s_ in at.success) and not at.error,"F5: dentro de tolerancia, aviso en verde")
# la lectura no se arrastra a otra orden
boton(at,"Cambiar orden").click().run(); orden(at)
ok(boton(at,"Leer báscula") and "q-lectura'>" not in textos(at),"F5: al cambiar de orden no se ve la lectura anterior")
# en movimiento
PREVIA="movimiento"; boton(at,"Leer báscula").click().run()
ok(any("sigue en movimiento" in w.value for w in at.warning),"F5: bascula en movimiento, pide esperar")
ok(boton(at,"Registrar pesada y cerrar carga").disabled and not [x for x in at.metric if x.label=="Diferencia"],"F5: en movimiento no deja registrar ni da diferencia")
PREVIA="sin_tolerancia"; boton(at,"Leer de nuevo").click().run()
ok(any("no tiene tolerancia configurada" in w.value for w in at.warning) and not at.success,"F5: sin tolerancia no afirma que no habra evento")
PREVIA="caida"; boton(at,"Leer de nuevo").click().run()
ok(any("La báscula no respondió" in e.value for e in at.error) and "q-lectura'>" not in textos(at),"F5: bascula caida, error y sin peso en pantalla")
# sin marca de inicio
CARGA_ABIERTA=False; PREVIA="fuera"; at=nueva(); orden(at)
boton(at,"La carga ya terminó: pesar sin marcar el inicio").click().run()
ok(boton(at,"Leer báscula") and any("solo los 5 minutos previos" in c.value for c in at.caption),"F5: se puede pesar sin marca, y dice lo que se pierde")
# manual sigue igual
ORIGEN="Ingreso manual"; at.run()
ni=[x for x in at.number_input if x.label=="Peso real (kg)"]
ok(ni and ni[0].value is None and not [b for b in at.button if b.label=="Leer báscula"],"F5: el ingreso manual sigue disponible y vacio")
ORIGEN="Báscula"
# historial
df=at.dataframe[-1].value
ok(list(df.columns)[0]=="Resultado" and list(df["Resultado"])==["Evento #214","Sin evento"],"F5: el historial dice que pesada abrio evento")
EVENTOS_CAIDO=True; at.run(); df=at.dataframe[-1].value
ok(set(df["Resultado"])=={"No disponible"},"F5: si no se pueden consultar los eventos, no afirma 'Sin evento'")
EVENTOS_CAIDO=False
# rol consulta
ROL_SESION="consulta"; at=nueva()
ok(not at.exception and not [b for b in at.button if b.label=="Consultar orden"] and len(at.dataframe)==1,"F5: Consulta solo ve el historial")

# ================================================================ FASE 6
ROL_SESION="administrador"; PANTALLA="Tolerancias"; n=len(LLAMADAS); at=nueva()
ok(not at.exception,"F6: Tolerancias (administrador) dibuja sin excepciones")
df=at.dataframe[0].value
ok(list(df["Producto"])==["Quinua blanca","Quinua roja"] and list(df["Se admiten"])==["100 kg (límite en kg)","100 kg (límite en kg)"],"F6: los productos van en una tabla comparable")
ok(df["Avisos por severidad"][0]=="Alta: SMS, Slack · Media: Slack, Correo · Baja: sin aviso","F6: los canales se leen en texto, no en JSON")
ok(len(at.json)==0,"F6: ya no hay JSON en pantalla")
ok(df["Último cambio"][1]=="Sin cambios desde la instalación","F6: ultimo cambio legible")
rutas=[l[1] for l in LLAMADAS[n:] if "historial" in l[1]]
ok(rutas==["/configuracion/Quinua blanca/historial"],"F6: solo se pide el historial del producto elegido")
kg=[x for x in at.number_input if x.label=="Límite en kg"][0]
n=len(LLAMADAS); boton(at,"Guardar cambios").click().run()
ok(not any(l[0]=="PATCH" for l in LLAMADAS[n:]) and any("No hay cambios" in i.value for i in at.info),"F6: guardar sin cambios no llama a la API")
[x for x in at.number_input if x.label=="Límite en kg"][0].set_value(80.0)
n=len(LLAMADAS); boton(at,"Guardar cambios").click().run()
ok(not any(l[0]=="PATCH" for l in LLAMADAS[n:]),"F6: guardar pide confirmacion antes de cambiar")
ok(any("de 50.00 kg y 0.50 % a **80.00 kg y 0.50 %**" in m_.value for m_ in at.markdown),"F6: la confirmacion muestra el antes y el despues")
ROL_SESION="supervisor"; at=nueva()
ok(not at.exception and not [x for x in at.number_input if x.label=="Límite en kg"] and not [b for b in at.button if b.label=="Guardar cambios"],"F6: el supervisor tiene vista de lectura, sin campos deshabilitados")
ok(any("Solo el rol Administrador" in c.value for c in at.caption) and len(at.dataframe)>=1,"F6: el supervisor ve la tabla y por que no edita")
# ingreso
PANTALLA=None
at=AppTest.from_file(APP,default_timeout=30).run()
ok(not at.exception and [t_.label for t_ in at.text_input]==["Correo electrónico","Contraseña"],"F6: ingreso con sus dos campos")
ok(any("le asignó el administrador" in c.value for c in at.caption) and any(m_.value=="## QUINOR" for m_ in at.markdown),"F6: ingreso centrado, con marca y leyenda")
def cae(*a,**k): raise httpx.ConnectError("x")
httpx.post=cae
at.text_input[0].set_value("a@b"); at.text_input[1].set_value("x"); at.button[0].click().run()
ok(at.error[0].value.startswith("No hay conexión") and any("le asignó el administrador" in c.value for c in at.caption),"F6: con error, la leyenda sigue visible")
httpx.post=lambda *a,**k: httpx.Response(200,json={"token":"t","usuario":{"nombre":"S","correo":"s@q","rol":"supervisor"}})
at.button[0].click().run()
ok(at.session_state["token"]=="t","F6: el ingreso correcto deja la sesion abierta")
print("TODO OK")
