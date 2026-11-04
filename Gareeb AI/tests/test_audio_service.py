"""Voice recognition tests that do not require a live microphone."""

from types import SimpleNamespace
import threading

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


def test_tts_word_events_are_emitted_by_single_engine_worker_thread():
    events = []
    finished = threading.Event()
    connected = threading.Event()
    engine_threads = []

    class FakeEngine:
        def connect(self, event, callback):
            engine_threads.append(threading.get_ident())
            assert event == "started-word"
            self.word_callback = callback
            connected.set()

        def setProperty(self, _name, _value):
            engine_threads.append(threading.get_ident())

        def say(self, text):
            engine_threads.append(threading.get_ident())
            self.text = text
            self.busy = True

        def startLoop(self, _external):
            engine_threads.append(threading.get_ident())

        def isBusy(self):
            return self.busy

        def iterate(self):
            engine_threads.append(threading.get_ident())
            self.word_callback("Hello", 0, 5)
            self.busy = False

        def endLoop(self):
            engine_threads.append(threading.get_ident())

        def stop(self):
            engine_threads.append(threading.get_ident())

    engine = FakeEngine()

    def on_event(name, data):
        events.append((name, data))
        if name == "speech_finished":
            finished.set()

    service = AudioService(audio_event_callback=on_event)
    service._running = True

    def init_engine():
        service._tts_engine = engine
        return True

    service._init_tts = init_engine
    worker = threading.Thread(target=service._tts_loop, name="test-mj-tts")
    worker.start()
    assert connected.wait(1.0)
    assert service.speak("Hello MJ")
    assert finished.wait(1.0)
    service._running = False
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert {name for name, _ in events} >= {
        "voice_state", "speech_started", "speech_progress", "speech_finished"
    }
    progress = [data for name, data in events if name == "speech_progress"]
    assert progress[0]["word"] == "Hello"
    assert progress[0]["level"] > 0.0
    assert progress[-1]["level"] == 0.0
    assert len(set(engine_threads)) == 1
