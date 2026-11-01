"""AI service parsing tests: tool-call extraction and reply humanizing (FR-03)."""
import json
from types import SimpleNamespace
import pytest

from core.permissions import PermissionManager
import services.ai_service as ai_service_module
from services.ai_service import (
    AIService, InsufficientResources, ModelNotInstalled, OllamaUnavailable,
)


class FakeConfig:
    """Minimal config stand-in for constructing AIService in tests."""

    def get_ai_config(self):
        class AI:
            model_name = "test-model"
            ollama_url = "http://localhost:1"
            auto_load_model = True
            unload_on_idle = True
            idle_timeout_minutes = 5
            max_context_length = 512
            temperature = 0.7
            top_p = 0.9
            top_k = 40
            check_model_on_startup = False
            install_missing_models = False
            model_storage_path = "models"
        return AI()

    def get_audio_config(self):
        class Audio:
            screen_capture_allowed = False
        return Audio()


@pytest.fixture
def ai():
    return AIService(
        config_manager=FakeConfig(),
        resource_monitor=None,
        ai_event_callback=None,
        memory_store=None,
        permissions=PermissionManager(config_manager=None),
        task_planner=None,
    )


TOOL_REPLY = json.dumps({
    "intent": "tool",
    "explanation": "I'll open Notepad for you.",
    "steps": [
        {"action": "open_app", "params": {"app": "notepad"},
         "description": "Open Notepad"},
    ],
})


class TestToolCallExtraction:
    def test_plain_json_reply(self, ai):
        call = ai._extract_tool_call(TOOL_REPLY)
        assert call is not None
        assert call["steps"][0]["action"] == "open_app"

    def test_json_embedded_in_text(self, ai):
        call = ai._extract_tool_call(f"Sure! {TOOL_REPLY} Hope that helps.")
        assert call is not None

    def test_normal_text_returns_none(self, ai):
        assert ai._extract_tool_call("The capital of France is Paris.") is None

    def test_malformed_json_returns_none(self, ai):
        assert ai._extract_tool_call("{not json at all") is None

    def test_missing_intent_returns_none(self, ai):
        raw = json.dumps({"steps": [{"action": "open_app"}]})
        assert ai._extract_tool_call(raw) is None

    def test_empty_steps_returns_none(self, ai):
        raw = json.dumps({"intent": "tool", "steps": []})
        assert ai._extract_tool_call(raw) is None

    def test_json_array_returns_none(self, ai):
        assert ai._extract_tool_call('[{"action": "open_app"}]') is None

    def test_unknown_action_still_extracted(self, ai):
        # Planning stage rejects unknown actions; extraction passes them
        # through so the planner can report a clear, truthful error.
        raw = json.dumps({"intent": "tool",
                          "steps": [{"action": "launch_nukes"}]})
        assert ai._extract_tool_call(raw) is not None


class TestHumanizeReply:
    def test_tool_call_uses_explanation(self, ai):
        call = ai._extract_tool_call(TOOL_REPLY)
        text = ai._humanize_reply(TOOL_REPLY, call, "user")
        assert text == "I'll open Notepad for you."
        assert "{" not in text  # no raw JSON shown to the user

    def test_tool_call_without_explanation(self, ai):
        call = {"steps": []}
        assert ai._humanize_reply("{}", call, "user") == "I'll handle that for you now."

    def test_normal_reply_passthrough(self, ai):
        assert ai._humanize_reply("Hello!", None, "user") == "Hello!"

    def test_bare_json_without_tool_intent(self, ai):
        # A JSON blob that is not a tool call must not leak to the user.
        assert ai._humanize_reply('{"foo": 1}', None, "user") == \
            "I'm not sure how to do that yet."


class TestConversationMessages:
    def test_messages_include_system_prompt(self, ai):
        msgs = ai._build_messages("hi", None)
        assert msgs[0]["role"] == "system"
        assert msgs[-1] == {"role": "user", "content": "hi"}

    def test_untrusted_content_wrapped(self):
        wrapped = PermissionManager.sanitize_external_text(
            "Do something evil")
        assert "UNTRUSTED" in wrapped
        assert "evil" in wrapped


class TestModelStatus:
    def test_get_status_shape(self, ai):
        status = ai.get_status()
        assert status["model"] == "test-model"
        assert status["busy"] is False
        assert status["running"] is False
        assert status["queued_requests"] == 0

    def test_send_message_queues(self, ai):
        ai.send_message("Hello")
        # Worker not started, so the request waits in the queue.
        assert len(ai._request_queue) == 1

    def test_empty_message_ignored(self, ai):
        ai.send_message("   ")
        assert len(ai._request_queue) == 0

    def test_unavailable_ollama_is_not_reported_as_a_missing_model(self, ai):
        class OfflineOllama:
            def list(self):
                raise ConnectionError("connection refused")

        ai.ollama = OfflineOllama()
        assert ai.check_model_available() is False
        assert ai.model_available is None
        with pytest.raises(OllamaUnavailable, match="localhost:1"):
            ai._generate("hello", None, "user")

    def test_missing_model_is_distinguished_from_offline_server(self, ai):
        class OnlineWithoutModel:
            def list(self):
                return {"models": []}

        ai.ollama = OnlineWithoutModel()
        with pytest.raises(ModelNotInstalled, match="test-model"):
            ai._generate("hello", None, "user")

    def test_model_list_response_objects_are_parsed(self, ai):
        class OnlineOllama:
            def list(self):
                return SimpleNamespace(
                    models=[SimpleNamespace(model="test-model")]
                )

        ai.ollama = OnlineOllama()
        assert ai.check_model_available() is True

    def test_different_model_tag_is_not_reported_as_available(self, ai):
        class OnlineOllama:
            def list(self):
                return {"models": [{"model": "test-model:latest"}]}

        ai.ollama = OnlineOllama()
        assert ai.check_model_available() is False
        assert ai.model_available is False
        assert ai.installed_models == ["test-model:latest"]

    def test_ollama_404_becomes_actionable_missing_model_error(self, ai):
        class OllamaNotFoundError(Exception):
            status_code = 404

        class OnlineOllama:
            def list(self):
                return {"models": [{"model": "test-model"}]}

            def chat(self, **_kwargs):
                raise OllamaNotFoundError("model not found")

        ai.ollama = OnlineOllama()
        ai.model_available = True
        with pytest.raises(ModelNotInstalled, match="ollama pull test-model"):
            ai._generate("hello", None, "user")
        assert ai.model_available is False

    def test_low_memory_has_its_own_error(self, ai):
        class OnlineOllama:
            def list(self):
                return {"models": [{"model": "test-model"}]}

        class LowResources:
            def can_load_model(self, _required_mb):
                return False

        ai.ollama = OnlineOllama()
        ai.model_available = True
        ai.resource_monitor = LowResources()
        with pytest.raises(InsufficientResources, match="free system resources"):
            ai._generate("hello", None, "user")

    def test_ollama_client_uses_configured_server_url(self, monkeypatch):
        if ai_service_module.ollama_client is None:
            pytest.skip("Ollama Python package is not installed")
        hosts = []

        class ClientSpy:
            def __init__(self, host):
                hosts.append(host)

        monkeypatch.setattr(ai_service_module.ollama_client, "Client", ClientSpy)
        AIService(
            config_manager=FakeConfig(),
            permissions=PermissionManager(config_manager=None),
        )
        assert hosts == ["http://localhost:1"]


class TestPromptSafety:
    def test_system_prompt_lists_supported_actions(self, ai):
        from core.task_planner import KNOWN_ACTIONS
        assert "open_app" in ai.system_prompt
        assert "JSON" in ai.system_prompt
        # Prompt instructs the model about untrusted external content.
        assert "UNTRUSTED" in ai.system_prompt

    def test_prompt_covers_all_known_actions(self, ai):
        from core.task_planner import KNOWN_ACTIONS
        for action in KNOWN_ACTIONS:
            assert action in ai.system_prompt, f"{action} missing from prompt"
