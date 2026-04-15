from .base import TranscriptionService
from .whisper_local import WhisperLocalService
import config


def get_transcription_service() -> TranscriptionService:
    """Factory: return the configured transcription backend."""
    name = config.TRANSCRIPTION_SERVICE.lower()
    if name == "whisper_local":
        return WhisperLocalService(
            model_path=config.WHISPER_MODEL_PATH,
            exe_path=config.WHISPER_EXE,
            language=config.WHISPER_LANG,
            timeout=config.WHISPER_TIMEOUT,
            vad=config.WHISPER_VAD,
            vad_model=config.WHISPER_VAD_MODEL,
            vad_threshold=config.WHISPER_VAD_THRESHOLD,
            vad_min_silence_ms=config.WHISPER_VAD_MIN_SILENCE_MS,
            vad_speech_pad_ms=config.WHISPER_VAD_SPEECH_PAD_MS,
        )
    raise ValueError(f"Unknown transcription service: {name!r}")
