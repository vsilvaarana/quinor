# Videos reales para las camaras simuladas

Mientras no haya camaras de la rampa conectadas, el sistema puede trabajar con
**grabaciones reales**. Cada camara simulada publica en bucle los videos de su
carpeta, como si fueran la camara de verdad: el grabador los graba, recorta el
clip de cada evento, YOLO cuenta y el supervisor lo ve en el dashboard.

```
videos/
  rampa-01/      videos de la camara-01
  rampa-02/      videos de la camara-02
```

- Formatos: `.mp4`, `.mkv`, `.avi`, `.mov`, `.m4v`, `.ts`. Cualquier codec que
  ffmpeg lea (H.264, H.265, MJPEG...).
- Se reproducen en **orden alfabetico** y, al terminar el ultimo, vuelve al
  primero. Para fijar el orden, numerarlos: `01_llegada.mp4`, `02_carga.mp4`.
- **Carpeta vacia: barras de colores**, como siempre. Se puede tener una camara
  con videos y otra sintetica.
- Los videos **no se suben a Git** (estan en `.gitignore`): pesan demasiado.

## Como usarlo

1. Copiar los videos en `despacho/api/videos/rampa-01/` (y `rampa-02/` si hay
   de la segunda camara).
2. Reiniciar la camara para que lea la carpeta:

   ```bash
   docker compose up -d --build camara-sim-01 camara-sim-02
   ```

   La primera vez hace falta `--build` porque cambio el simulador. Despues,
   al agregar o quitar videos, basta con `docker compose restart camara-sim-01`.
3. Mirar que tomo los videos:

   ```bash
   docker compose logs camara-sim-01 --tail 20
   ```

   Debe decir `1 video(s) real(es) de /videos, en bucle: ...`. Al arrancar,
   cada video **se convierte una sola vez** al formato de la camara de planta
   (H.264, 1280x720, 15 fps, un fotograma clave por segundo); un video de una
   hora tarda unos minutos. Mientras convierte, la camara aparece sin senal.
4. Registrar una pesada en el dashboard como siempre. El clip del evento sale
   de estos videos.

**Los videos se publican "en vivo".** El grabador los recibe a velocidad real,
igual que de una camara: para que un evento tenga video, la pesada tiene que
registrarse mientras el video corre, y el clip cubre los 5 minutos antes del
inicio de carga y los 2 despues de la pesada.

## Otra carpeta de la PC

Si los videos estan en otro lugar, por ejemplo `D:\grabaciones`, no hace falta
moverlos. En el `.env`:

```
CAMERA_VIDEOS_DIR=D:/grabaciones
```

(con barras normales). Dentro tiene que haber las subcarpetas `rampa-01` y
`rampa-02`. Despues, `docker compose up -d camara-sim-01 camara-sim-02`.

## Llevar los videos a la maquina de Azure

Desde PowerShell de la PC:

```powershell
scp -i $HOME\.ssh\TU_CLAVE.pem -r C:\videos\rampa-01 azureuser@IP:~/quinor/despacho/api/videos/
```

Para compartirlos con mas gente (el companero, la maquina de Azure), se pueden
dejar en el bucket S3 bajo `videos-prueba/rampa-01/` y bajarlos en cada equipo
con `aws s3 sync s3://BUCKET/videos-prueba/rampa-01 videos/rampa-01`. S3 es el
lugar para **guardarlos y repartirlos**; la camara siempre los lee de una
carpeta local, como la camara real lee de su sensor.

## Lo que hay que saber antes de sacar conclusiones

- **El modelo de YOLO se entreno con video sintetico**, tanto los sacos como
  las personas (`modelos/sacos.pt`, HU-19 pendiente). Con video real puede
  contar mal o no ver a alguien: es esperable, y estas grabaciones son
  justamente el material para etiquetar y reentrenarlo.
- **La linea de carga** que cruzan los sacos esta, por defecto, en vertical por
  el centro de la imagen. Si en el video los sacos cruzan por otro lado, se
  ajusta en el `.env` con `LINEA_CARGA=x1,y1,x2,y2` (coordenadas de 0 a 1,
  donde 0,0 es la esquina superior izquierda), y la zona donde se mide la
  permanencia de las personas con `ZONA_CARGA`. Luego `docker compose up -d yolo`.
- Video de personas reales: es un dato personal. Usar grabaciones con permiso
  de la empresa y de quienes aparecen, y no compartirlas fuera del equipo.
