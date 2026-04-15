import os
import subprocess
import logging

from .base import TranscriptionService

logger = logging.getLogger(__name__)


class WhisperLocalService(TranscriptionService):
    """
    Transcription via a local whisper.cpp binary (whisper.exe / whisper).
    Expects a ggml model file and supports --output-txt mode.
    """

    def __init__(
        self,
        model_path: str,
        exe_path: str,
        language: str = "ru",
        timeout: int | None = None,
        vad: bool = False,
        vad_model: str = "",
        vad_threshold: str = "",
        vad_min_silence_ms: str = "",
        vad_speech_pad_ms: str = "",
    ):
        self.model_path = model_path
        self.exe_path = exe_path
        self.language = language
        self.timeout = timeout
        self.vad = vad
        self.vad_model = vad_model
        self.vad_threshold = vad_threshold
        self.vad_min_silence_ms = vad_min_silence_ms
        self.vad_speech_pad_ms = vad_speech_pad_ms

        if self.vad and not self.vad_model:
            raise ValueError(
                "WHISPER_VAD is enabled but WHISPER_VAD_MODEL is empty. "
                "Download a Silero VAD model (e.g. ggml-silero-v6.2.0.bin) and set the path."
            )

    def transcribe(self, wav_path: str) -> str:
        if not self.model_path or not self.exe_path:
            return "[Whisper not configured: set WHISPER_MODEL_PATH and WHISPER_EXE]"

        output_base = os.path.splitext(wav_path)[0]
        cmd = [
            self.exe_path,
            "-m", self.model_path,
            "-f", wav_path,
            "-l", self.language,
            "--no-prints",
            "--output-txt",
            "--output-file", output_base,
        ]
        if self.vad:
            cmd += ["--vad", "--vad-model", self.vad_model]
            if self.vad_threshold:
                cmd += ["--vad-threshold", self.vad_threshold]
            if self.vad_min_silence_ms:
                cmd += ["--vad-min-silence-duration-ms", self.vad_min_silence_ms]
            if self.vad_speech_pad_ms:
                cmd += ["--vad-speech-pad-ms", self.vad_speech_pad_ms]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
            )
            txt_path = output_base + ".txt"
            if result.returncode == 0 and os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    text = f.read().strip()
                os.unlink(txt_path)
                return text
            logger.warning("Whisper non-zero exit: %s", result.stderr.strip())
            return f"[Whisper error: {result.stderr.strip()}]"
        except subprocess.TimeoutExpired:
            return "[Whisper timed out]"
        except Exception as e:
            logger.exception("Whisper exception")
            return f"[Whisper exception: {e}]"
