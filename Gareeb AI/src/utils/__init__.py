# Utils package initialization for MJ AI

"""Utility modules: file operations, OCR, path validation.

Import submodules directly, e.g.:
    from utils.file_utils import FileUtils
"""

__all__ = ['FileUtils', 'FileValidationError']


def __getattr__(name):
    if name in ('FileUtils', 'FileValidationError'):
        from utils.file_utils import FileUtils, FileValidationError
        return {'FileUtils': FileUtils, 'FileValidationError': FileValidationError}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
