"""Utilities, settings persistence, WER scoring, and the CLI surface."""

import json

import pytest

from podharvest import config as config_mod
from podharvest.accuracy import word_error_rate
from podharvest.appspace import AppSpace
from podharvest.cli import build_parser
from podharvest.models import classify_media
from podharvest.util import (
    human_duration,
    human_size,
    parse_date,
    parse_duration,
    safe_filename,
    slugify,
)


class TestSlugsAndFilenames:
    @pytest.mark.parametrize("raw,expected", [
        ("Hello, World!", "hello-world"),
        ("  spaced  out  ", "spaced-out"),
        ("Ünïcödé Tïtlé", "unicode-title"),
        ("multiple---dashes", "multiple-dashes"),
        ("", "untitled"),
        ("!!!", "untitled"),
    ])
    def test_slugify(self, raw, expected):
        assert slugify(raw) == expected

    def test_slug_is_truncated_on_a_word_boundary(self):
        assert len(slugify("word " * 100)) <= 120

    def test_path_traversal_is_neutralised(self):
        assert "/" not in safe_filename("../../etc/passwd")
        assert ".." not in safe_filename("../../etc/passwd")

    def test_windows_reserved_names_are_escaped(self):
        for reserved in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT1"):
            assert safe_filename(f"{reserved}.mp3").upper() != f"{reserved}.MP3"

    def test_illegal_characters_are_replaced(self):
        cleaned = safe_filename('a<b>c:d"e|f?g*h.mp3')
        assert not any(ch in cleaned for ch in '<>:"|?*')

    def test_trailing_dots_and_spaces_are_trimmed(self):
        assert not safe_filename("name...  ").endswith((" ", "."))


class TestDatesAndDurations:
    @pytest.mark.parametrize("raw", [
        "Tue, 05 Mar 2024 10:00:00 +0000",    # RFC 822 (RSS)
        "2024-03-05T10:00:00Z",               # ISO 8601 (Atom)
        "2024-03-05T10:00:00+00:00",
        "2024-03-05 10:00:00",
        "2024-03-05",
    ])
    def test_dates_parse_to_an_aware_datetime(self, raw):
        parsed = parse_date(raw)
        assert parsed is not None
        assert parsed.tzinfo is not None
        assert parsed.year == 2024 and parsed.month == 3 and parsed.day == 5

    def test_unparseable_date_returns_none(self):
        assert parse_date("last Thursday") is None
        assert parse_date("") is None
        assert parse_date(None) is None

    @pytest.mark.parametrize("raw,seconds", [
        ("1:02:05", 3725), ("02:05", 125), ("125", 125), ("0:00", 0),
    ])
    def test_durations(self, raw, seconds):
        assert parse_duration(raw) == seconds

    def test_invalid_duration_returns_none(self):
        assert parse_duration("about an hour") is None

    def test_human_duration_formats(self):
        assert human_duration(3725) == "1:02:05"
        assert human_duration(125) == "2:05"
        assert human_duration(None) == "unknown"

    def test_human_size_formats(self):
        assert human_size(1024) == "1.0 KB"
        assert human_size(None) == "unknown"


class TestMediaClassification:
    @pytest.mark.parametrize("mime,url,kind", [
        ("audio/mpeg", "https://x/a.mp3", "audio"),
        ("", "https://x/a.mp3", "audio"),
        ("", "https://x/a.mp3?token=1#f", "audio"),
        ("video/mp4", "https://x/a.mp4", "video"),
        ("", "https://x/a.webm", "video"),
        ("image/png", "https://x/a.png", "image"),
        ("application/pdf", "https://x/a.pdf", "document"),
        ("", "https://x/a.unknownext", "other"),
    ])
    def test_classification(self, mime, url, kind):
        assert classify_media(mime, url) == kind


class TestSettings:
    def test_roundtrip(self, tmp_path):
        app = AppSpace(tmp_path).ensure()
        settings = config_mod.Settings(last_feed_url="https://ex.test/f", episode_limit=5,
                                       transcribe=True)
        config_mod.save(app, settings)
        loaded = config_mod.load(app)
        assert loaded.last_feed_url == "https://ex.test/f"
        assert loaded.episode_limit == 5
        assert loaded.transcribe is True

    def test_missing_file_yields_defaults(self, tmp_path):
        assert config_mod.load(AppSpace(tmp_path).ensure()).episode_limit is None

    def test_corrupt_file_falls_back_to_defaults(self, tmp_path):
        app = AppSpace(tmp_path).ensure()
        app.config_file.write_text("{not json", encoding="utf-8")
        assert config_mod.load(app).episode_limit is None

    def test_unknown_keys_are_ignored(self, tmp_path):
        """Forward compatibility: a newer version's settings must still load."""
        app = AppSpace(tmp_path).ensure()
        app.config_file.write_text(
            json.dumps({"episode_limit": 3, "from_the_future": True}), encoding="utf-8")
        assert config_mod.load(app).episode_limit == 3

    def test_every_documented_setting_exists(self):
        """Guards against the README describing settings no code reads."""
        for name in ("output_dir", "episode_limit", "follow_pagination",
                     "download_enclosures", "download_kinds", "concurrent_downloads",
                     "download_retries", "download_rate_limit_kbps", "max_enclosure_mb",
                     "on_duplicate_file", "transcribe", "asr_engine", "asr_model",
                     "hf_token", "include_timestamps", "identify_speakers",
                     "diarization_backend", "naming_template", "write_srt", "write_vtt"):
            assert hasattr(config_mod.Settings(), name), name


class TestAppSpace:
    def test_explicit_root_wins(self, tmp_path):
        assert AppSpace(tmp_path).root == tmp_path

    def test_ensure_creates_every_directory(self, tmp_path):
        app = AppSpace(tmp_path).ensure()
        for path in (app.models_dir, app.config_dir, app.logs_dir,
                     app.http_cache_dir, app.default_output_dir):
            assert path.is_dir()

    def test_env_overrides_point_inside_the_root(self, tmp_path):
        app = AppSpace(tmp_path).ensure()
        for key in ("HF_HOME", "TORCH_HOME", "PIP_CACHE_DIR"):
            assert str(tmp_path) in app.env_overrides()[key]


class TestWordErrorRate:
    def test_identical_text_scores_zero(self):
        assert word_error_rate("the quick brown fox", "the quick brown fox").wer == 0.0

    def test_one_substitution_in_four_words(self):
        assert word_error_rate("the quick brown fox", "the quick brown dog").wer == pytest.approx(0.25)

    def test_error_counts_are_broken_out(self):
        result = word_error_rate("a b c d", "a b x d")
        assert result.substitutions == 1
        assert result.reference_words == 4
        assert result.errors == 1

    def test_deletion_and_insertion(self):
        assert word_error_rate("a b c d", "a b d").wer == pytest.approx(0.25)
        assert word_error_rate("a b c", "a b c d").wer == pytest.approx(0.3333, abs=1e-3)

    def test_scoring_ignores_case_and_punctuation(self):
        assert word_error_rate("Hello, world!", "hello world").wer == 0.0


class TestCliParser:
    def test_no_command_is_not_an_error(self):
        assert build_parser().parse_args([]).command is None

    def test_fetch_arguments(self):
        args = build_parser().parse_args(
            ["fetch", "https://ex.test/f", "--limit", "5", "--transcribe"])
        assert args.command == "fetch"
        assert args.limit == 5 and args.transcribe is True

    def test_limit_all_means_no_limit(self):
        assert build_parser().parse_args(["fetch", "--limit", "all"]).limit is None

    def test_negative_limit_is_rejected(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["fetch", "--limit", "-1"])

    def test_no_gui_prompt_flag_exists(self):
        """It was documented in the module docstring but never implemented."""
        assert build_parser().parse_args(["--no-gui-prompt"]).no_gui_prompt is True

    def test_hf_token_flag_exists(self):
        args = build_parser().parse_args(["fetch", "--hf-token", "hf_x"])
        assert args.hf_token == "hf_x"

    def test_every_subcommand_has_a_handler(self):
        from podharvest.cli import _HANDLERS
        parser = build_parser()
        actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
        for name in actions[0].choices:
            assert name in _HANDLERS, name
