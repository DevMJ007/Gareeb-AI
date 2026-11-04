"""Resource monitor tests (PRD sections 7 and 12)."""
import time
import pytest

from core.resource_monitor import ResourceMonitor, cpu_thread_limit


@pytest.fixture
def rm():
    monitor = ResourceMonitor(config_manager=None)
    # Collect one sample synchronously for deterministic assertions.
    stats = monitor._collect_stats()
    monitor._update_stats_history(stats)
    yield monitor
    monitor.stop_monitoring()


class TestStats:
    def test_cpu_thread_budget_uses_eighty_percent_by_default(self, monkeypatch):
        monkeypatch.setattr("core.resource_monitor.psutil.cpu_count",
                            lambda logical=True: 8)

        assert cpu_thread_limit() == 6
        assert cpu_thread_limit(50) == 4

    def test_collect_stats_shape(self, rm):
        stats = rm._collect_stats()
        assert stats.cpu_usage_percent >= 0
        assert stats.memory_total_mb > 0
        assert stats.memory_used_mb > 0
        assert 0 <= stats.memory_percent <= 100
        assert stats.disk_total_mb > 0
        assert stats.active_processes > 0

    def test_get_current_stats(self, rm):
        stats = rm.get_current_stats()
        assert stats is not None

    def test_history_bounded(self, rm):
        for _ in range(250):
            rm._update_stats_history(rm._collect_stats())
        assert len(rm.stats_history) <= rm.max_history_size

    def test_average_stats(self, rm):
        avg = rm.get_average_stats(duration_seconds=60)
        assert avg is not None
        assert avg.cpu_usage_percent >= 0


class TestModelLoading:
    def test_refuses_when_memory_too_low(self, rm):
        # Ask for more than the total RAM of the machine - must refuse.
        total = rm.get_current_stats().memory_total_mb
        assert rm.can_load_model(int(total) + 1024) is False

    def test_allows_small_model_when_plenty_free(self, rm):
        stats = rm.get_current_stats()
        if stats.memory_available_mb > 1024:
            assert rm.can_load_model(64) is True

    def test_idle_unload_decision_without_config(self, rm):
        # No config manager -> conservative behaviour.
        assert rm.should_unload_model(idle_time_minutes=9999) is True


class TestStatus:
    def test_resource_status_shape(self, rm):
        status = rm.get_resource_status()
        assert status["status"] in ("healthy", "warning", "critical", "unknown")
        assert "stats" in status

    def test_monitoring_start_stop(self, rm):
        received = []
        rm.start_monitoring(callback=received.append)
        assert rm.monitoring is True
        time.sleep(1.3)
        rm.stop_monitoring()
        assert rm.monitoring is False
        assert len(received) >= 1  # at least one sample delivered
