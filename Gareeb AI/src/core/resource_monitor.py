#!/usr/bin/env python3
"""
Resource monitor for MJ AI.

Monitors system resources and provides information about available memory,
CPU usage, and disk space for resource management decisions.
"""

import time
import psutil
import threading
from typing import Any, Dict, Optional, Callable
import logging
from pathlib import Path
from dataclasses import dataclass
import gc


def cpu_thread_limit(max_cpu_percent: int = 80) -> int:
    """Return a conservative worker count from the configured CPU budget."""
    logical_cpus = max(1, psutil.cpu_count(logical=True) or 1)
    try:
        budget = max(1, min(100, int(max_cpu_percent)))
    except (TypeError, ValueError):
        budget = 50
    return max(1, min(logical_cpus, logical_cpus * budget // 100))

@dataclass
class ResourceStats:
    """System resource statistics."""
    timestamp: float
    cpu_usage_percent: float
    memory_used_mb: float
    memory_total_mb: float
    memory_available_mb: float
    memory_percent: float
    disk_used_mb: float
    disk_total_mb: float
    disk_free_mb: float
    disk_percent: float
    active_processes: int
    threads_count: int

class ResourceMonitor:
    """
    Monitors system resources and provides resource management.
    
    Tracks CPU usage, memory consumption, and disk usage to make decisions
    about resource allocation and model management.
    """
    
    def __init__(self, config_manager=None):
        self.logger = logging.getLogger(__name__)
        
        self.config_manager = config_manager
        self.monitoring = False
        self.monitoring_thread: Optional[threading.Thread] = None
        self.stats_callback: Optional[Callable[[ResourceStats], None]] = None
        self.stats_history: list[ResourceStats] = []
        self.max_history_size = 100
        
        # Resource thresholds
        self.low_memory_threshold_mb = 512  # MB
        self.critical_memory_threshold_mb = 256  # MB
        self.high_cpu_threshold_percent = 80.0
        self.high_disk_threshold_percent = 90.0
        
        self.logger.info("Resource monitor initialized")
    
    def start_monitoring(self, callback: Optional[Callable[[ResourceStats], None]] = None):
        """
        Start resource monitoring.
        
        Args:
            callback: Optional callback for resource statistics updates
        """
        if self.monitoring:
            self.logger.warning("Resource monitoring already started")
            return
        
        self.stats_callback = callback
        self.monitoring = True
        
        self.monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True
        )
        self.monitoring_thread.start()
        
        self.logger.info("Resource monitoring started")
    
    def stop_monitoring(self):
        """Stop resource monitoring."""
        self.monitoring = False
        
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5.0)
            self.monitoring_thread = None
        
        self.logger.info("Resource monitoring stopped")
    
    def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.monitoring:
            try:
                stats = self._collect_stats()
                self._update_stats_history(stats)
                
                if self.stats_callback:
                    self.stats_callback(stats)
                
                # Force garbage collection periodically
                if len(self.stats_history) % 60 == 0:  # Every minute
                    gc.collect()
                
                time.sleep(1.0)  # Monitor every second
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(5.0)  # Wait before retrying
    
    def _collect_stats(self) -> ResourceStats:
        """Collect current system statistics."""
        timestamp = time.time()
        
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)
        
        # Memory usage
        memory = psutil.virtual_memory()
        memory_used_mb = memory.used / (1024 * 1024)
        memory_total_mb = memory.total / (1024 * 1024)
        memory_available_mb = memory.available / (1024 * 1024)
        
        # Disk usage
        disk = psutil.disk_usage('/')
        disk_used_mb = disk.used / (1024 * 1024)
        disk_total_mb = disk.total / (1024 * 1024)
        
        # Process and thread count
        processes = psutil.pids()
        active_processes = len(processes)
        
        threads_count = 0
        for process in psutil.process_iter(['pid']):
            try:
                threads_count += process.num_threads()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Processes can exit or become inaccessible between the scan
                # and the thread-count query; skip those entries for this sample.
                continue
        
        return ResourceStats(
            timestamp=timestamp,
            cpu_usage_percent=cpu_percent,
            memory_used_mb=memory_used_mb,
            memory_total_mb=memory_total_mb,
            memory_available_mb=memory_available_mb,
            memory_percent=memory.percent,
            disk_used_mb=disk_used_mb,
            disk_total_mb=disk_total_mb,
            disk_free_mb=disk.free / (1024 * 1024),
            disk_percent=disk.percent,
            active_processes=active_processes,
            threads_count=threads_count
        )
    
    def _update_stats_history(self, stats: ResourceStats):
        """Update statistics history."""
        self.stats_history.append(stats)
        
        # Keep history size bounded
        if len(self.stats_history) > self.max_history_size:
            self.stats_history.pop(0)
    
    def get_current_stats(self) -> Optional[ResourceStats]:
        """Get current resource statistics."""
        if self.stats_history:
            return self.stats_history[-1]
        return None
    
    def get_average_stats(self, duration_seconds: int = 60) -> Optional[ResourceStats]:
        """
        Get average resource statistics over a duration.
        
        Args:
            duration_seconds: Duration for averaging
            
        Returns:
            Average resource statistics or None if insufficient data
        """
        if not self.stats_history:
            return None
        
        cutoff_time = time.time() - duration_seconds
        relevant_stats = [
            stats for stats in self.stats_history
            if stats.timestamp >= cutoff_time
        ]
        
        if not relevant_stats:
            return None
        
        # Calculate averages
        avg_cpu = sum(stats.cpu_usage_percent for stats in relevant_stats) / len(relevant_stats)
        avg_memory = sum(stats.memory_used_mb for stats in relevant_stats) / len(relevant_stats)
        avg_disk = sum(stats.disk_used_mb for stats in relevant_stats) / len(relevant_stats)
        
        # Use latest timestamp
        latest_stats = relevant_stats[-1]
        
        return ResourceStats(
            timestamp=latest_stats.timestamp,
            cpu_usage_percent=avg_cpu,
            memory_used_mb=avg_memory,
            memory_total_mb=latest_stats.memory_total_mb,
            memory_available_mb=latest_stats.memory_available_mb,
            memory_percent=(avg_memory / latest_stats.memory_total_mb) * 100,
            disk_used_mb=avg_disk,
            disk_total_mb=latest_stats.disk_total_mb,
            disk_free_mb=latest_stats.disk_free_mb,
            disk_percent=latest_stats.disk_percent,
            active_processes=latest_stats.active_processes,
            threads_count=latest_stats.threads_count
        )
    
    def can_load_model(self, model_memory_mb: int) -> bool:
        """
        Check if there's sufficient resources to load a model.
        
        Args:
            model_memory_mb: Memory required by the model in MB
            
        Returns:
            True if model can be loaded, False otherwise
        """
        current_stats = self.get_current_stats()
        if not current_stats:
            return True
        
        # Check memory
        available_memory_mb = current_stats.memory_available_mb
        required_memory_mb = model_memory_mb + 512  # 512MB buffer
        
        if available_memory_mb < required_memory_mb:
            self.logger.warning(f"Insufficient memory: need {required_memory_mb}MB, have {available_memory_mb}MB")
            return False
        
        # Check CPU
        config = self.config_manager.get_performance_config() if self.config_manager else None
        if config and current_stats.cpu_usage_percent > config.max_cpu_usage_percent:
            # CPU usage is a transient system-wide sample. A saturated sample
            # commonly comes from the local model itself, so do not reject a
            # request here. Ollama and Whisper use cpu_thread_limit() to keep
            # their worker count within the configured CPU budget.
            self.logger.info(
                "CPU load is %.1f%% (configured budget %s%%); inference will "
                "use a reduced thread count",
                current_stats.cpu_usage_percent,
                config.max_cpu_usage_percent,
            )
        
        # Check disk space (minimum 1GB free)
        if current_stats.disk_free_mb < 1024:
            self.logger.warning(f"Insufficient disk space: need 1024MB, have {current_stats.disk_free_mb}MB")
            return False
        
        return True
    
    def should_unload_model(self, idle_time_minutes: float) -> bool:
        """
        Check if model should be unloaded based on idle time.
        
        Args:
            idle_time_minutes: Time since last activity in minutes
            
        Returns:
            True if model should be unloaded, False otherwise
        """
        if not self.config_manager:
            return True
        
        config = self.config_manager.get_ai_config()
        
        if not config.unload_on_idle:
            return False
        
        return idle_time_minutes >= config.idle_timeout_minutes
    
    def get_resource_status(self) -> Dict[str, Any]:
        """
        Get comprehensive resource status.
        
        Returns:
            Dictionary with resource status information
        """
        stats = self.get_current_stats()
        if not stats:
            return {"status": "unknown", "message": "No resource data available"}
        
        status = "healthy"
        messages = []
        
        # Check memory
        if stats.memory_available_mb < self.low_memory_threshold_mb:
            status = "warning"
            messages.append(f"Low memory: {stats.memory_available_mb:.0f}MB available")
        
        if stats.memory_available_mb < self.critical_memory_threshold_mb:
            status = "critical"
            messages.append(f"Critical memory: {stats.memory_available_mb:.0f}MB available")
        
        # Check CPU
        if stats.cpu_usage_percent > self.high_cpu_threshold_percent:
            if status == "healthy":
                status = "warning"
            messages.append(f"High CPU usage: {stats.cpu_usage_percent:.1f}%")
        
        # Check disk
        if stats.disk_percent > self.high_disk_threshold_percent:
            if status == "healthy":
                status = "warning"
            messages.append(f"High disk usage: {stats.disk_percent:.1f}%")
        
        return {
            "status": status,
            "messages": messages,
            "stats": {
                "cpu_percent": stats.cpu_usage_percent,
                "memory_used_mb": stats.memory_used_mb,
                "memory_available_mb": stats.memory_available_mb,
                "memory_percent": stats.memory_percent,
                "disk_used_mb": stats.disk_used_mb,
                "disk_free_mb": stats.disk_free_mb,
                "disk_percent": stats.disk_percent,
                "active_processes": stats.active_processes,
                "threads_count": stats.threads_count
            }
        }
