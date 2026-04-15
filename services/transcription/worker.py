import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from services import audio as audio_svc

from .base import TranscriptionService

logger = logging.getLogger(__name__)


class TranscriptionWorker:
    """
    Owns a single-worker thread pool so CPU-heavy ffmpeg+whisper jobs are serialized
    rather than competing for cores. Async callers await transcribe_file(); the
    underlying work runs in the dedicated thread.
    """

    def __init__(self, service: TranscriptionService):
        self.service = service
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="transcribe",
        )

    async def transcribe_file(self, audio_path: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._work, audio_path)

    def _work(self, audio_path: str) -> str:
        wav = audio_svc.convert_to_wav_16k_mono(audio_path)
        if not wav:
            return "[Audio conversion failed]"
        return self.service.transcribe(wav)

    def shutdown(self) -> None:
        logger.info("Shutting down transcription worker...")
        self._executor.shutdown(wait=True)
