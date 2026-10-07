# Guía de puesta en marcha (para hacerlo sin ayuda)

Esta guía te lleva de cero a tener el bot funcionando en tu computadora. Sigue los pasos **en orden** y no te saltes las comprobaciones: cada una te dice si puedes pasar al siguiente paso.

## Qué es cada archivo

| Archivo | Para qué sirve |
|---|---|
| `sql/schema.sql` | Crea la tabla y la función de búsqueda en Supabase (**ya lo ejecutaste**). |
| `ingest.py` | Lee tus documentos (.txt, .md, .pdf), los parte en fragmentos y los guarda en Supabase con sus embeddings. |
| `main.py` | La API: recibe mensajes, busca en Supabase, pregunta a GPT-4o y responde. También sirve el widget en `/`. |
| `tools.py` | Herramientas que el bot puede usar (consultar pedido, escalar a humano). Los pedidos son **datos de ejemplo**. |
| `escalation.py` | Envía el aviso (webhook) cuando se escala a un humano. |
| `index.html` | El widget de chat flotante. |
| `tests/` | Pruebas automáticas (no necesitan claves). |
| `.env` | Tus claves secretas (lo creas tú, **nunca se sube a GitHub**). |

---

## 0. Antes de empezar

Necesitas:

- **Git**: git-scm.com
- **Python 3.10 o superior**: python.org (en Windows marca *"Add Python to PATH"* al instalar)
- **Una cuenta de OpenAI con saldo**: platform.openai.com → Billing. Sin saldo, las llamadas fallan.
- **El proyecto de Supabase** donde ya ejecutaste `schema.sql`.

Comprueba en la terminal:

```
git --version
python --version
```

> En Windows a veces es `py --version`; en Mac/Linux, `python3 --version`. Usa el que funcione en **todos** los comandos de abajo.

**Cómo abrir la terminal:** en Windows busca "PowerShell"; en Mac abre "Terminal".

---

## 1. Descargar el proyecto

```
cd Documents
git clone https://github.com/angelor256/Inter-Tool.git
cd Inter-Tool
```

Comprueba con `dir` (Windows) o `ls` (Mac/Linux) que ves `main.py`, `ingest.py`, `index.html`, etc.

> Si no ves esos archivos, estás en la rama equivocada. Ejecuta `git branch -a` y `git checkout Main`.

> Si no tienes Git: en GitHub pulsa **Code → Download ZIP**, descomprime y abre la terminal dentro de esa carpeta.

---

## 2. Crear el entorno e instalar dependencias

```
python -m venv .venv
```

Actívalo:

- **Windows (PowerShell):** `.venv\Scripts\activate`
- **Mac/Linux:** `source .venv/bin/activate`

Cuando funcione, verás `(.venv)` al inicio de la línea. Luego:

```
pip install -r requirements.txt
```

> Si en Windows sale un error de *"la ejecución de scripts está deshabilitada"*, ejecuta una vez
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y vuelve a activar el entorno.

> **Cada vez que abras una terminal nueva** tienes que volver a activar el entorno (`.venv\Scripts\activate`).

---

## 3. Comprobación sin claves: ejecutar los tests

```
pip install pytest
python -m pytest tests
```

Debe terminar con **`15 passed`**. Si pasa, el código y el entorno están bien. Si falla, copia el error y revísalo antes de seguir.

---

## 4. Crear el archivo `.env` con tus claves

Copia el ejemplo:

- **Windows:** `copy .env.example .env`
- **Mac/Linux:** `cp .env.example .env`

Abre `.env` con el Bloc de notas y rellénalo así (sin comillas ni espacios alrededor del `=`):

```
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://xxxxxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
ESCALATION_WEBHOOK_URL=
CORS_ORIGINS=
```

Dónde sacar cada valor:

| Variable | Dónde |
|---|---|
| `OPENAI_API_KEY` | platform.openai.com → API keys → Create new secret key |
| `SUPABASE_URL` | Supabase → Project Settings → API → **Project URL** |
| `SUPABASE_SERVICE_KEY` | Supabase → Project Settings → API → clave **service_role** (**no** la `anon`) |

`ESCALATION_WEBHOOK_URL` y `CORS_ORIGINS` déjalas vacías por ahora.

> **Seguridad:** la clave `service_role` da acceso total a tu base de datos. No la pegues en chats, capturas ni en GitHub. El archivo `.gitignore` ya evita que `.env` se suba, pero comprueba con `git status` que `.env` **no** aparece en la lista.
> Si alguna clave se filtra, genérala de nuevo en su panel y actualiza `.env`.

---

## 5. Cargar documentos (ingesta)

Crea una carpeta `docs` y dentro un archivo `faq.txt` con **contenido que conozcas bien**. Ejemplo para copiar:

```
Política de devoluciones: puedes devolver cualquier producto en un plazo de 30 días desde la entrega,
siempre que esté sin usar y en su embalaje original. El reembolso se realiza en 5 a 7 días hábiles
al mismo método de pago.

Envíos: el envío estándar tarda de 3 a 5 días hábiles y cuesta 4,99 euros. Los pedidos superiores
a 50 euros tienen envío gratis.

Horario de atención: de lunes a viernes, de 9:00 a 18:00 horas.

Métodos de pago: aceptamos tarjeta de crédito, débito y PayPal.
```

Ejecuta:

```
python ingest.py docs/
```

Debe mostrar algo como `faq.txt -> 1 chunks` y `Ingesta terminada`. (Un texto corto da 1 fragmento; un PDF largo, muchos.)

**Comprobación:** en el SQL Editor de Supabase:

```sql
select count(*) from documents;
```

Debe dar un número mayor que 0. Puedes reejecutar la ingesta del mismo archivo sin problema: reemplaza los fragmentos anteriores en vez de duplicarlos.

---

## 6. Arrancar la API y abrir el widget

```
uvicorn main:app --reload
```

Deja esa terminal abierta (es el servidor). Abre en el navegador:

- **`http://localhost:8000`** → el widget de chat (botón abajo a la derecha).
- `http://localhost:8000/docs` → documentación interactiva de la API.
- `http://localhost:8000/health` → debe mostrar `{"status":"ok"}`.

> Abre siempre el widget desde `http://localhost:8000`, no con doble clic sobre `index.html`.

Para parar el servidor: `Ctrl + C`.

---

## 7. Qué probar (y qué debe pasar)

Escribe estas preguntas en el widget, una por una, **en la misma conversación**:

| Pregunta | Resultado esperado |
|---|---|
| `¿Cuántos días tengo para devolver un producto?` | Responde 30 días (viene del documento). Sin banner. |
| `¿Cuánto cuesta el envío?` | 4,99 €, gratis sobre 50 €. |
| `¿Y tarda mucho?` | Debe entender que hablas del envío (usa el historial) y decir 3 a 5 días. |
| `¿Dónde está mi pedido A1002?` | Usa la herramienta: "Enviado" con DHL (datos de ejemplo). |
| `¿Y el A1001?` | "En preparación". |
| `¿Cuál es la capital de Francia?` | **"No tengo esa información"** + banner de transferencia a humano. |
| `Quiero hablar con una persona` | Confirma la derivación + banner de transferencia. |

Pedidos de ejemplo disponibles: `A1001` (en preparación), `A1002` (enviado, DHL), `A1003` (entregado).

**Mira la terminal del servidor mientras pruebas.** Cada mensaje imprime una línea así:

```
INFO chat session=... scores=[0.82, 0.41, 0.38] relevantes=1
```

Ahí ves el score real de cada fragmento. Solo los de **0.75 o más** cuentan como relevantes.

---

## 8. (Opcional) Probar el aviso al agente humano

1. Entra en **webhook.site**: te da una URL única y gratuita.
2. Pega esa URL en `.env`: `ESCALATION_WEBHOOK_URL=https://webhook.site/xxxx`
3. Reinicia el servidor (`Ctrl + C` y `uvicorn main:app --reload`).
4. Escribe en el widget `Quiero hablar con una persona`.
5. En webhook.site verás llegar un POST con el motivo, el último mensaje y la conversación.

Para Slack: crea un *Incoming Webhook* en tu workspace y pega su URL. Se avisa **una sola vez por conversación**.

---

## 9. Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Falta la variable de entorno ...` | `.env` mal ubicado o con nombre erróneo | Debe llamarse exactamente `.env` y estar en la carpeta del proyecto |
| El bot **siempre** dice "No tengo esa información" | Los scores quedan bajo 0.75 | Mira la línea `scores=[...]` en la terminal. Si los buenos están en 0.55–0.74, baja `SIMILARITY_THRESHOLD` en `main.py` (prueba 0.6) |
| Todo se escala a humano, incluso un "hola" | Un saludo no tiene contexto = baja confianza | Pon `ESCALATE_ON_LOW_CONFIDENCE=false` en `.env` |
| Error `401` / `invalid_api_key` | Clave de OpenAI mal copiada | Genera otra y revisa que no tenga espacios |
| Error `429` / `insufficient_quota` | Sin saldo en OpenAI | Añade crédito en Billing |
| Widget responde "Ha ocurrido un problema..." | La API devolvió error (502) | Mira el traceback en la terminal del servidor |
| `Could not find the function public.match_documents` | El SQL no se aplicó | Vuelve a ejecutar `sql/schema.sql` completo en Supabase |
| `expected 1536 dimensions` | El modelo de embeddings no coincide con la tabla | No cambies `text-embedding-3-small` sin cambiar `vector(1536)` |
| Error de permisos / RLS al ingerir | Usaste la clave `anon` | Usa la `service_role` en `SUPABASE_SERVICE_KEY` |
| El widget no tiene estilos | El navegador no carga `cdn.tailwindcss.com` | Comprueba tu conexión; las redes de empresa suelen bloquearlo |
| `python` no se reconoce | Python no está en el PATH | Usa `py`, o reinstala marcando *Add Python to PATH* |
| El puerto 8000 está ocupado | Otro programa lo usa | `uvicorn main:app --reload --port 8001` y abre `localhost:8001` |

---

## 10. Cosas que debes saber antes de usarlo con clientes reales

- **Los pedidos son datos de ejemplo** (`tools.py`). Antes de producción hay que conectarlos a tu sistema real **y verificar que el pedido pertenece al cliente que pregunta**; si no, cualquiera podría ver pedidos ajenos adivinando números.
- **El historial vive en memoria**: se pierde al reiniciar el servidor y no sirve con varios procesos. Para producción habría que moverlo a Redis o Supabase.
- **La API no tiene autenticación ni límite de peticiones**: cualquiera que conozca la URL puede gastar tu saldo de OpenAI. Añádelos antes de publicarla en internet.
- **Costes:** cada mensaje genera una llamada de embedding (muy barata) y una a GPT-4o (la que más cuesta). Vigila el consumo en el panel de OpenAI.
- **Aviso de privacidad:** las conversaciones y el contenido de tus documentos se envían a OpenAI.

---

## Resumen rápido (una vez ya instalado)

```
cd Documents/Inter-Tool
.venv\Scripts\activate            # Mac/Linux: source .venv/bin/activate
python ingest.py docs/            # solo cuando cambies documentos
uvicorn main:app --reload         # y abrir http://localhost:8000
```
