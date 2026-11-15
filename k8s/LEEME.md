# QUINOR en Kubernetes (AKS)

Manifiestos equivalentes al `docker-compose.yml` de `despacho/api`: 13 servicios,
un volumen para el buffer de video y las imagenes del ACR.

## Antes de aplicar

Deben existir (los crean los scripts de `despliegue_azure`):

- El cluster AKS con credenciales en `kubectl` (`kubectl get nodes` responde).
- El namespace `quinor`.
- El Secret `quinor-env` y el ConfigMap `aws-certs`.
- Las 5 imagenes en el ACR. `kustomization.yaml` asume el registro
  `quinoracr2026.azurecr.io` y la etiqueta `1.0`: cambiar ahi si son otros.

## Aplicar

```powershell
cd C:\proyectos\PI1\quinor\k8s
kubectl apply -k .
kubectl get pods -n quinor -w
```

Tardan en quedar `Running` 1/1: YOLO carga PyTorch (hasta 2 o 3 minutos). Es normal
ver reinicios de `api` y `grabador` al principio, porque arrancan antes que lo que
necesitan (en el compose esperaban con `depends_on`; aqui reintentan).

## Ver la web

Sin exponer nada a internet:

```powershell
kubectl port-forward svc/dashboard 8501:8501 -n quinor
```

Abrir http://localhost:8501. Una sola ventana de PowerShell por port-forward.

Otras pantallas y servicios:

```powershell
kubectl port-forward svc/api 8000:8000 -n quinor        # http://localhost:8000
kubectl port-forward svc/mailpit 8025:8025 -n quinor    # correos de prueba
```

## Diagnostico

```powershell
kubectl get pods,svc,pvc -n quinor
kubectl describe pod <pod> -n quinor        # eventos: imagen, volumen, memoria
kubectl logs deploy/api -n quinor
kubectl logs deploy/grabador -n quinor
kubectl logs deploy/yolo -n quinor
```

| Sintoma | Causa probable |
|---|---|
| `ImagePullBackOff` | La imagen o etiqueta no existe en el ACR, o el cluster no tiene AcrPull |
| `Pending` en yolo | Espera al grabador (afinidad) o al disco del buffer |
| `CreateContainerConfigError` | Falta el Secret `quinor-env` o el ConfigMap `aws-certs` |
| `OOMKilled` | El pod paso su limite de memoria (YOLO: 3 Gi) |
| api en `CrashLoopBackOff` | Revisar `DATABASE_URL` y que Lightsail acepte la IP del cluster |

## Cambios respecto al compose

- Las imagenes se construyeron con `target: dev`. Los pods usan el codigo que va
  dentro de la imagen; no hay montajes de carpetas ni `--reload`.
- Los pesos de YOLO van dentro de la imagen (`/code/modelos/sacos.pt`).
- `yolo` y `vlm` no reciben el Secret completo, solo sus claves.
- `grabador` usa estrategia `Recreate` para no tener dos grabando a la vez.
- Sin MariaDB ni MinIO: la base es MySQL en Lightsail y los clips van a S3.
- Redis (HU-17) no se despliega.

## Para ahorrar credito

```powershell
..\despliegue_azure\03_apagar_o_eliminar.ps1 detener
```

Para borrar solo estos objetos: `kubectl delete -k .`
