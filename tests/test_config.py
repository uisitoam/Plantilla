"""Configuration precedence, strictness and path anchoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from packagename.config import (
    DEFAULT_CONFIG_FILE,
    PROJECT_ROOT,
    Paths,
    Settings,
    get_settings,
    load_settings,
    settings_from_mapping,
    use_settings,
)


class TestSources:
    def test_reads_the_shipped_config(self):
        settings = load_settings()
        assert settings.project_name == "packagename"
        assert settings.random_seed == 42

    def test_reads_a_custom_yaml(self, tmp_path):
        cfg = tmp_path / "custom.yaml"
        cfg.write_text("project_name: custom\nrandom_seed: 7\n")
        settings = load_settings(cfg)
        assert settings.project_name == "custom"
        assert settings.random_seed == 7

    def test_falls_back_to_defaults_when_yaml_is_missing(self, tmp_path):
        settings = load_settings(tmp_path / "nope.yaml")
        assert settings.project_name == "packagename"
        assert settings.random_seed == 42

    def test_hydra_sections_are_not_settings(self):
        """`defaults` and `hydra:` live in the same file but belong to Hydra."""
        settings = load_settings(DEFAULT_CONFIG_FILE)
        assert not hasattr(settings, "hydra")


class TestPrecedence:
    """Environment beats file, and explicit arguments beat everything."""

    def test_env_overrides_yaml(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("project_name: from_yaml\n")
        monkeypatch.setenv("PACKAGENAME_PROJECT_NAME", "from_env")
        assert load_settings(cfg).project_name == "from_env"

    def test_env_fills_gaps_in_yaml(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("random_seed: 7\n")
        monkeypatch.setenv("PACKAGENAME_PROJECT_NAME", "from_env")
        settings = load_settings(cfg)
        assert settings.project_name == "from_env"
        assert settings.random_seed == 7

    def test_nested_env_override(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("wandb:\n  project: from_yaml\n")
        monkeypatch.setenv("PACKAGENAME_WANDB__PROJECT", "from_env")
        assert load_settings(cfg).wandb.project == "from_env"

    def test_explicit_arguments_win(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("project_name: from_yaml\n")
        monkeypatch.setenv("PACKAGENAME_PROJECT_NAME", "from_env")
        assert load_settings(cfg, project_name="explicit").project_name == "explicit"

    def test_unprefixed_variables_are_ignored(self, monkeypatch):
        """A bare PROJECT_NAME belongs to some other program, not to us."""
        monkeypatch.setenv("PROJECT_NAME", "someone_else")
        assert load_settings().project_name == "packagename"


class TestStrictness:
    def test_unknown_top_level_yaml_key_is_rejected(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("randon_seed: 1\n")
        with pytest.raises(ValueError, match="Unknown configuration key"):
            load_settings(cfg)

    def test_unknown_nested_yaml_key_is_rejected(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("wandb:\n  projekt: oops\n")
        with pytest.raises(ValueError, match=r"[Ee]xtra"):
            load_settings(cfg)

    def test_unknown_override_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown configuration key"):
            load_settings(projekt_name="misspelled")

    def test_wrong_type_is_rejected(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("random_seed: not_a_number\n")
        with pytest.raises(ValueError, match="random_seed"):
            load_settings(cfg)


class TestPaths:
    def test_relative_defaults_are_anchored_to_the_root(self):
        paths = Paths()
        assert paths.root == PROJECT_ROOT
        assert paths.gold == PROJECT_ROOT / "data/gold"
        assert all(getattr(paths, name).is_absolute() for name in Paths.model_fields)

    def test_relative_overrides_follow_a_custom_root(self, tmp_path):
        paths = Paths(root=tmp_path, gold=Path("custom/gold"))
        assert paths.gold == tmp_path / "custom" / "gold"

    def test_absolute_overrides_are_left_alone(self, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        assert Paths(root=tmp_path, gold=elsewhere).gold == elsewhere

    def test_layer_lookup(self, tmp_path):
        paths = Paths(root=tmp_path)
        assert paths.layer("silver") == paths.silver
        with pytest.raises(ValueError, match="Unknown layer"):
            paths.layer("platinum")

    def test_ensure_creates_every_directory(self, tmp_path):
        paths = Paths(root=tmp_path)
        paths.ensure()
        assert paths.gold.is_dir()
        assert paths.figures.is_dir()

    def test_wandb_run_dir_defaults_to_the_root(self, tmp_path):
        settings = load_settings(paths={"root": tmp_path})
        assert settings.wandb.run_dir == tmp_path

    def test_log_file_is_resolved_under_the_logs_directory(self, tmp_path):
        settings = load_settings(paths={"root": tmp_path}, logging={"file": "run.log"})
        assert settings.logging.file == tmp_path / "logs" / "run.log"


class TestHelpers:
    def test_settings_from_mapping_strips_hydra_keys(self):
        composed = {"project_name": "composed", "defaults": ["_self_"], "hydra": {"job": {}}}
        assert settings_from_mapping(composed).project_name == "composed"

    def test_settings_from_mapping_rejects_unknown_keys(self):
        with pytest.raises(ValueError, match="Unknown configuration key"):
            settings_from_mapping({"nonsense": 1})

    def test_as_flat_dict_uses_dotted_keys(self):
        flat = load_settings().as_flat_dict()
        assert flat["wandb.project"] == "packagename"
        assert flat["random_seed"] == 42
        assert all(not isinstance(value, dict) for value in flat.values())

    def test_get_settings_is_cached(self):
        assert get_settings() is get_settings()


class TestActiveSettings:
    """`use_settings` is how an entrypoint's config reaches implicit readers."""

    def test_binding_replaces_what_get_settings_returns(self, tmp_path):
        bound = load_settings(project_name="bound", paths={"root": tmp_path})
        with use_settings(bound):
            assert get_settings() is bound

    def test_the_binding_is_undone_on_exit(self, tmp_path):
        before = get_settings()
        with use_settings(load_settings(paths={"root": tmp_path})):
            pass
        assert get_settings() is before

    def test_the_binding_is_undone_when_the_block_raises(self, tmp_path):
        before = get_settings()
        with pytest.raises(RuntimeError), use_settings(load_settings(paths={"root": tmp_path})):
            raise RuntimeError("boom")
        assert get_settings() is before

    def test_bindings_nest(self, tmp_path):
        outer = load_settings(project_name="outer", paths={"root": tmp_path})
        inner = load_settings(project_name="inner", paths={"root": tmp_path})
        with use_settings(outer):
            with use_settings(inner):
                assert get_settings().project_name == "inner"
            assert get_settings().project_name == "outer"


def test_shipped_yaml_produces_a_fully_resolved_object():
    """The config that ships with the template must validate on a clean checkout."""
    settings = Settings()
    assert settings.project_name
    assert settings.paths.root == PROJECT_ROOT
    assert settings.wandb.run_dir is not None
    assert settings.logging.level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
