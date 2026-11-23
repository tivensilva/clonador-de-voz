"""Clonador de voz: interfaz web local con OmniVoice.

Se abre con abrir.bat (o el acceso directo del escritorio). Todo corre en este PC.
"""
import json
import os
import re
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import gradio as gr

from audio_util import cargar_audio

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "salida"
VOCES = AQUI / "mis_voces"
SR = 24000

FRASES = [
    "Abrí la nevera tres veces en cinco minutos, por si la comida se había reproducido sola. [sigh] No, no se reprodujo.",
    "Señoras y señores, el gato acaba de tumbar un vaso, me miró a los ojos, y tumbó otro. Esto ya es personal.",
    "Hoy fui al gimnasio. Bueno, pasé por el frente. Bueno, lo vi en una foto. Cuenta, ¿cierto?",
    "Pongo cinco alarmas para levantarme temprano y las apago todas con una precisión de francotirador. [laughter]",
    "Empiezo la dieta el lunes. ¿Cuál lunes? No sé, uno de esos, ya veremos.",
    "Este mensaje de voz va a durar treinta segundos. [laughter] Mentira, son once minutos y no llego a ningún punto.",
    "Se fue el internet y descubrí que en esta casa vive más gente. Muy amables, por cierto.",
    "Hola, soy el clon. El original está durmiendo. Yo me encargo de contestar los correos y de comerme las galletas.",
]
IDIOMAS = {"Español": "spanish", "English": "english", "Português": "portuguese", "Français": "french", "Italiano": "italian"}
CALIDAD = {"⚡ Rápida": 16, "🎯 Normal": 32, "💎 Alta": 48}
NUEVA = "➕ Nueva voz (grabar o subir)"


# ---------- Modelos (se cargan en segundo plano para que la página abra al instante) ----------
estado = {"modelo": None, "error": None, "dispositivo": "…"}
_whisper = {"m": None}
_lock = threading.Lock()
_cache_voz = {}


def cargar_modelo():
    try:
        import torch
        from omnivoice import OmniVoice

        gpu = torch.cuda.is_available() and os.environ.get("CLONADOR_CPU") != "1"
        estado["dispositivo"] = torch.cuda.get_device_name(0) if gpu else "CPU"
        estado["modelo"] = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map="cuda:0" if gpu else "cpu",
            dtype=torch.float16 if gpu else torch.float32,
        )
        print(f"Modelo listo en {estado['dispositivo']}.", flush=True)
    except Exception as e:  # se muestra en la interfaz
        estado["error"] = str(e)
        print("Error cargando el modelo:", e, flush=True)


hilo_modelo = threading.Thread(target=cargar_modelo, daemon=True)


def esperar_modelo(progress):
    if not estado["modelo"] and not estado["error"]:
        progress(0, desc="Cargando el modelo (solo al abrir la app)…")
        hilo_modelo.join()
    if estado["error"]:
        raise gr.Error(f"No se pudo cargar el modelo: {estado['error']}")
    return estado["modelo"]


def texto_estado():
    if estado["error"]:
        return "<span class='pill err'>⛔ Error al cargar el modelo</span>"
    if estado["modelo"]:
        return f"<span class='pill ok'>● Listo · {estado['dispositivo']}</span>"
    return "<span class='pill wait'>◌ Cargando el modelo…</span>"


# ---------- Lógica ----------
def lista_voces():
    VOCES.mkdir(exist_ok=True)
    return [NUEVA] + sorted(p.stem for p in VOCES.glob("*.pt"))


def nombre_seguro(s):
    s = re.sub(r"[^\w\- ]", "", s, flags=re.UNICODE).strip()
    return s[:40]


def obtener_voz(modelo, voz, audio, ref_texto):
    from omnivoice.models.omnivoice import VoiceClonePrompt
    import torch

    if voz and voz != NUEVA:
        return VoiceClonePrompt.load(str(VOCES / f"{voz}.pt"))
    if not audio:
        raise gr.Error("Primero graba o sube un audio con tu voz (paso 1).")
    if not (ref_texto or "").strip():
        raise gr.Error("Escribe lo que dices en el audio, o dale a «✨ Transcribir».")
    clave = (audio, os.path.getmtime(audio), ref_texto.strip())
    if clave not in _cache_voz:
        wav, sr = cargar_audio(audio)
        _cache_voz.clear()
        _cache_voz[clave] = modelo.create_voice_clone_prompt(
            ref_audio=(torch.from_numpy(wav), sr), ref_text=ref_texto.strip()
        )
    return _cache_voz[clave]


def transcribir(audio, idioma, progress=gr.Progress()):
    if not audio:
        raise gr.Error("Primero graba o sube un audio.")
    if _whisper["m"] is None:
        progress(0, desc="Preparando el transcriptor (la primera vez tarda un poco)…")
        from faster_whisper import WhisperModel

        _whisper["m"] = WhisperModel("small", device="cpu", compute_type="int8")
    progress(0.5, desc="Escuchando…")
    wav, _ = cargar_audio(audio, sr=16000)
    lang = {"spanish": "es", "english": "en", "portuguese": "pt", "french": "fr", "italian": "it"}[IDIOMAS[idioma]]
    segs, _ = _whisper["m"].transcribe(wav, language=lang)
    texto = " ".join(s.text.strip() for s in segs).strip()
    if not texto:
        raise gr.Error("No se entendió nada en el audio. Prueba con uno más claro.")
    return texto


CONSEJO = "<span class='hint'>💡 Habla normal y sin ruido de fondo. Sirven las notas de voz de WhatsApp.</span>"


def info_audio(audio):
    if not audio:
        return CONSEJO
    try:
        wav, sr = cargar_audio(audio)
    except Exception:
        return "<span class='hint err'>No pude leer ese audio. Prueba con otro formato.</span>"
    d = len(wav) / sr
    if d < 3:
        return f"<span class='hint warn'>⏱️ {d:.1f} s — muy corto, intenta 3 a 10 s.</span>"
    if d > 12:
        return f"<span class='hint warn'>⏱️ {d:.1f} s — algo largo; con 3 a 10 s sale mejor.</span>"
    return f"<span class='hint ok'>⏱️ {d:.1f} s — perfecto.</span>"


def generar(voz, audio, ref_texto, texto, idioma, velocidad, calidad, variacion, historial,
            progress=gr.Progress()):
    import soundfile as sf
    import torch
    from omnivoice.models.omnivoice import OmniVoiceGenerationConfig

    texto = (texto or "").strip()
    if not texto:
        raise gr.Error("Escribe qué quieres que diga tu clon (paso 2).")
    modelo = esperar_modelo(progress)
    progress(0.2, desc="Preparando tu voz…")
    with _lock:
        prompt = obtener_voz(modelo, voz, audio, ref_texto)
        progress(0.4, desc="Hablando… 🎙️")
        torch.manual_seed(int(variacion))
        t0 = time.time()
        wav = modelo.generate(
            text=texto, voice_clone_prompt=prompt, language=IDIOMAS[idioma], speed=float(velocidad),
            generation_config=OmniVoiceGenerationConfig(num_step=CALIDAD[calidad]),
        )[0]
    SALIDA.mkdir(exist_ok=True)
    corto = "_".join(re.findall(r"\w+", texto.lower())[:4]) or "frase"
    ruta = SALIDA / f"{datetime.now():%Y%m%d-%H%M%S}_{corto}.wav"
    sf.write(ruta, wav, SR)
    print(f"Generado en {time.time() - t0:.0f} s → {ruta}", flush=True)
    historial = [{"ruta": str(ruta), "texto": texto}] + (historial or [])
    return str(ruta), historial[:12]


def guardar_voz(nombre, audio, ref_texto, progress=gr.Progress()):
    nombre = nombre_seguro(nombre or "")
    if not nombre:
        raise gr.Error("Ponle un nombre a la voz.")
    modelo = esperar_modelo(progress)
    with _lock:
        prompt = obtener_voz(modelo, NUEVA, audio, ref_texto)
    VOCES.mkdir(exist_ok=True)
    prompt.save(str(VOCES / f"{nombre}.pt"))
    gr.Info(f"Voz «{nombre}» guardada. Ya puedes elegirla sin subir el audio.")
    return gr.update(choices=lista_voces(), value=nombre), ""


def cambiar_voz(voz):
    nueva = voz == NUEVA
    return gr.update(visible=nueva), gr.update(visible=not nueva)


def borrar_voz(voz):
    if voz and voz != NUEVA:
        (VOCES / f"{voz}.pt").unlink(missing_ok=True)
        gr.Info(f"Voz «{voz}» borrada.")
    return gr.update(choices=lista_voces(), value=NUEVA)


# ---------- Interfaz ----------
TEMA = gr.themes.Soft(
    primary_hue="violet",
    secondary_hue="fuchsia",
    neutral_hue="slate",
    radius_size="lg",
    font=["Segoe UI", "system-ui", "-apple-system", "Roboto", "sans-serif"],
).set(
    button_primary_background_fill="linear-gradient(90deg, *primary_500, *secondary_500)",
    button_primary_background_fill_hover="linear-gradient(90deg, *primary_600, *secondary_600)",
    button_primary_text_color="white",
    block_border_width="0px",
    block_shadow="0 1px 3px rgba(15,23,42,.06), 0 8px 24px rgba(15,23,42,.06)",
)

CSS = """
.gradio-container { max-width: 1100px !important; margin: 0 auto !important; }
#hero { text-align: center; padding: 28px 16px 8px; }
#hero h1 { font-size: 2.4rem; font-weight: 800; margin: 0;
  background: linear-gradient(90deg, #7c3aed, #d946ef); -webkit-background-clip: text;
  background-clip: text; color: transparent; }
#hero p { margin: 6px 0 0; opacity: .75; font-size: 1.05rem; }
.paso h3 { margin: 0 0 4px; font-size: 1.1rem; }
.paso .num { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 50%;
  background: linear-gradient(135deg, #7c3aed, #d946ef); color: #fff; font-size: .85rem; margin-right: 8px; }
.pill { display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: .85rem; font-weight: 600; }
.pill.ok { background: rgba(16,185,129,.12); color: #059669; }
.pill.wait { background: rgba(245,158,11,.14); color: #b45309; }
.pill.err { background: rgba(239,68,68,.12); color: #dc2626; }
.hint { font-size: .85rem; } .hint.ok { color: #059669; } .hint.warn { color: #b45309; } .hint.err { color: #dc2626; }
#estado { text-align: center; }
#generar { font-size: 1.15rem !important; min-height: 56px; border: none !important;
  background: linear-gradient(90deg, #7c3aed, #d946ef) !important; color: #fff !important;
  box-shadow: 0 8px 24px rgba(124,58,237,.35); transition: transform .15s ease, box-shadow .15s ease; }
#generar:hover { transform: translateY(-1px); box-shadow: 0 12px 28px rgba(124,58,237,.45); }
.chips button { font-size: .85rem !important; }
#pie { text-align: center; font-size: .8rem; opacity: .6; padding: 18px 0 8px; }
footer { display: none !important; }
"""

with gr.Blocks(title="Clonador de voz") as demo:
    historial = gr.State([])

    gr.HTML("<div id='hero'><h1>🎙️ Clonador de voz</h1>"
            "<p>Graba unos segundos, escribe una frase y escúchate decirla. Todo pasa en tu PC.</p></div>")
    estado_html = gr.HTML(texto_estado(), elem_id="estado")
    reloj = gr.Timer(1.0)

    with gr.Row(equal_height=False):
        # ---- Paso 1 ----
        with gr.Column(scale=1, elem_classes="paso"):
            gr.HTML("<h3><span class='num'>1</span>Tu voz</h3>")
            voz = gr.Dropdown(lista_voces(), value=NUEVA, label="Voz", interactive=True)
            with gr.Group(visible=True) as grupo_nueva:
                audio = gr.Audio(sources=["microphone", "upload"], type="filepath", label="Tu audio (3 a 10 s)")
                duracion = gr.HTML(CONSEJO)
                with gr.Row():
                    ref_texto = gr.Textbox(
                        label="¿Qué dices en ese audio?", placeholder="Escríbelo tal cual o usa ✨ Transcribir",
                        lines=2, scale=4,
                    )
                with gr.Row():
                    btn_transcribir = gr.Button("✨ Transcribir", size="sm")
                with gr.Accordion("💾 Guardar esta voz para la próxima", open=False):
                    with gr.Row():
                        nombre_voz = gr.Textbox(placeholder="Nombre, p. ej. «Yo»", show_label=False, scale=3)
                        btn_guardar = gr.Button("Guardar", size="sm", scale=1)
            with gr.Group(visible=False) as grupo_guardada:
                gr.HTML("<p class='hint ok' style='padding:10px'>✅ Usando una voz guardada. No hace falta audio.</p>")
                btn_borrar = gr.Button("🗑️ Borrar esta voz", size="sm", variant="stop")

        # ---- Paso 2 ----
        with gr.Column(scale=1, elem_classes="paso"):
            gr.HTML("<h3><span class='num'>2</span>¿Qué quieres que diga?</h3>")
            texto = gr.Textbox(
                show_label=False, lines=5, max_lines=10,
                placeholder="Escribe cualquier cosa… o dale a 🎲 para una frase al azar",
            )
            with gr.Row(elem_classes="chips"):
                btn_azar = gr.Button("🎲 Sorpréndeme", size="sm", min_width=0, scale=2)
                btn_risa = gr.Button("😂 Risa", size="sm", min_width=0, scale=1)
                btn_suspiro = gr.Button("😮‍💨 Suspiro", size="sm", min_width=0, scale=1)
            with gr.Accordion("⚙️ Ajustes", open=False):
                idioma = gr.Dropdown(list(IDIOMAS), value="Español", label="Idioma del texto")
                velocidad = gr.Slider(0.7, 1.4, value=1.0, step=0.05, label="Velocidad")
                calidad = gr.Radio(list(CALIDAD), value="🎯 Normal", label="Calidad")
                with gr.Row():
                    variacion = gr.Number(value=7, precision=0, label="Variación (si sale rara, cámbiala)", scale=3)
                    btn_dado = gr.Button("🎲", size="sm", scale=1)
            btn_generar = gr.Button("🎙️ Generar", variant="primary", size="lg", elem_id="generar")
            salida = gr.Audio(label="Resultado", type="filepath", autoplay=True, interactive=False)

    with gr.Accordion("🕘 Historial de esta sesión", open=False):
        @gr.render(inputs=historial)
        def mostrar_historial(items):
            if not items:
                gr.Markdown("_Aquí aparecerán tus audios generados._")
            for it in items:
                gr.Audio(it["ruta"], label=it["texto"][:90], interactive=False)

    gr.HTML("<div id='pie'>Clona solo tu voz · Uso no comercial · Voz sintetizada con OmniVoice (k2-fsa) · "
            f"Tus audios quedan en la carpeta <b>salida</b></div>")

    # ---- Eventos ----
    # Eventos livianos: sin límite, para que la interfaz no se congele mientras se genera
    libre = dict(concurrency_limit=None, show_progress="hidden")
    demo.load(texto_estado, None, estado_html, **libre)
    reloj.tick(lambda: (texto_estado(), gr.Timer(active=not (estado["modelo"] or estado["error"]))),
               outputs=[estado_html, reloj], **libre)
    voz.change(cambiar_voz, voz, [grupo_nueva, grupo_guardada], **libre)
    audio.change(info_audio, audio, duracion, **libre)
    btn_borrar.click(borrar_voz, voz, voz, **libre)
    btn_transcribir.click(transcribir, [audio, idioma], ref_texto, concurrency_id="whisper", concurrency_limit=1)
    btn_guardar.click(guardar_voz, [nombre_voz, audio, ref_texto], [voz, nombre_voz])
    # Botones de texto: se resuelven en el navegador (instantáneos, sin esperar a la cola)
    js_azar = ("(t) => { const f = " + json.dumps(FRASES, ensure_ascii=False) + "; let n;"
               " do { n = f[Math.floor(Math.random() * f.length)]; } while (n === t && f.length > 1); return n; }")
    btn_azar.click(None, texto, texto, js=js_azar)
    btn_risa.click(None, texto, texto, js="(t) => ((t || '').trimEnd() + ' [laughter] ').trimStart()")
    btn_suspiro.click(None, texto, texto, js="(t) => ((t || '').trimEnd() + ' [sigh] ').trimStart()")
    btn_dado.click(None, None, variacion, js="() => Math.floor(Math.random() * 9999) + 1")
    btn_generar.click(
        generar, [voz, audio, ref_texto, texto, idioma, velocidad, calidad, variacion, historial],
        [salida, historial],
    )


def puerto_libre(preferido=8001):
    for p in range(preferido, preferido + 20):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return preferido


if __name__ == "__main__":
    hilo_modelo.start()
    puerto = puerto_libre()
    print(f"\n  Clonador de voz → http://127.0.0.1:{puerto}\n  (Cierra esta ventana para apagarlo)\n", flush=True)
    demo.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=puerto, inbrowser=os.environ.get("CLONADOR_NO_ABRIR") != "1",
        theme=TEMA, css=CSS, show_error=True, footer_links=[],
    )
