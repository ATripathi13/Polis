from infrastructure.config.settings import get_settings


def test_settings_load() -> None:
    settings = get_settings()

    assert settings.app_name == "Polis"
    assert settings.environment == "development"