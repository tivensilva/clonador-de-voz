r"""Clona tu voz con OmniVoice y la hace decir lo que quieras (versión de línea de comandos).

Ejemplos:
  clonar.bat --ref mis_audios\yo.wav --ref-texto "Lo que digo en el audio" --texto "Hola, soy tu clon"
  clonar.bat --ref mis_audios\yo.wav --ref-texto "..." --guardar-voz mis_voces\yo.pt --frases frases_ejemplo.txt
  clonar.bat --voz mis_voces\yo.pt --texto "Ya no necesito el audio de referencia"
"""
import argparse
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def leer_frases(args):
    frases = []
    for t in args.texto or []:
        frases.append((None, t))
    if args.frases:
        with open(args.frases, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea or linea.startswith("#"):
                    continue
                if "|" in linea:
                    nombre, texto = (p.strip() for p in linea.split("|", 1))
                    frases.append((nombre, texto))
                else:
                    frases.append((None, linea))
    return frases


def nombre_archivo(i, nombre, texto):
    base = nombre or "_".join(re.findall(r"\w+", texto.lower())[:5]) or "frase"
    return f"{i:02d}_{base}.wav"


def cargar_referencia(ruta):
    from audio_util import cargar_audio

    if not os.path.isfile(ruta):
        sys.exit(f"No encuentro el audio de referencia: {ruta}")
    try:
        wav, sr = cargar_audio(ruta)
    except Exception:
        sys.exit(f"No pude leer {ruta}. Prueba con otro formato (.wav, .mp3, .m4a, .ogg).")
    dur = len(wav) / sr
    if dur < 3:
        print(f"Ojo: la referencia dura {dur:.1f} s; con menos de 3 s el clon sale flojo.")
    elif dur > 12:
        print(f"Ojo: la referencia dura {dur:.1f} s; recórtala a 3-10 s para mejores resultados.")
    return wav, sr


def main():
    p = argparse.ArgumentParser(description="Clonador de voz con OmniVoice (todo local).")
    voz = p.add_argument_group("de qué voz")
    voz.add_argument("--ref", help="Audio de 3-10 s con TU voz, limpio y sin ruido (wav, mp3, m4a, WhatsApp...).")
    voz.add_argument("--ref-texto", help="Lo que dices exactamente en el audio de referencia.")
    voz.add_argument("--voz", help="Voz guardada antes con --guardar-voz (.pt). Reemplaza --ref y --ref-texto.")
    voz.add_argument("--guardar-voz", help="Guarda la voz en este .pt para reusarla sin el audio.")
    que = p.add_argument_group("qué decir")
    que.add_argument("--texto", action="append", help="Frase a decir. Puedes repetir --texto varias veces.")
    que.add_argument("--frases", help="Archivo .txt con una frase por línea (opcional: 'nombre | frase').")
    aj = p.add_argument_group("ajustes")
    aj.add_argument("--salida", default="salida", help="Carpeta donde quedan los .wav (por defecto: salida).")
    aj.add_argument("--idioma", default="spanish", help="Idioma del texto (por defecto: spanish).")
    aj.add_argument("--velocidad", type=float, default=1.0, help="1.0 normal, 0.8 más lento, 1.2 más rápido.")
    aj.add_argument("--semilla", type=int, default=7, help="Si una frase sale rara, prueba otra semilla.")
    aj.add_argument("--pasos", type=int, default=32, help="Más pasos = algo mejor y más lento (por defecto 32).")
    aj.add_argument("--cpu", action="store_true", help="Forzar CPU aunque haya GPU (lento).")
    args = p.parse_args()

    if not args.voz and not (args.ref and args.ref_texto):
        p.error("necesito --voz, o bien --ref junto con --ref-texto.")
    frases = leer_frases(args)
    if not frases and not args.guardar_voz:
        p.error("no hay nada que decir: usa --texto o --frases.")
    ref = cargar_referencia(args.ref) if args.ref else None

    import soundfile as sf
    import torch
    from omnivoice import OmniVoice
    from omnivoice.models.omnivoice import OmniVoiceGenerationConfig, VoiceClonePrompt

    usar_gpu = torch.cuda.is_available() and not args.cpu
    print("Cargando el modelo en", torch.cuda.get_device_name(0) if usar_gpu else "CPU", "...")
    model = OmniVoice.from_pretrained(
        "k2-fsa/OmniVoice",
        device_map="cuda:0" if usar_gpu else "cpu",
        dtype=torch.float16 if usar_gpu else torch.float32,
    )

    if args.voz:
        prompt = VoiceClonePrompt.load(args.voz)
    else:
        wav, sr = ref
        prompt = model.create_voice_clone_prompt(ref_audio=(torch.from_numpy(wav), sr), ref_text=args.ref_texto)
    if args.guardar_voz:
        os.makedirs(os.path.dirname(os.path.abspath(args.guardar_voz)), exist_ok=True)
        prompt.save(args.guardar_voz)
        print("Voz guardada en", args.guardar_voz)

    os.makedirs(args.salida, exist_ok=True)
    config = OmniVoiceGenerationConfig(num_step=args.pasos)
    for i, (nombre, texto) in enumerate(frases, 1):
        t0 = time.time()
        torch.manual_seed(args.semilla)
        audio = model.generate(
            text=texto,
            voice_clone_prompt=prompt,
            language=args.idioma,
            speed=args.velocidad,
            generation_config=config,
        )
        destino = os.path.join(args.salida, nombre_archivo(i, nombre, texto))
        sf.write(destino, audio[0], 24000)
        print(f"[{i}/{len(frases)}] {destino}  ({time.time() - t0:.0f} s)")

    if frases:
        print("\nListo. Los audios están en:", os.path.abspath(args.salida))


if __name__ == "__main__":
    main()
