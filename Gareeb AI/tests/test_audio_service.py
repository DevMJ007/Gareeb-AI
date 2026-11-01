"""Voice recognition tests that do not require a live microphone."""

from types import SimpleNamespace

import pytest

from services.audio_service import AudioService


class FakeWhisper:
    def __init__(self):
        self.options = None

    def transcribe(self, audio, **options):
        self.options = options
        segments = [SimpleNamespace(text=" Open Notepad")]
        info = SimpleNamespace(language="en", language_probability=0.99)
        return iter(segments), info


@pytest.mark.parametrize(("language", "expected"), [("en", "en"), ("auto", None)])
def test_transcription_uses_selected_language_and_stronger_decoding(language, expected):
    spoken = []
    service = AudioService(text_sink=spoken.append)
    service.set_recognition_language(language)
    whisper = FakeWhisper()
    service._whisper = whisper

    # One second of 16 kHz mono silence is sufficient input for this mocked test.
    service._transcribe([b"\x00\x00" * service.SAMPLE_RATE])

    assert spoken == ["Open Notepad"]
    assert whisper.options == {
        "language": expected,
        "beam_size": 3,
        "vad_filter": True,
        "condition_on_previous_text": False,
    }
    assert service.state.is_processing is False


def test_too_short_recording_returns_clear_voice_error():
    events = []
    service = AudioService(audio_event_callback=lambda name, data: events.append((name, data)))
    whisper = FakeWhisper()
    service._whisper = whisper

    service._transcribe([b"\x00\x00" * 100])

    assert whisper.options is None
    assert any(name == "voice_error" for name, _ in events)
    assert service.state.is_processing is False
