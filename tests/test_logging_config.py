import server.logging_config as logging_config
from server.logging_config import configure_server_logging


def test_configure_server_logging_creates_the_log_directory_and_file(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_file = log_dir / "server.log"
    monkeypatch.setattr(logging_config, "LOG_DIR", log_dir)
    monkeypatch.setattr(logging_config, "LOG_FILE", log_file)

    configure_server_logging()

    assert log_dir.is_dir()
    assert log_file.exists()
