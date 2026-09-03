"""Seeding and logging configuration."""

from __future__ import annotations

import logging
import os
import random

import numpy as np

from packagename.log import get_logger, setup_logging
from packagename.seed import set_seed


class TestSetSeed:
    def test_python_rng_is_reproducible(self):
        set_seed(123)
        first = [random.random() for _ in range(5)]  # noqa: S311 -- not cryptographic
        set_seed(123)
        assert [random.random() for _ in range(5)] == first  # noqa: S311

    def test_numpy_rng_is_reproducible(self):
        set_seed(123)
        first = np.random.rand(5)  # noqa: NPY002 -- exercises the legacy global RNG
        set_seed(123)
        np.testing.assert_array_equal(np.random.rand(5), first)  # noqa: NPY002

    def test_different_seeds_diverge(self):
        set_seed(1)
        first = random.random()  # noqa: S311
        set_seed(2)
        assert random.random() != first  # noqa: S311

    def test_hash_seed_is_exported(self):
        set_seed(7)
        assert os.environ["PYTHONHASHSEED"] == "7"

    def test_returns_the_seed_for_chaining(self):
        assert set_seed(11) == 11

    def test_deterministic_mode_is_accepted_without_torch(self):
        assert set_seed(5, deterministic=True) == 5


class TestSetupLogging:
    def test_installs_a_console_handler(self, settings):
        setup_logging(settings)
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert len(root.handlers) == 1

    def test_repeated_calls_do_not_duplicate_handlers(self, settings):
        setup_logging(settings)
        setup_logging(settings)
        assert len(logging.getLogger().handlers) == 1

    def test_level_argument_overrides_the_config(self, settings):
        setup_logging(settings, level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_file_handler_writes_where_configured(self, tmp_path):
        from packagename.config import load_settings

        settings = load_settings(paths={"root": tmp_path}, logging={"file": "run.log"})
        setup_logging(settings)
        get_logger("packagename.test").warning("hello")
        logging.shutdown()
        assert "hello" in (tmp_path / "logs" / "run.log").read_text(encoding="utf-8")

    def test_noisy_libraries_are_demoted(self, settings):
        setup_logging(settings)
        assert logging.getLogger("matplotlib").level == logging.WARNING

    def test_get_logger_namespaces_by_module(self):
        assert get_logger("packagename.foo").name == "packagename.foo"
