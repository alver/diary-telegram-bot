from abc import ABC, abstractmethod


class TranscriptionService(ABC):
    """Abstract base for transcription backends."""

    @abstractmethod
    def transcribe(self, wav_path: str) -> str:
        """Transcribe a 16kHz mono WAV file. Returns plain text."""
