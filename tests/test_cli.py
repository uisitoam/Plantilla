"""Hydra wiring: composition, command-line overrides and the no-chdir contract."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from hydra import compose, initialize_config_dir
from hydra.core.hydra_config import HydraConfig
from omegaconf import OmegaConf

from packagename.cli._hydra import command_line_overrides, hydra_entrypoint
from packagename.config import CONFIG_DIR, PROJECT_ROOT, Settings, settings_from_mapping


def _compose(*overrides: str, with_hydra: bool = False):
    with initialize_config_dir(version_base=None, config_dir=str(CONFIG_DIR)):
        return compose(
            config_name="config",
            overrides=list(overrides),
            return_hydra_config=with_hydra,
        )


def _settings(*overrides: str) -> Settings:
    cfg = _compose(*overrides)
    return settings_from_mapping(OmegaConf.to_container(cfg, resolve=True))


class TestComposition:
    def test_composed_config_validates_into_settings(self):
        settings = _settings()
        assert settings.project_name == "packagename"
        assert settings.paths.root == PROJECT_ROOT

    def test_command_line_override_of_a_scalar(self):
        assert _settings("random_seed=7").random_seed == 7

    def test_command_line_override_of_a_nested_key(self):
        assert _settings("wandb.mode=offline").wandb.mode == "offline"

    def test_command_line_override_of_a_path(self, tmp_path):
        settings = _settings(f"paths.root={tmp_path}")
        assert settings.paths.gold == tmp_path / "data" / "gold"

    def test_invalid_override_is_caught_by_validation(self):
        with pytest.raises(ValueError, match=r"wandb\.mode|mode"):
            _settings("wandb.mode=not_a_mode")

    def test_unknown_key_needs_an_explicit_append(self):
        """Struct mode means a typo is an error, not a silently ignored key."""
        with pytest.raises(Exception, match=r"not in struct|Could not override"):
            _compose("wandb.projekt=oops")


@pytest.mark.integration
class TestPrecedence:
    """The environment must not be shadowed by YAML defaults nobody typed.

    Regression tests: the composed config used to enter as explicit values, so
    every key the YAML spelled out — which is all of them — outranked the
    environment. That made `.env` and `PACKAGENAME_*` inert for the entrypoints,
    which is the way the template is normally run.
    """

    def _run(self, tmp_path, monkeypatch, *overrides: str) -> Settings:
        captured: dict[str, Settings] = {}

        @hydra_entrypoint
        def entry(settings: Settings) -> None:
            captured["settings"] = settings

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "test-entrypoint",
                f"paths.root={tmp_path}",
                f"hydra.run.dir={tmp_path}/out",
                *overrides,
            ],
        )
        entry()
        return captured["settings"]

    def test_environment_beats_the_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PACKAGENAME_RANDOM_SEED", "999")
        assert self._run(tmp_path, monkeypatch).random_seed == 999

    def test_nested_environment_beats_the_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PACKAGENAME_WANDB__PROJECT", "from_env")
        assert self._run(tmp_path, monkeypatch).wandb.project == "from_env"

    def test_a_command_line_override_beats_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PACKAGENAME_RANDOM_SEED", "999")
        assert self._run(tmp_path, monkeypatch, "random_seed=7").random_seed == 7

    def test_overriding_one_leaf_leaves_its_siblings_to_the_environment(
        self, tmp_path, monkeypatch
    ):
        """Sources are merged per leaf, not per section."""
        monkeypatch.setenv("PACKAGENAME_WANDB__PROJECT", "from_env")
        settings = self._run(tmp_path, monkeypatch, "wandb.mode=disabled")
        assert settings.wandb.mode == "disabled"
        assert settings.wandb.project == "from_env"

    def test_the_config_file_still_beats_the_defaults(self, tmp_path, monkeypatch):
        """With nothing else in play, the YAML is what decides."""
        assert self._run(tmp_path, monkeypatch).wandb.mode == "offline"


@contextmanager
def _composed_with_hydra(*overrides: str):
    """Compose for real and install the resulting HydraConfig, as a job would."""
    with initialize_config_dir(version_base=None, config_dir=str(CONFIG_DIR)):
        HydraConfig.instance().set_config(
            compose(config_name="config", overrides=list(overrides), return_hydra_config=True)
        )
        # The task config, without Hydra's own node, is what a job actually gets.
        task = compose(config_name="config", overrides=list(overrides))
        try:
            yield OmegaConf.to_container(task, resolve=True)
        finally:
            # Leaving a config installed would leak into later tests.
            HydraConfig().cfg = None


class TestCommandLineOverrides:
    """`command_line_overrides` is what separates typed keys from YAML defaults."""

    def test_extracts_only_the_named_leaves(self):
        with _composed_with_hydra("random_seed=7", "wandb.mode=disabled") as composed:
            assert command_line_overrides(composed) == {
                "random_seed": 7,
                "wandb": {"mode": "disabled"},
            }

    def test_nothing_typed_means_nothing_explicit(self):
        with _composed_with_hydra() as composed:
            assert command_line_overrides(composed) == {}

    def test_ignores_hydras_own_overrides(self):
        with _composed_with_hydra("hydra.job.chdir=false", "random_seed=1") as composed:
            assert command_line_overrides(composed) == {"random_seed": 1}

    def test_a_deleted_key_carries_nothing(self):
        """`~key` removes it from the composed config, so there is no value to pass on."""
        with _composed_with_hydra("~logging.level") as composed:
            assert command_line_overrides(composed) == {}

    def test_a_whole_section_can_be_overridden(self):
        with _composed_with_hydra("wandb.tags=[a,b]") as composed:
            assert command_line_overrides(composed) == {"wandb": {"tags": ["a", "b"]}}


class TestHydraSection:
    def test_chdir_is_disabled(self):
        """The whole path design depends on the process not changing directory."""
        cfg = _compose(with_hydra=True)
        assert cfg.hydra.job.chdir is False

    def test_output_directories_are_absolute(self):
        cfg = _compose(with_hydra=True)
        assert Path(cfg.hydra.run.dir).is_absolute()
        assert Path(cfg.hydra.run.dir).is_relative_to(PROJECT_ROOT)

    def test_project_root_resolver_is_registered(self):
        assert OmegaConf.has_resolver("project_root")


@pytest.mark.integration
class TestEntrypoint:
    def test_receives_validated_settings_without_changing_directory(self, tmp_path, monkeypatch):
        captured: dict[str, object] = {}

        @hydra_entrypoint
        def entry(settings: Settings) -> None:
            captured["cwd"] = Path.cwd()
            captured["settings"] = settings

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "test-entrypoint",
                f"paths.root={tmp_path}",
                f"hydra.run.dir={tmp_path / 'outputs'}",
            ],
        )
        entry()

        settings = captured["settings"]
        assert isinstance(settings, Settings)
        assert captured["cwd"] == tmp_path, "hydra.job.chdir must stay false"
        assert settings.paths.root == tmp_path

    def test_creates_the_project_directories(self, tmp_path, monkeypatch):
        captured: dict[str, Settings] = {}

        @hydra_entrypoint
        def entry(settings: Settings) -> None:
            captured["settings"] = settings

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "test-entrypoint",
                f"paths.root={tmp_path}",
                f"hydra.run.dir={tmp_path / 'outputs'}",
            ],
        )
        entry()

        assert captured["settings"].paths.gold.is_dir()
        assert captured["settings"].paths.figures.is_dir()

    def test_seeds_the_generators(self, tmp_path, monkeypatch):
        import os

        @hydra_entrypoint
        def entry(settings: Settings) -> None: ...

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "test-entrypoint",
                "random_seed=1234",
                f"paths.root={tmp_path}",
                f"hydra.run.dir={tmp_path / 'outputs'}",
            ],
        )
        entry()
        assert os.environ["PYTHONHASHSEED"] == "1234"

    def test_command_line_overrides_reach_get_settings(self, tmp_path, monkeypatch):
        """Helpers that resolve relative paths must see the composed config.

        Regression test: get_settings() used to return separately loaded settings,
        so `savefig(fig, "x.png")` inside a Hydra job ignored `paths.*` overrides
        and wrote to the repository instead.
        """
        captured: dict[str, Path] = {}

        @hydra_entrypoint
        def entry(settings: Settings) -> None:
            from packagename.config import get_settings

            captured["from_argument"] = settings.paths.figures
            captured["from_get_settings"] = get_settings().paths.figures

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "test-entrypoint",
                f"paths.root={tmp_path}",
                f"hydra.run.dir={tmp_path / 'outputs'}",
            ],
        )
        entry()

        assert captured["from_get_settings"] == captured["from_argument"]
        assert captured["from_get_settings"].is_relative_to(tmp_path)

    def test_the_binding_does_not_outlive_the_call(self, tmp_path, monkeypatch):
        from packagename.config import get_settings

        @hydra_entrypoint
        def entry(settings: Settings) -> None: ...

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "test-entrypoint",
                f"paths.root={tmp_path}",
                f"hydra.run.dir={tmp_path / 'outputs'}",
            ],
        )
        entry()

        assert get_settings().paths.root == PROJECT_ROOT

    def test_preserves_the_wrapped_function_metadata(self):
        @hydra_entrypoint
        def documented(settings: Settings) -> None:
            """A docstring."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "A docstring."


@pytest.mark.integration
class TestTrainEntrypoint:
    """Smoke test: the console script must at least start and finish."""

    def test_runs_end_to_end(self, tmp_path, monkeypatch):
        from packagename.cli import train

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "packagename-train",
                f"paths.root={tmp_path}",
                f"hydra.run.dir={tmp_path / 'outputs'}",
                "wandb.mode=disabled",
            ],
        )
        train.main()
        assert (tmp_path / "data" / "gold").is_dir()


@pytest.mark.integration
class TestStageEntrypoint:
    """`packagename-stage` is what `just etl` invokes, so it is a contract.

    It is deliberately not a Hydra entrypoint: a stage's parameters come from
    the versioned `configs/config.yaml` and nowhere else, so accepting
    overrides here would let a run leave no trace in `git log`.
    """

    def test_listing_the_stages_succeeds(self, capsys):
        from packagename.cli.stage import main

        assert main(["--list"]) == 0
        assert "generate_measurements" in capsys.readouterr().out

    def test_running_a_stage_writes_its_output(self, tmp_path, monkeypatch):
        from packagename.cli.stage import main
        from packagename.config import reset_settings_cache

        monkeypatch.setenv("PACKAGENAME_PATHS__ROOT", str(tmp_path))
        reset_settings_cache()

        assert main(["generate_measurements"]) == 0
        assert (tmp_path / "data" / "raw" / "measurements.csv").is_file()

    def test_all_runs_the_stages_in_registration_order(self, tmp_path, monkeypatch):
        """`just etl` depends on `--all` chaining a producer before its consumer."""
        from packagename.cli.stage import main
        from packagename.config import reset_settings_cache

        monkeypatch.setenv("PACKAGENAME_PATHS__ROOT", str(tmp_path))
        reset_settings_cache()

        assert main(["--all"]) == 0
        assert (tmp_path / "data" / "silver" / "measurements.parquet").is_file()

    def test_an_unknown_stage_exits_non_zero(self):
        """A caller has to see a failure, not a stage that quietly did nothing."""
        from packagename.cli.stage import main

        with pytest.raises(SystemExit) as exited:
            main(["no_such_stage"])
        assert exited.value.code != 0

    def test_a_missing_stage_name_exits_non_zero(self):
        from packagename.cli.stage import main

        with pytest.raises(SystemExit) as exited:
            main([])
        assert exited.value.code != 0
