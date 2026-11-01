# UI package initialization for MJ AI

"""User interface modules: main window, companion widget, settings.

Import submodules directly, e.g.:
    from ui.main_window import MainWindow
"""

__all__ = ['MainWindow', 'CompanionWidget', 'SettingsDialog']


def __getattr__(name):
    if name in ('MainWindow', 'CompanionWidget', 'SettingsDialog'):
        from ui.main_window import MainWindow, CompanionWidget, SettingsDialog
        return {'MainWindow': MainWindow,
                'CompanionWidget': CompanionWidget,
                'SettingsDialog': SettingsDialog}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
