# Services package initialization for MJ AI

"""Service layer: AI, audio, automation, and screen analysis.

Import submodules directly, e.g.:
    from services.ai_service import AIService
"""

__all__ = [
    'AIService',
    'AudioService',
    'AutomationService',
    'ScreenAnalyzer',
]

_SERVICE_MODULES = {
    'AIService': ('services.ai_service', 'AIService'),
    'AudioService': ('services.audio_service', 'AudioService'),
    'AutomationService': ('services.automation_service', 'AutomationService'),
    'ScreenAnalyzer': ('services.screen_analyzer', 'ScreenAnalyzer'),
}


def __getattr__(name):
    if name in _SERVICE_MODULES:
        module_name, attr = _SERVICE_MODULES[name]
        import importlib
        module = importlib.import_module(module_name)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
