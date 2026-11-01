"""Configuration manager tests (PRD section 12)."""
import json
import pytest

from core.config_manager import ConfigManager


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "cfg" / "config.json"
    return ConfigManager(config_file=str(path))


class TestConfigBasics:
    def test_defaults_created(self, cfg):
        # First run writes defaults.
        assert cfg.config_file.exists()
        audio = cfg.get_audio_config()
        assert audio.push_to_talk_enabled is True
        assert audio.language == "en"
        assert audio.microphone_allowed is False  # privacy-first default
        assert audio.screen_capture_allowed is False

    def test_ai_defaults(self, cfg):
        ai = cfg.get_ai_config()
        assert ai.model_name
        assert ai.unload_on_idle is True
        assert 1 <= ai.idle_timeout_minutes <= 120

    def test_ui_defaults(self, cfg):
        ui = cfg.get_ui_config()
        assert ui.window_width >= 400
        assert ui.companion_name

    def test_automation_defaults(self, cfg):
        auto = cfg.get_automation_config()
        assert auto.confirm_destructive_actions is True
        assert auto.restrict_to_user_folders is True
        assert auto.allowed_applications  # non-empty allow-list

    def test_memory_defaults(self, cfg):
        mem = cfg.get_memory_config()
        assert mem.storage_backend == "sqlite"
        assert mem.max_conversations > 0


class TestConfigGetSet:
    def test_set_get(self, cfg):
        cfg.set("audio", "tts_speed", 1.5)
        assert cfg.get("audio", "tts_speed") == 1.5

    def test_get_default(self, cfg):
        assert cfg.get("nope", "nothing", "fallback") == "fallback"

    def test_set_section_roundtrip(self, cfg):
        section = {"model_name": "tinyllama", "ollama_url": "http://x:1"}
        cfg.set_section("ai", section)
        ai = cfg.get_ai_config()
        assert ai.model_name == "tinyllama"

    def test_persistence_across_instances(self, tmp_path):
        path = tmp_path / "c2.json"
        c1 = ConfigManager(config_file=str(path))
        c1.set("ui", "companion_name", "Robo")
        c1.save()

        c2 = ConfigManager(config_file=str(path))
        assert c2.get_ui_config().companion_name == "Robo"

    def test_corrupt_file_recovers(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not valid json!!!", encoding="utf-8")
        c = ConfigManager(config_file=str(path))
        # Falls back to defaults and rewrites a valid file.
        assert c.get_audio_config().push_to_talk_enabled is True
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "audio" in data

    def test_saved_file_is_valid_json(self, cfg):
        cfg.set("test", "k", 123)
        data = json.loads(cfg.config_file.read_text(encoding="utf-8"))
        assert data["test"]["k"] == 123
