# Guion de prueba con un supervisor

Pendiente de la fase 7 que no se puede hacer desde el codigo: ver a una persona
de la rampa usar las pantallas nuevas. Este guion sirve para una sesion de 30
minutos. No se le explica la pantalla antes: lo que interesa es donde duda.

## Preparacion

- Entorno de demostracion con al menos tres eventos pendientes: uno con posible
  sustitucion (falta peso y los sacos cuadran) y uno con faltante de sacos.
- Un usuario con rol Supervisor y una orden lista para pesar.
- Quien observa no ayuda salvo que la persona se quede bloqueada mas de un
  minuto. Anota el tiempo de cada tarea y en que punto dudo.

## Tareas

| # | Se le pide | Se observa | Se da por buena si |
|---|---|---|---|
| 1 | "Entre al sistema" | Si encuentra los campos y el boton | Entra sin ayuda |
| 2 | "Cuantos eventos hay por revisar?" | Si lo lee en el menu o en el titulo | Responde en menos de 10 s |
| 3 | "Cual de estos casos le preocupa mas y por que?" | Si usa la severidad, la cifra en rojo y la etiqueta de hallazgo | Nombra la sustitucion y dice que significa |
| 4 | "Revise ese caso y decida" | Si encuentra el video, salta a un fotograma y clasifica | Clasifica con justificacion sin subir y bajar la pagina |
| 5 | "Pase al siguiente caso" | Si usa Siguiente o vuelve a la bandeja | Llega al siguiente evento |
| 6 | "Muestreme solo los casos con sacos faltantes" | Si usa el boton de resumen o Mas filtros | Lo consigue en menos de 20 s |
| 7 | "Registre la pesada de la orden X" | Si sigue los tres pasos; que hace al ver el aviso de evento | Registra sin preguntar que boton pulsar |
| 8 | "La bascula no responde. Registre el peso" | Si encuentra Ingreso manual y escribe el motivo | Registra como manual |
| 9 | "Que tolerancia tiene la quinua blanca?" | Si entiende la columna Se admiten | Responde en kilos |

## Preguntas de cierre

1. Que fue lo mas confuso?
2. Hubo algun momento en que no supo si lo que hizo se guardo?
3. Al leer la bascula, entendio que esa lectura queda registrada?
4. Que le falta a la tarjeta de un evento para decidir sin abrirlo?

## Que hacer con el resultado

Cada tarea fallida o con duda de mas de 30 segundos es un punto de mejora.
Anotarlo en `CAMBIOS_UX_20261115.md`, seccion "Fase 7", con la tarea, lo que
paso y la pantalla.
