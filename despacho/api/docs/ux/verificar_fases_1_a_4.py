"""Verificacion del dashboard con una API simulada (critica de UX del 15/11/2026).

No forma parte de la suite: la convencion 4 pide pruebas contra cosas reales y
esto usa respuestas de mentira. Sirve para comprobar el comportamiento de las
pantallas sin levantar el entorno. Uso, desde despacho/api:

    python docs/ux/verificar_fases_1_a_4.py

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
ROL_SESION="supervisor"
def falso(metodo,url,**k):
    global ROL1
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
    if r=="/eventos": return R(200,[])
    if r=="/pesadas" and metodo=="GET": return R(200,[])
    if r=="/pesadas": return R(201,dict(id=1,numero_orden="ORD-1",peso_real_kg="19650",peso_esperado_kg="20000",origen="manual",fecha_hora="2026-11-15T10:00:00",bascula_id="B1",evento=None))
    if r=="/ordenes": return R(200,[])
    if r.startswith("/ordenes/"): return R(200,dict(numero_orden="ORD-1",cliente="C",producto="Quinua blanca",peso_esperado_kg="20000",sacos_esperados=400,fecha="2026-11-15",sincronizado_en="2026-11-15T10:00:00"))
    if r=="/cargas": return R(200,[])
    if r.endswith("/aplicada"): return R(200,dict(tolerancia_efectiva_kg=100,manda="kg",equivalente_del_pct_kg=150))
    if r=="/configuracion": return R(200,[])
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


P=lambda: [l[3] for l in LLAMADAS if l[1]=="/eventos/bandeja"][-1]
at=nueva(); ok(not at.exception,"la bandeja dibuja sin excepciones")
t=textos(at)
ok("Faltan 3 sacos" in t and "Posible sustitución" in t and "Conteo de sacos pendiente" in t,"F2: hallazgo en cada tarjeta")
ok("q-dif'>-350 kg" in t,"F2: diferencia en kg destacada")
ok(not [e for e in at.expander if e.label=="Filtros"],"F2: los filtros ya no estan en un desplegable")
ok(P()=={"tamano":50,"pagina":1},"F2: por defecto no manda filtros (valen los de la API)")
# atajo de resumen
boton(at,"Ver solo con diferencia de sacos").click().run()
ok(P().get("solo_con_faltante") is True,"F2: el boton de resumen filtra de verdad")
ok(any(b.label=="Más filtros (1)" or True for b in at.button),"etiqueta de mas filtros")
# paginacion en el pie
boton(at,"Siguiente").click().run(); ok(P()["pagina"]==2,"F2: Siguiente del pie pasa a la pagina 2")
at.selectbox(key="filtro_periodo").set_value("todo").run()
ok(P()["pagina"]==1 and P().get("estado")=="pendiente" and P().get("sin_defectos"),"F2: cambiar filtro vuelve a pag. 1; Pendientes+Todo sigue siendo solo pendientes")
at.selectbox(key="filtro_periodo").set_value("ultimos 7 dias").run()
# tabla
import pandas as pd
df=at.dataframe[0].value; ok(set(df["Estado"])=={"Pendiente"},"F1: la tabla muestra el nombre del estado, no el codigo")
# abrir, clasificar corto
[b for b in at.button if b.key=="revisar_213"][0].click().run()
ok(not at.exception,"pagina del evento sin excepciones")
ok(at.text_area[0].label=="Justificación (mínimo 10 caracteres)","F3: el minimo esta en la etiqueta")
ok(any("después no podrá" in c.value for c in at.caption),"F3: aviso de que confirmar no se revierte")
ok(any("ábralo en Chrome o Edge" in c.value for c in at.caption) and not any("Matroska" in c.value for c in at.caption),"F1: sin jerga en el video")
at.text_area[0].set_value("corto"); boton(at,"Registrar clasificación").click().run()
ok(any("al menos 10 caracteres" in w.value for w in at.warning) and not any(l[1].endswith("/veredicto") for l in LLAMADAS),"F3: justificacion corta no se envia")
boton(at,"← Volver a Eventos").click().run()
ok(P().get("solo_con_faltante") is True,"los filtros se conservan al volver")
# tokens: confirmar antes de revocar
PANTALLA="Tokens"; at.run()
n=len(LLAMADAS); boton(at,"Revocar").click().run()
ok(not at.exception,"dialogo de revocar sin excepciones")
ok(not any(l[0]=="DELETE" for l in LLAMADAS[n:]),"F3: Revocar no borra al primer clic")
ok(any("Va a revocar el token" in m.value for m in at.markdown),"F3: el dialogo dice que va a pasar")
boton(at,"Cancelar").click().run(); ok(not any(l[0]=="DELETE" for l in LLAMADAS[n:]),"F3: Cancelar no hace nada")
ABIERTOS.add("revocar_7"); at.run(); boton(at,"Revocar token").click().run(); ABIERTOS.clear()
ok(any(l[0]=="DELETE" and l[1]=="/auth/tokens/7" for l in LLAMADAS[n:]),"F3: al confirmar, revoca")
ok(any("revocado" in x.value for x in at.success),"F3: confirma el resultado tras el dialogo")
# usuarios (admin)
ROL_SESION="administrador"; PANTALLA="Usuarios"; at=nueva(); ok(not at.exception,"admin dibuja sin excepciones")
n=len(LLAMADAS); at.selectbox(key="rol_1").set_value("consulta").run()
ok(not any(l[0]=="PATCH" for l in LLAMADAS[n:]),"F3: elegir otro rol en la lista ya no lo aplica")
boton(at,"Aplicar rol").click().run(); ok(not any(l[0]=="PATCH" for l in LLAMADAS[n:]),"F3: Aplicar rol pide confirmacion")
ABIERTOS.add("aplicar_rol_1"); at.run(); boton(at,"Cambiar rol").click().run(); ABIERTOS.clear(); at.run()
ok([l for l in LLAMADAS[n:] if l[0]=="PATCH"][0][1:3]==("/usuarios/1/rol",{"rol":"consulta"}),"F3: al confirmar, cambia el rol correcto")
ok(not [b for b in at.button if b.label=="Aplicar rol"],"tras aplicar, no queda cambio pendiente")
n=len(LLAMADAS); [b for b in at.button if b.key=="activacion_2"][0].click().run()
ok(not any(l[0]=="PATCH" for l in LLAMADAS[n:]),"F3: Desactivar pide confirmacion")
ABIERTOS.add("activacion_2"); at.run(); boton(at,"Desactivar usuario").click().run(); ABIERTOS.clear()
ok([l for l in LLAMADAS[n:] if l[0]=="PATCH"][0][1:3]==("/usuarios/2/activacion",{"activo":False}),"F3: al confirmar, desactiva al usuario correcto")
# ---------------------------------------------------------------- fase 4
ROL_SESION="supervisor"; PANTALLA=None; n=len(LLAMADAS); at=nueva()
ok(not at.exception,"F4: Eventos dibuja sin excepciones")
ok(MENU_VISTO=={"Operación":["Eventos (3)","Registro de pesada","Órdenes"],"Monitoreo":["Cámaras","Estado del sistema"],"Administración":["Tolerancias","Tokens de acceso"]},"F4: menu en tres grupos, con contador, y sin Usuarios para el supervisor")
rutas={l[1] for l in LLAMADAS[n:]}
ok(rutas=={"/eventos/bandeja","/salud"},"F4: en Eventos solo se llama a la bandeja y a la salud: "+str(sorted(rutas)))
ok("3 eventos" in textos(at),"F4: Eventos conserva el titulo con los pendientes")
at.selectbox(key="filtro_severidad").set_value("media").run()
PANTALLA="Registro de pesada"; n=len(LLAMADAS); at.run()
ok(not at.exception and "Sistema en línea" in textos(at),"F4: la linea de estado va en todas las pantallas")
ok("3 eventos" not in textos(at),"F4: el titulo grande solo esta en Eventos")
rutas={l[1] for l in LLAMADAS[n:]}
ok(rutas=={"/eventos/bandeja","/salud","/pesadas"},"F4: en Registro de pesada no se piden tokens, usuarios ni tolerancias: "+str(sorted(rutas)))
PANTALLA=None; at.run()
ok(at.selectbox(key="filtro_severidad").value=="media","F4: los filtros de la bandeja sobreviven a visitar otra pantalla")
for PANTALLA in ("Órdenes","Cámaras","Estado del sistema","Tolerancias","Tokens"):
    at.run(); ok(not at.exception,"F4: "+PANTALLA+" dibuja sin excepciones")
ROL_SESION="administrador"; PANTALLA="Usuarios"; at=nueva()
ok(MENU_VISTO["Administración"]==["Tolerancias","Tokens de acceso","Usuarios"] and not at.exception,"F4: el administrador si ve Usuarios")
PANTALLA=None
# ingreso sin conexion
def cae(*a,**k): raise httpx.ConnectError("x")
httpx.post=cae
at=AppTest.from_file(APP,default_timeout=30).run()
at.text_input[0].set_value("a@b"); at.text_input[1].set_value("x"); at.button[0].click().run()
ok(at.error[0].value.startswith("No hay conexión con el sistema") and "http" not in at.error[0].value,"F1: el error de ingreso no expone la direccion interna")
print("TODO OK")
