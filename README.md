# JobFinder CV Studio

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Ruzafan/JobFinder)

Servicio web local (y listo para Docker) para gestionar tu **CV Base**, analizar ofertas de empleo (por **URL** o texto), detectar **palabras clave ATS**, preguntarte por puntos dudosos **guardando tus respuestas en una memoria persistente**, y generar un **CV adaptado honesto** sin inventar ni exagerar nada, listo para exportar a **PDF (ATS)** y **Word (.docx)**.

Accesible desde cualquier ordenador o teléfono dentro de tu misma red Wi-Fi.

## Inicio rápido con Docker (Recomendado)

```bash
docker compose up -d --build
```

Luego abre en tu navegador:
- En este PC: `http://localhost:8000`
- Desde el móvil u otro PC en la misma Wi-Fi: `http://<TU_IP_LOCAL>:8000` (la app te muestra tu enlace y un código QR en el botón **Conectar móvil**).

Los datos (tu CV base, memoria persistente, historial y configuración) se guardan en la carpeta `./data/jobfinder.db`.

## Ejecución local sin Docker (Python)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Proveedores de IA soportados

Desde la pestaña **Configuración** puedes cambiar en cualquier momento entre:
1. **Modo Local Inteligente** (activado por defecto, sin API key, 100% privado).
2. **Google Gemini** (`gemini-2.5-flash` — muy rápido y con capa gratuita en Google AI Studio).
3. **OpenAI** (`gpt-4o-mini` / `gpt-4o`).
4. **Anthropic Claude** (`claude-3-5-sonnet-latest`).
5. **Ollama / LM Studio** (modelos 100% locales en tu PC).
