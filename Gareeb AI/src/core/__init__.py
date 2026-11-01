# Core package initialization for MJ AI

"""Core application modules: config, resource monitoring, app lifecycle.

Import submodules directly, e.g.:
    from core.config_manager import ConfigManager
"""

__all__ = ['ConfigManager', 'ResourceMonitor']


def __getattr__(name):
    if name == 'ConfigManager':
        from core.config_manager import ConfigManager
        return ConfigManager
    if name == 'ResourceMonitor':
        from core.resource_monitor import ResourceMonitor
        return ResourceMonitor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
