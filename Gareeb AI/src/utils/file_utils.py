#!/usr/bin/env python3
"""
File utilities for MJ AI.

Provides functions for safe file operations, path validation, and file management.
"""

import os
import shutil
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import json
import stat

# Configure logger
logger = logging.getLogger(__name__)

class FileValidationError(Exception):
    """Exception raised for file validation errors."""
    pass

class FileUtils:
    """
    Utility class for file operations with safety checks.
    
    Provides methods for safe file creation, reading, writing, and management
    with validation and confirmation for potentially destructive operations.
    """
    
    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        self.logger = logging.getLogger(__name__)
    
    def validate_path(self, path: str, require_exists: bool = False, 
                     require_file: bool = False, require_dir: bool = False) -> Path:
        """
        Validate a file or directory path.
        
        Args:
            path: Path to validate
            require_exists: Whether the path must exist
            require_file: Whether the path must be a file
            require_dir: Whether the path must be a directory
            
        Returns:
            Validated Path object
            
        Raises:
            FileValidationError: If validation fails
        """
        try:
            if path is None or not isinstance(path, (str, os.PathLike)):
                raise FileValidationError("Path is empty or invalid.")
            raw_path = str(path)
            if not raw_path.strip():
                raise FileValidationError("Path is empty or invalid.")
            raw_parts = raw_path.replace("\\", "/").split("/")
            if ".." in raw_parts:
                raise FileValidationError("Path traversal is not allowed.")

            validated_path = Path(raw_path).expanduser().resolve()
            
            # Check if path exists if required
            if require_exists and not validated_path.exists():
                raise FileValidationError(f"Path does not exist: {validated_path}")
            
            # Check path type if specified
            if require_file and validated_path.exists() and not validated_path.is_file():
                raise FileValidationError(f"Path is not a file: {validated_path}")
            
            if require_dir and validated_path.exists() and not validated_path.is_dir():
                raise FileValidationError(f"Path is not a directory: {validated_path}")
            
            # Check for security issues
            self._check_security_issues(validated_path)
            
            return validated_path
            
        except Exception as e:
            self.logger.error(f"Path validation failed for {path}: {e}")
            raise FileValidationError(f"Invalid path: {e}")
    
    def _check_security_issues(self, path: Path):
        """
        Check for potential security issues with a path.
        
        Args:
            path: Path to check
            
        Raises:
            FileValidationError: If security issue detected
        """
        # Check for dangerous paths
        dangerous_patterns = [
            "..", "../", "..\\", 
            "/etc", "C:\\Windows", "C:\\Program Files",
            "/usr/bin", "/bin", "/sbin"
        ]
        
        path_str = str(path).replace("/", "\\").casefold()
        for pattern in dangerous_patterns:
            if pattern.casefold().replace("/", "\\") in path_str:
                raise FileValidationError(f"Access to system path not allowed: {path}")

        # Check for hidden files in restricted contexts
        if path.name.startswith('.'):
            self.logger.warning(f"Access to hidden file: {path}")
        
        # Check for executable files without explicit permission
        if path.suffix == '.exe' or path.name.lower().endswith('.com'):
            self.logger.warning(f"Access to executable file: {path}")
    
    def safe_read_file(self, file_path: str, encoding: str = 'utf-8', 
                      max_size_mb: int = 10) -> str:
        """
        Read a file with safety checks.
        
        Args:
            file_path: Path to file
            encoding: File encoding
            max_size_mb: Maximum file size in MB
            
        Returns:
            File content as string
            
        Raises:
            FileValidationError: If file cannot be read safely
        """
        try:
            path = self.validate_path(file_path, require_file=True)

            sensitive_hints = (
                "password", "passwd", "credential", "secret", "token", "private",
                "wallet", "keystore", "id_rsa",
            )
            name = path.name.casefold()
            if path.suffix.casefold() == ".pem" or any(hint in name for hint in sensitive_hints):
                raise FileValidationError(f"Access to sensitive file not allowed: {path}")
            
            # Check file size
            file_size = path.stat().st_size
            max_size_bytes = max_size_mb * 1024 * 1024
            
            if file_size > max_size_bytes:
                raise FileValidationError(f"File too large: {file_size} bytes > {max_size_bytes} bytes")
            
            # Check if file is readable
            if not os.access(path, os.R_OK):
                raise FileValidationError(f"File not readable: {path}")
            
            # Read file content
            with open(path, 'r', encoding=encoding) as f:
                content = f.read()
            
            self.logger.debug(f"Successfully read file: {path} ({len(content)} characters)")
            return content
            
        except UnicodeDecodeError:
            # Try with different encoding
            try:
                with open(path, 'r', encoding='latin-1') as f:
                    content = f.read()
                return content
            except Exception as e:
                raise FileValidationError(f"Cannot read file with any supported encoding: {e}")
        except Exception as e:
            raise FileValidationError(f"Error reading file: {e}")
    
    def safe_write_file(self, file_path: str, content: str, 
                       encoding: str = 'utf-8', create_dirs: bool = True,
                       backup_existing: bool = False) -> bool:
        """
        Write content to a file with safety checks.
        
        Args:
            file_path: Path to file
            content: Content to write
            encoding: File encoding
            create_dirs: Whether to create parent directories if they don't exist
            backup_existing: Whether to create a backup of existing file
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            FileValidationError: If file cannot be written safely
        """
        try:
            path = self.validate_path(file_path)
            
            # Check if parent directory exists and is writable
            parent_dir = path.parent
            if not parent_dir.exists():
                if create_dirs:
                    parent_dir.mkdir(parents=True, exist_ok=True)
                    self.logger.info(f"Created directory: {parent_dir}")
                else:
                    raise FileValidationError(f"Parent directory does not exist: {parent_dir}")
            
            if not os.access(parent_dir, os.W_OK):
                raise FileValidationError(f"Parent directory not writable: {parent_dir}")
            
            # Check if file exists and create backup if requested
            if path.exists() and backup_existing:
                backup_path = path.with_suffix(f".backup{path.suffix}")
                backup_count = 1
                while backup_path.exists():
                    backup_path = path.with_suffix(f".backup{backup_count}{path.suffix}")
                    backup_count += 1
                
                shutil.copy2(path, backup_path)
                self.logger.info(f"Created backup: {backup_path}")
            
            # Write file content
            with open(path, 'w', encoding=encoding) as f:
                f.write(content)
            
            self.logger.info(f"Successfully wrote file: {path} ({len(content)} characters)")
            return True
            
        except Exception as e:
            raise FileValidationError(f"Error writing file: {e}")
    
    def safe_create_directory(self, dir_path: str, mode: int = 0o755) -> bool:
        """
        Create a directory with safety checks.
        
        Args:
            dir_path: Path to directory
            mode: Directory permissions
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            FileValidationError: If directory cannot be created safely
        """
        try:
            path = self.validate_path(dir_path, require_dir=False)
            
            # Create directory
            path.mkdir(parents=True, exist_ok=True)
            
            # Set permissions
            path.chmod(mode)
            
            self.logger.info(f"Successfully created directory: {path}")
            return True
            
        except Exception as e:
            raise FileValidationError(f"Error creating directory: {e}")
    
    def safe_delete_file(self, file_path: str, confirm: bool = True) -> bool:
        """
        Delete a file with safety checks.
        
        Args:
            file_path: Path to file
            confirm: Whether to request confirmation
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            FileValidationError: If file cannot be deleted safely
        """
        try:
            path = self.validate_path(file_path, require_file=True)
            
            # Check if path is in allowed locations (if configured)
            if self.config_manager:
                config = self.config_manager.get_automation_config()
                if config.restrict_to_user_folders:
                    user_folders = [
                        str(Path.home()),
                        str(Path.home() / "Documents"),
                        str(Path.home() / "Desktop"),
                        str(Path.home() / "Downloads")
                    ]
                    
                    path_str = str(path)
                    if not any(path_str.startswith(folder) for folder in user_folders):
                        raise FileValidationError(f"Access to this path is restricted: {path}")
            
            # Request confirmation if requested
            if confirm:
                response = input(f"Are you sure you want to delete {path}? (y/N): ")
                if response.lower() != 'y':
                    self.logger.info(f"Deletion cancelled by user for: {path}")
                    return False
            
            # Delete file
            path.unlink()
            self.logger.info(f"Successfully deleted file: {path}")
            return True
            
        except Exception as e:
            raise FileValidationError(f"Error deleting file: {e}")
    
    def safe_move_file(self, src_path: str, dst_path: str, 
                      overwrite: bool = False, confirm: bool = True) -> bool:
        """
        Move a file with safety checks.
        
        Args:
            src_path: Source file path
            dst_path: Destination file path
            overwrite: Whether to overwrite existing file
            confirm: Whether to request confirmation
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            FileValidationError: If file cannot be moved safely
        """
        try:
            src = self.validate_path(src_path, require_file=True)
            dst = self.validate_path(dst_path, require_exists=False, require_file=False)
            
            # Check if destination exists
            if dst.exists():
                if overwrite:
                    # Request confirmation for overwrite
                    if confirm:
                        response = input(f"File already exists. Overwrite {dst}? (y/N): ")
                        if response.lower() != 'y':
                            self.logger.info(f"Move cancelled by user for: {src} -> {dst}")
                            return False
                else:
                    raise FileValidationError(f"File already exists: {dst}")
            
            # Move file
            shutil.move(str(src), str(dst))
            self.logger.info(f"Successfully moved file: {src} -> {dst}")
            return True
            
        except Exception as e:
            raise FileValidationError(f"Error moving file: {e}")
    
    def safe_copy_file(self, src_path: str, dst_path: str, 
                      overwrite: bool = False) -> bool:
        """
        Copy a file with safety checks.
        
        Args:
            src_path: Source file path
            dst_path: Destination file path
            overwrite: Whether to overwrite existing file
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            FileValidationError: If file cannot be copied safely
        """
        try:
            src = self.validate_path(src_path, require_file=True)
            dst = self.validate_path(dst_path, require_exists=False, require_file=False)
            
            # Check if destination exists
            if dst.exists() and not overwrite:
                raise FileValidationError(f"File already exists: {dst}")
            
            # Copy file
            shutil.copy2(src, dst)
            self.logger.info(f"Successfully copied file: {src} -> {dst}")
            return True
            
        except Exception as e:
            raise FileValidationError(f"Error copying file: {e}")
    
    def get_file_info(self, file_path: str) -> Dict[str, Any]:
        """
        Get information about a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            Dictionary with file information
            
        Raises:
            FileValidationError: If file cannot be accessed
        """
        try:
            path = self.validate_path(file_path, require_file=True)
            
            stat_info = path.stat()
            
            return {
                'path': str(path),
                'name': path.name,
                'size': stat_info.st_size,
                'size_mb': stat_info.st_size / (1024 * 1024),
                'modified': stat_info.st_mtime,
                'created': stat_info.st_ctime,
                'is_readable': os.access(path, os.R_OK),
                'is_writable': os.access(path, os.W_OK),
                'is_executable': os.access(path, os.X_OK),
                'exists': True
            }
            
        except FileNotFoundError:
            return {
                'path': str(path),
                'name': Path(file_path).name,
                'size': 0,
                'size_mb': 0,
                'modified': 0,
                'created': 0,
                'is_readable': False,
                'is_writable': False,
                'is_executable': False,
                'exists': False
            }
    
    def create_text_file(self, file_path: str, content: str, 
                        confirm_overwrite: bool = True) -> bool:
        """
        Create a text file with confirmation.
        
        Args:
            file_path: Path to file
            content: Content to write
            confirm_overwrite: Whether to request confirmation if file exists
            
        Returns:
            True if successful, False otherwise
        """
        try:
            path = self.validate_path(file_path)
            
            if path.exists():
                if confirm_overwrite:
                    response = input(f"File already exists. Overwrite {path}? (y/N): ")
                    if response.lower() != 'y':
                        self.logger.info(f"File creation cancelled by user for: {path}")
                        return False
                else:
                    self.logger.warning(f"File already exists, skipping: {path}")
                    return True  # Consider it a "success" since file exists
            
            self.safe_write_file(file_path, content)
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating text file: {e}")
            return False
    
    def list_directory(self, dir_path: str, recursive: bool = False, 
                      include_hidden: bool = False) -> List[Dict[str, Any]]:
        """
        List contents of a directory.
        
        Args:
            dir_path: Path to directory
            recursive: Whether to list files recursively
            include_hidden: Whether to include hidden files
            
        Returns:
            List of file/directory information dictionaries
        """
        try:
            path = self.validate_path(dir_path, require_dir=True)
            
            files = []
            
            for item in path.iterdir():
                # Skip hidden files if not requested
                if not include_hidden and item.name.startswith('.'):
                    continue
                
                file_info = self.get_file_info(str(item))
                
                # Add to results
                files.append(file_info)
                
                # Add subdirectories if recursive
                if recursive and item.is_dir():
                    files.extend(self.list_directory(str(item), recursive, include_hidden))
            
            return sorted(files, key=lambda x: x['name'])
            
        except Exception as e:
            self.logger.error(f"Error listing directory {dir_path}: {e}")
            return []
    
    def search_in_directory(self, dir_path: str, query: str, 
                           file_extensions: Optional[List[str]] = None,
                           recursive: bool = False) -> List[Dict[str, Any]]:
        """
        Search for text in files within a directory.
        
        Args:
            dir_path: Path to directory
            query: Text to search for
            file_extensions: List of file extensions to search (None for all)
            recursive: Whether to search recursively
            
        Returns:
            List of search results with file info and match positions
        """
        try:
            path = self.validate_path(dir_path, require_dir=True)
            
            results = []
            
            for item in self.list_directory(dir_path, recursive, include_hidden=False):
                if not item['exists']:
                    continue
                
                # Check file extension
                if file_extensions and item['name']:
                    ext = Path(item['name']).suffix.lower()
                    if ext not in file_extensions:
                        continue
                
                # Skip binary files (large files or common binary extensions)
                if (item['size'] > 10 * 1024 * 1024 or  # 10MB
                    item['name'].lower().endswith(('.exe', '.dll', '.bin', '.png', '.jpg', '.mp3', '.mp4'))):
                    continue
                
                try:
                    # Read file and search
                    content = self.safe_read_file(str(path / item['name']))
                    
                    # Simple case-insensitive search
                    if query.lower() in content.lower():
                        # Find all matches
                        matches = []
                        start_pos = 0
                        while True:
                            pos = content.lower().find(query.lower(), start_pos)
                            if pos == -1:
                                break
                            
                            # Extract context around match
                            context_start = max(0, pos - 50)
                            context_end = min(len(content), pos + len(query) + 50)
                            context = content[context_start:context_end]
                            
                            matches.append({
                                'position': pos,
                                'context': context,
                                'line_number': content[:pos].count('\n') + 1
                            })
                            
                            start_pos = pos + 1
                        
                        results.append({
                            'file_path': str(path / item['name']),
                            'file_name': item['name'],
                            'matches': matches,
                            'total_matches': len(matches)
                        })
                
                except FileValidationError:
                    # Skip files that cannot be read
                    continue
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error searching in directory {dir_path}: {e}")
            return []
