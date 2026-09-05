"""Where the large things live, and moving them without losing them."""

from __future__ import annotations

import json

import pytest

from podharvest import storage
from podharvest.appspace import AppSpace, resolve


def _space(tmp_path, *, data=None):
    return AppSpace(tmp_path / "home", data_root=data).ensure()


class TestTheTwoHalves:
    """Settings and logs stay put; the big folders are the ones that move."""

    def test_by_default_everything_is_in_one_place(self, tmp_path):
        app = _space(tmp_path)
        assert app.models_dir.parent == app.root
        assert app.config_dir.parent == app.root

    def test_a_data_root_moves_only_the_large_folders(self, tmp_path):
        elsewhere = tmp_path / "big drive"
        app = _space(tmp_path, data=elsewhere)
        assert app.models_dir == elsewhere / "models"
        assert app.python_packages_dir == elsewhere / "pydeps"
        assert app.http_cache_dir == elsewhere / "cache" / "http"
        assert app.temp_dir == elsewhere / "tmp"

    def test_settings_and_logs_never_move(self, tmp_path):
        """A settings file that moves is a settings file you can lose."""
        elsewhere = tmp_path / "big drive"
        app = _space(tmp_path, data=elsewhere)
        assert app.config_file.parent.parent == app.root
        assert app.logs_dir.parent == app.root

    def test_the_movable_list_matches_what_the_properties_use(self, tmp_path):
        app = _space(tmp_path)
        for name in app.DATA_FOLDERS:
            assert (app.data / name).parent == app.data

    def test_ml_caches_follow_the_data_root(self, tmp_path):
        """Otherwise Hugging Face keeps filling the drive you just left."""
        elsewhere = tmp_path / "big drive"
        app = _space(tmp_path, data=elsewhere)
        env = app.env_overrides()
        assert str(elsewhere) in env["HF_HOME"]
        assert str(elsewhere) in env["TORCH_HOME"]


class TestReadingTheSetting:
    """`resolve` reads the JSON directly, before `config` can be used."""

    def _write(self, root, value):
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "config" / "settings.json").write_text(
            json.dumps({"data_dir": value}), encoding="utf-8")

    def test_a_configured_folder_is_used(self, tmp_path, monkeypatch):
        root = tmp_path / "home"
        elsewhere = tmp_path / "big drive"
        self._write(root, str(elsewhere))
        monkeypatch.setenv("PODHARVEST_HOME", str(root))
        app = resolve()
        assert app.data == elsewhere.resolve()

    def test_no_setting_means_the_default(self, tmp_path, monkeypatch):
        root = tmp_path / "home"
        self._write(root, "")
        monkeypatch.setenv("PODHARVEST_HOME", str(root))
        assert resolve().data == root.resolve()

    def test_an_unreadable_settings_file_is_not_fatal(self, tmp_path, monkeypatch):
        """Somebody whose drive is unplugged should get podHarvest back."""
        root = tmp_path / "home"
        (root / "config").mkdir(parents=True)
        (root / "config" / "settings.json").write_text("{not json",
                                                       encoding="utf-8")
        monkeypatch.setenv("PODHARVEST_HOME", str(root))
        assert resolve().data == root.resolve()

    def test_pointing_at_itself_is_the_default(self, tmp_path, monkeypatch):
        root = tmp_path / "home"
        self._write(root, str(root))
        monkeypatch.setenv("PODHARVEST_HOME", str(root))
        app = resolve()
        assert app.data_root is None


class TestMeasuring:
    def test_it_reports_each_folder(self, tmp_path):
        app = _space(tmp_path)
        (app.models_dir / "a.bin").write_bytes(b"x" * 2048)
        sizes = {s.name: s.bytes for s in storage.measure(app)}
        assert sizes["models"] == 2048
        assert sizes["pydeps"] == 0

    def test_the_largest_comes_first(self, tmp_path):
        app = _space(tmp_path)
        (app.models_dir / "a.bin").write_bytes(b"x" * 4096)
        (app.python_packages_dir / "b.bin").write_bytes(b"x" * 8192)
        assert storage.measure(app)[0].name == "pydeps"

    def test_sizes_are_read_aloud_not_printed_raw(self):
        assert storage.human_size(0) == "0 bytes"
        assert storage.human_size(2048) == "2.0 KB"
        assert storage.human_size(5 * 1024 ** 3) == "5.0 GB"

    def test_free_space_answers_for_a_folder_that_does_not_exist_yet(self, tmp_path):
        assert storage.free_bytes(tmp_path / "not" / "made" / "yet") > 0


class TestCheckingBeforeMoving:
    def test_moving_where_it_already_is_is_refused(self, tmp_path):
        app = _space(tmp_path)
        ok, why = storage.check_move(app, app.data)
        assert ok is False
        assert "already" in why

    def test_moving_into_its_own_subfolder_is_refused(self, tmp_path):
        """Otherwise the copy is copied, forever."""
        app = _space(tmp_path)
        ok, why = storage.check_move(app, app.data / "models" / "deeper")
        assert ok is False
        assert "inside" in why

    def test_a_file_is_not_a_folder(self, tmp_path):
        app = _space(tmp_path)
        target = tmp_path / "a-file"
        target.write_text("no", encoding="utf-8")
        ok, why = storage.check_move(app, target)
        assert ok is False
        assert "file" in why

    def test_a_good_destination_is_allowed_and_says_the_size(self, tmp_path):
        app = _space(tmp_path)
        (app.models_dir / "a.bin").write_bytes(b"x" * 4096)
        ok, why = storage.check_move(app, tmp_path / "elsewhere")
        assert ok is True
        assert "4.0 KB" in why

    def test_it_refuses_when_there_is_not_enough_room(self, tmp_path, monkeypatch):
        app = _space(tmp_path)
        (app.models_dir / "a.bin").write_bytes(b"x" * 4096)
        monkeypatch.setattr(storage, "free_bytes", lambda _p: 10)
        ok, why = storage.check_move(app, tmp_path / "elsewhere")
        assert ok is False
        assert "Not enough room" in why


class TestMoving:
    def test_everything_arrives(self, tmp_path):
        app = _space(tmp_path)
        (app.models_dir / "a.bin").write_bytes(b"x" * 32)
        (app.python_packages_dir / "b.txt").write_text("hi", encoding="utf-8")
        destination = tmp_path / "elsewhere"
        storage.move_data(app, destination)
        assert (destination / "models" / "a.bin").read_bytes() == b"x" * 32
        assert (destination / "pydeps" / "b.txt").read_text() == "hi"

    def test_the_originals_are_gone_afterwards(self, tmp_path):
        app = _space(tmp_path)
        (app.models_dir / "a.bin").write_bytes(b"x" * 32)
        storage.move_data(app, tmp_path / "elsewhere")
        assert not app.models_dir.exists()

    def test_settings_and_logs_are_left_alone(self, tmp_path):
        app = _space(tmp_path)
        app.config_file.write_text("{}", encoding="utf-8")
        (app.logs_dir / "podharvest.log").write_text("x", encoding="utf-8")
        storage.move_data(app, tmp_path / "elsewhere")
        assert app.config_file.is_file()
        assert (app.logs_dir / "podharvest.log").is_file()

    def test_it_says_what_it_is_doing(self, tmp_path):
        app = _space(tmp_path)
        (app.models_dir / "a.bin").write_bytes(b"x" * 32)
        said: list[str] = []
        storage.move_data(app, tmp_path / "elsewhere", on_progress=said.append)
        assert any("Copying models" in line for line in said)
        assert any("Done" in line for line in said)

    def test_a_failed_copy_leaves_the_original_where_it_was(
            self, tmp_path, monkeypatch):
        """Half a gigabyte of models is not worth risking to save seconds."""
        app = _space(tmp_path)
        (app.models_dir / "a.bin").write_bytes(b"x" * 32)

        def explode(*_a, **_k):
            raise OSError("the drive went away")

        monkeypatch.setattr(storage.shutil, "copytree", explode)
        with pytest.raises(OSError):
            storage.move_data(app, tmp_path / "elsewhere")
        assert (app.models_dir / "a.bin").is_file()
