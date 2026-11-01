#!/usr/bin/env python3
"""
Simple test script to verify MJ AI setup.
"""

import sys
import os
import logging

def test_imports():
    """Test that all required imports work."""
    print("Testing imports...")
    
    try:
        # Core modules
        from core.config_manager import ConfigManager
        print("ConfigManager imported successfully")
        
        from core.resource_monitor import ResourceMonitor
        print("ResourceMonitor imported successfully")
        
        # Services
        from services.audio_service import AudioService
        print("AudioService imported successfully")
        
        from services.automation_service import AutomationService
        print("AutomationService imported successfully")
        
        from services.screen_analyzer import ScreenAnalyzer
        print("ScreenAnalyzer imported successfully")
        
        from services.ai_service import AIService
        print("AIService imported successfully")
        
        # UI modules
        from ui.main_window import MainWindow, CompanionWidget
        print("MainWindow and CompanionWidget imported successfully")
        
        # Utils
        from utils.file_utils import FileUtils, FileValidationError
        print("FileUtils imported successfully")
        
        print("All imports successful!")
        return True
        
    except ImportError as e:
        print(f"Import failed: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

def test_config_manager():
    """Test ConfigManager functionality."""
    print("\nTesting ConfigManager...")
    
    try:
        from core.config_manager import ConfigManager
        
        # Create config manager
        config = ConfigManager()
        
        # Test getting configurations
        audio_config = config.get_audio_config()
        print(f"Audio config loaded (model: {audio_config.tts_voice})")
        
        ai_config = config.get_ai_config()
        print(f"AI config loaded (model: {ai_config.model_name})")
        
        ui_config = config.get_ui_config()
        print(f"UI config loaded (window: {ui_config.window_width}x{ui_config.window_height})")
        
        # Test setting values
        config.set("test", "value", "test_value")
        retrieved = config.get("test", "value", "default")
        if retrieved == "test_value":
            print("Config set/get works")
        else:
            print(f"Config set/get failed: {retrieved} != 'test_value'")
            return False
        
        # Save and reload
        config.save()
        
        config2 = ConfigManager()
        audio_config2 = config2.get_audio_config()
        if audio_config2.tts_voice == audio_config.tts_voice:
            print("Config save/load works")
        else:
            print("Config save/load failed")
            return False
        
        print("ConfigManager tests passed!")
        return True
        
    except Exception as e:
        print(f"ConfigManager test failed: {e}")
        return False

def test_logging():
    """Test logging setup."""
    print("\nTesting logging...")
    
    try:
        import logging
        
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )
        
        logger = logging.getLogger(__name__)
        logger.info("Test log message")
        print("Logging works")
        
        return True
        
    except Exception as e:
        print(f"Logging test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 50)
    print("MJ AI Setup Test")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_config_manager,
        test_logging
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                print(f"Test {test.__name__} failed")
        except Exception as e:
            print(f"Test {test.__name__} crashed: {e}")
    
    print("\n" + "=" * 50)
    print(f"Test Results: {passed}/{total} tests passed")
    print("=" * 50)
    
    if passed == total:
        print("All tests passed! MJ AI setup is working.")
        return 0
    else:
        print("Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())