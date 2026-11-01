#!/usr/bin/env python3
"""
Test script to verify MJ AI setup.

Checks basic imports and functionality to ensure the application can start.
"""

import sys
import os
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """Test that all required imports work."""
    print("Testing imports...")
    
    try:
        # Core modules
        from core.config_manager import ConfigManager
        print("✓ ConfigManager imported")
        
        from core.resource_monitor import ResourceMonitor
        print("✓ ResourceMonitor imported")
        
        # Services
        from services.audio_service import AudioService
        print("✓ AudioService imported")
        
        from services.automation_service import AutomationService
        print("✓ AutomationService imported")
        
        from services.screen_analyzer import ScreenAnalyzer
        print("✓ ScreenAnalyzer imported")
        
        from services.ai_service import AIService
        print("✓ AIService imported")
        
        # UI modules
        from ui.main_window import MainWindow, CompanionWidget
        print("✓ MainWindow and CompanionWidget imported")
        
        # Utils
        from utils.file_utils import FileUtils, FileValidationError
        print("✓ FileUtils imported")
        
        print("All imports successful!")
        return True
        
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
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
        print(f"✓ Audio config loaded (model: {audio_config.tts_voice})")
        
        ai_config = config.get_ai_config()
        print(f"✓ AI config loaded (model: {ai_config.model_name})")
        
        ui_config = config.get_ui_config()
        print(f"✓ UI config loaded (window: {ui_config.window_width}x{ui_config.window_height})")
        
        # Test setting values
        config.set("test", "value", "test_value")
        retrieved = config.get("test", "value", "default")
        if retrieved == "test_value":
            print("✓ Config set/get works")
        else:
            print(f"✗ Config set/get failed: {retrieved} != 'test_value'")
            return False
        
        # Save and reload
        config.save()
        
        config2 = ConfigManager()
        audio_config2 = config2.get_audio_config()
        if audio_config2.tts_voice == audio_config.tts_voice:
            print("✓ Config save/load works")
        else:
            print("✗ Config save/load failed")
            return False
        
        print("ConfigManager tests passed!")
        return True
        
    except Exception as e:
        print(f"✗ ConfigManager test failed: {e}")
        return False

def test_file_utils():
    """Test FileUtils functionality."""
    print("\nTesting FileUtils...")
    
    try:
        from utils.file_utils import FileUtils, FileValidationError
        
        # Create FileUtils instance
        file_utils = FileUtils()
        
        # Test path validation
        test_path = file_utils.validate_path(".", require_dir=True)
        print(f"✓ Path validation works: {test_path}")
        
        # Test creating a temporary directory
        temp_dir = "test_temp_dir"
        success = file_utils.safe_create_directory(temp_dir)
        if success:
            print(f"✓ Directory creation works: {temp_dir}")
            
            # Test writing and reading a file
            test_file = f"{temp_dir}/test.txt"
            test_content = "Hello, MJ AI!"
            
            success = file_utils.safe_write_file(test_file, test_content)
            if success:
                print("✓ File writing works")
                
                read_content = file_utils.safe_read_file(test_file)
                if read_content == test_content:
                    print("✓ File reading works")
                else:
                    print(f"✗ File reading failed: '{read_content}' != '{test_content}'")
                    return False
            else:
                print("✗ File writing failed")
                return False
            
            # Test file info
            file_info = file_utils.get_file_info(test_file)
            if file_info['exists'] and file_info['size'] > 0:
                print(f"✓ File info works: {file_info['size']} bytes")
            else:
                print("✗ File info failed")
                return False
            
            # Clean up
            import shutil
            shutil.rmtree(temp_dir)
            print(f"✓ Cleanup successful: {temp_dir}")
        else:
            print("✗ Directory creation failed")
            return False
        
        print("FileUtils tests passed!")
        return True
        
    except Exception as e:
        print(f"✗ FileUtils test failed: {e}")
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
        print("✓ Logging works")
        
        return True
        
    except Exception as e:
        print(f"✗ Logging test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 50)
    print("MJ AI Setup Test")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_config_manager,
        test_file_utils,
        test_logging
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
    
    print("\n" + "=" * 50)
    print(f"Test Results: {passed}/{total} tests passed")
    print("=" * 50)
    
    if passed == total:
        print("✓ All tests passed! MJ AI setup is working.")
        return 0
    else:
        print("✗ Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())