"""Carga de audio en cualquier formato (wav, mp3, m4a, notas de voz de WhatsApp...)."""
import subprocess


def buscar_ffmpeg():
    """Ruta al ffmpeg portátil de imageio-ffmpeg. No se agrega al PATH a propósito: si Gradio
    ve un ffmpeg en el PATH, intenta usar también ffprobe, que este paquete no trae."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


FFMPEG = buscar_ffmpeg()


def cargar_audio(ruta, sr=24000):
    """Devuelve (numpy float32 mono, sr) remuestreado a `sr`."""
    import numpy as np
    import soundfile as sf

    try:
        data, sr_in = sf.read(ruta, dtype="float32", always_2d=True)
        data = data.mean(axis=1)
        if sr_in != sr:
            import librosa

            data = librosa.resample(data, orig_sr=sr_in, target_sr=sr)
        return data.astype("float32"), sr
    except Exception:
        if not FFMPEG:
            raise
    crudo = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(ruta), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(crudo, dtype="float32").copy(), sr
