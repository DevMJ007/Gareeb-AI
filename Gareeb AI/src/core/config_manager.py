#!/usr/bin/env python3
"""
Configuration manager for MJ AI.

Handles loading, saving, and managing application configuration.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
import logging
from dataclasses import dataclass, field
from core.app_paths import data_path

@dataclass
class AudioConfig:
    """Audio configuration settings."""
    # Voice input
    push_to_talk_enabled: bool = True
    push_to_talk_key: str = "ctrl+shift+m"
    auto_start_listening: bool = False
    wake_word_enabled: bool = False
    wake_word: str = "hey mj"
    language: str = "en"
    
    # Voice output
    tts_enabled: bool = True
    tts_speed: float = 1.0
    tts_volume: float = 1.0
    tts_voice: str = "default"
    
    # Audio permissions
    microphone_allowed: bool = False
    screen_capture_allowed: bool = False

@dataclass
class AIConfig:
    """AI model configuration settings."""
    # Model selection
    model_name: str = "llama3.2:1b"  # Small model for 12GB RAM
    ollama_url: str = "http://localhost:11434"
    auto_load_model: bool = True
    unload_on_idle: bool = True
    idle_timeout_minutes: int = 5
    
    # Inference settings
    max_context_length: int = 1024
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    
    # Model management
    check_model_on_startup: bool = True
    install_missing_models: bool = False
    model_storage_path: str = "models"

@dataclass
class UIConfig:
    """User interface configuration settings."""
    # Window settings
    window_width: int = 800
    window_height: int = 600
    window_x: int = 100
    window_y: int = 100
    companion_x: int = -1
    companion_y: int = -1
    always_on_top: bool = False
    transparent_background: bool = False
    window_opacity: float = 1.0
    
    # Animation settings
    animation_speed: float = 1.0
    eye_blink_interval: int = 3000  # milliseconds
    eye_movement_sensitivity: float = 1.0
    show_listening_indicator: bool = True
    show_thinking_indicator: bool = True
    
    # Companion appearance
    companion_name: str = "MJ"
    companion_personality: str = "friendly"
    companion_color: str = "#333333"
    
    # Panel visibility
    conversation_panel_visible: bool = True
    settings_panel_visible: bool = False
    status_bar_visible: bool = True

@dataclass
class AutomationConfig:
    """Desktop automation configuration settings."""
    # Safety settings
    confirm_destructive_actions: bool = True
    restrict_to_user_folders: bool = True
    max_execution_time: int = 30  # seconds
    
    # Application control
    allowed_applications: list[str] = field(default_factory=lambda: [
        "notepad.exe",
        "code.exe",
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "steam.exe",
        "discord.exe"
    ])
    
    # Mouse and keyboard
    enable_mouse_control: bool = True
    enable_keyboard_input: bool = True
    prevent_sleep: bool = False

@dataclass
class MemoryConfig:
    """Conversation memory configuration."""
    # Storage
    storage_backend: str = "sqlite"
    database_path: str = "data/myai.db"
    
    # Retention
    max_conversations: int = 100
    max_messages_per_conversation: int = 1000
    auto_cleanup: bool = True
    cleanup_days: int = 30
    
    # Memory settings
    store_user_preferences: bool = True
    store_task_history: bool = True
    store_interaction_patterns: bool = True

@dataclass
class PerformanceConfig:
    """Performance and resource management."""
    # Resource limits
    max_memory_usage_mb: int = 2048
    max_cpu_usage_percent: int = 50
    max_concurrent_tasks: int = 3
    
    # Monitoring
    monitor_cpu_usage: bool = True
    monitor_memory_usage: bool = True
    monitor_disk_usage: bool = False
    
    # Optimization
    cache_responses: bool = False
    cache_size: int = 100
    compression_enabled: bool = True

@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    file_enabled: bool = True
    console_enabled: bool = True
    file_path: str = "logs/myai.log"
    max_file_size_mb: int = 10
    backup_count: int = 5
    include_sensitive_info: bool = False
class ConfigManager:
    """
    Manages application configuration.
    
    Handles loading, saving, and providing access to configuration values.
    """
    
    def __init__(self, config_file: Optional[str] = None):
        self.logger = logging.getLogger(__name__)
        
        if config_file is None:
            self.config_file = data_path(Path("config") / "mjai_config.json")
        else:
            self.config_file = Path(config_file)
        
        self.config_dir = self.config_file.parent
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.config = {}
        
        self._load_config()
    
    def _load_config(self):
        """Load configuration from file."""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
                
                self.logger.info(f"Configuration loaded from {self.config_file}")
            else:
                self.logger.info(f"No existing configuration found, using defaults")
                self._save_defaults()
                
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            self._save_defaults()
    
    def _save_defaults(self):
        """Save default configuration."""
        default_config = {
            "audio": {
                "push_to_talk_enabled": True,
                "push_to_talk_key": "ctrl+shift+m",
                "auto_start_listening": False,
                "wake_word_enabled": False,
                "wake_word": "hey mj",
                "language": "en",
                "tts_enabled": True,
                "tts_speed": 1.0,
                "tts_volume": 1.0,
                "tts_voice": "default",
                "microphone_allowed": False,
                "screen_capture_allowed": False
            },
            "ai": {
                "model_name": "llama3.2:1b",
                "ollama_url": "http://localhost:11434",
                "auto_load_model": True,
                "unload_on_idle": True,
                "idle_timeout_minutes": 5,
                "max_context_length": 1024,
                "temperature": 0.7,
                "top_p": 0.9,
                "top_k": 40,
                "check_model_on_startup": True,
                "install_missing_models": False,
                "model_storage_path": "models"
            },
            "ui": {
                "window_width": 800,
                "window_height": 600,
                "window_x": 100,
                "window_y": 100,
                "companion_x": -1,
                "companion_y": -1,
                "always_on_top": False,
                "transparent_background": False,
                "window_opacity": 1.0,
                "animation_speed": 1.0,
                "eye_blink_interval": 3000,
                "eye_movement_sensitivity": 1.0,
                "show_listening_indicator": True,
                "show_thinking_indicator": True,
                "companion_name": "MJ",
                "companion_personality": "friendly",
                "companion_color": "#333333",
                "conversation_panel_visible": True,
                "settings_panel_visible": False,
                "status_bar_visible": True
            },
            "automation": {
                "confirm_destructive_actions": True,
                "restrict_to_user_folders": True,
                "max_execution_time": 30,
                "allowed_applications": [
                    "notepad.exe",
                    "code.exe",
                    "chrome.exe",
                    "msedge.exe",
                    "firefox.exe"
                ],
                "enable_mouse_control": True,
                "enable_keyboard_input": True,
                "prevent_sleep": False
            },
            "memory": {
                "storage_backend": "sqlite",
                "database_path": "data/myai.db",
                "max_conversations": 100,
                "max_messages_per_conversation": 1000,
                "auto_cleanup": True,
                "cleanup_days": 30,
                "store_user_preferences": True,
                "store_task_history": True,
                "store_interaction_patterns": True
            },
            "performance": {
                "max_memory_usage_mb": 2048,
                "max_cpu_usage_percent": 50,
                "max_concurrent_tasks": 3,
                "monitor_cpu_usage": True,
                "monitor_memory_usage": True,
                "monitor_disk_usage": False,
                "cache_responses": False,
                "cache_size": 100,
                "compression_enabled": True
            },
            "logging": {
                "level": "INFO",
                "file_enabled": True,
                "console_enabled": True,
                "file_path": "logs/myai.log",
                "max_file_size_mb": 10,
                "backup_count": 5,
                "include_sensitive_info": False
            }
        }
        
        self.config = default_config
        self.save()
    
    def save(self):
        """Save current configuration to file."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            
            self.logger.debug(f"Configuration saved to {self.config_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to save configuration: {e}")
            raise
    
    def get_audio_config(self) -> AudioConfig:
        """Get audio configuration."""
        audio_config = self.config.get("audio", {})
        return AudioConfig(**audio_config)
    
    def get_ai_config(self) -> AIConfig:
        """Get AI configuration."""
        ai_config = self.config.get("ai", {})
        return AIConfig(**ai_config)
    
    def get_ui_config(self) -> UIConfig:
        """Get UI configuration."""
        ui_config = self.config.get("ui", {})
        return UIConfig(**ui_config)
    
    def get_automation_config(self) -> AutomationConfig:
        """Get automation configuration."""
        automation_config = self.config.get("automation", {})
        return AutomationConfig(**automation_config)
    
    def get_memory_config(self) -> MemoryConfig:
        """Get memory configuration."""
        memory_config = self.config.get("memory", {})
        return MemoryConfig(**memory_config)
    
    def get_performance_config(self) -> PerformanceConfig:
        """Get performance configuration."""
        performance_config = self.config.get("performance", {})
        return PerformanceConfig(**performance_config)
    
    def get_logging_config(self) -> LoggingConfig:
        """Get logging configuration."""
        logging_config = self.config.get("logging", {})
        return LoggingConfig(**logging_config)
    
    def get(self, section: str, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.
        
        Args:
            section: Configuration section
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        return self.config.get(section, {}).get(key, default)
    
    def set(self, section: str, key: str, value: Any):
        """
        Set a configuration value.
        
        Args:
            section: Configuration section
            key: Configuration key
            value: Configuration value
        """
        if section not in self.config:
            self.config[section] = {}
        
        self.config[section][key] = value
        self.save()
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """
        Get an entire configuration section.
        
        Args:
            section: Configuration section
            
        Returns:
            Configuration section dictionary
        """
        return self.config.get(section, {}).copy()
    
    def set_section(self, section: str, values: Dict[str, Any]):
        """
        Set an entire configuration section.
        
        Args:
            section: Configuration section
            values: Configuration values
        """
        self.config[section] = values.copy()
        self.save()
