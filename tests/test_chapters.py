"""Chapter marker parsing, spacing and the mechanical-grid guard."""

from __future__ import annotations

from podharvest.enrich import (
    _looks_mechanical,
    _parse_chapters,
    format_chapters,
    timestamped_text,
)


class _Seg:
    def __init__(self, start: float, text: str) -> None:
        self.start = start
        self.text = text


class TestTimestampedText:
    def test_renders_clock_times(self):
        out = timestamped_text([_Seg(0, "Hello"), _Seg(3725, "Later")])
        assert out.splitlines() == ["[00:00:00] Hello", "[01:02:05] Later"]

    def test_skips_empty_segments(self):
        assert timestamped_text([_Seg(0, "   "), _Seg(5, "Real")]) == "[00:00:05] Real"


class TestParseChapters:
    def test_accepts_the_shapes_models_actually_emit(self):
        reply = (
            "Here are the chapters:\n"
            "- 00:00:00 - Introduction\n"
            "* 3:02 - Portion control\n"
            "2. [00:15:30] Audience questions\n"
        )
        assert _parse_chapters(reply, 1800) == [
            (0, "Introduction"), (182, "Portion control"), (930, "Audience questions")]

    def test_leading_digits_of_a_timestamp_are_not_eaten_as_a_bullet(self):
        # Regression: stripping "0123456789" from the left destroyed the hour.
        assert _parse_chapters("00:05:00 - Something", 1800) == [(300, "Something")]

    def test_drops_times_past_the_end_of_the_episode(self):
        assert _parse_chapters("99:00:00 - Impossible", 1800) == []

    def test_drops_near_duplicates(self):
        reply = "00:10:00 - First\n00:10:05 - Practically the same moment"
        assert len(_parse_chapters(reply, 1800)) == 1


class TestMechanicalGuard:
    def test_a_chapter_every_minute_is_rejected(self):
        # The real failure: a weak model listed the timeline instead of finding
        # topic changes, producing 34 chapters exactly 60 seconds apart.
        grid = [(60 * i, f"Topic {i}") for i in range(1, 35)]
        assert _looks_mechanical(grid) is True

    def test_genuine_uneven_boundaries_are_kept(self):
        real = [(0, "Welcome"), (34, "Guest"), (69, "Disclaimer"),
                (90, "Kitchens"), (312, "Portions"), (930, "Questions")]
        assert _looks_mechanical(real) is False

    def test_too_few_chapters_to_judge(self):
        assert _looks_mechanical([(0, "a"), (60, "b"), (120, "c")]) is False


class TestFormatChapters:
    def test_each_chapter_ends_where_the_next_begins(self):
        out = format_chapters([(0, "One"), (60, "Two")], 180)
        assert "**00:00:00 - 00:01:00**  One" in out
        assert "**00:01:00 - 00:03:00**  Two" in out

    def test_empty_list_produces_nothing(self):
        assert format_chapters([], 180) == ""


class TestKeyOwnership:
    """Anthropic, OpenAI and OpenRouter keys all begin "sk-", so pasting the
    wrong line out of a list of keys is easy and the resulting 401 says
    nothing useful."""

    def test_recognises_each_issuer(self):
        from podharvest.cloud import _key_belongs_to
        assert _key_belongs_to("sk-ant-abc123") == "anthropic"
        assert _key_belongs_to("sk-or-v1-abc123") == "openrouter"
        assert _key_belongs_to("sk-proj-abc123") == "openai"
        assert _key_belongs_to("sk-svcacct-abc123") == "openai"
        assert _key_belongs_to("AIzaSyDabc123") == "gemini"
        assert _key_belongs_to("sk-abc123") == "openai"

    def test_longer_prefixes_win(self):
        # "sk-ant-" must not be read as a bare OpenAI "sk-".
        from podharvest.cloud import _key_belongs_to
        assert _key_belongs_to("sk-ant-anything") != "openai"

    def test_unknown_shape_is_not_guessed(self):
        from podharvest.cloud import _key_belongs_to
        assert _key_belongs_to("3bffe8ff78f2.H4PgQZ") is None
        assert _key_belongs_to("") is None

    def test_article_agrees_with_the_name(self):
        from podharvest.cloud import _article
        assert _article("OpenAI") == "an OpenAI"
        assert _article("Anthropic") == "an Anthropic"
        assert _article("Google Gemini") == "a Google Gemini"

    def test_wrong_provider_is_reported_without_a_network_call(self, tmp_path):
        # An obviously-wrong key must be caught by shape, before any request.
        from podharvest import appspace
        from podharvest.cloud import verify_key
        ok, message = verify_key(appspace.resolve(), "openai", "sk-ant-not-a-real-key")
        assert ok is False
        assert "Anthropic" in message


class TestMoneyWording:
    """Per-minute rates are hand-copied from provider pricing pages, so a
    figure like "$9.72" claims accuracy the input does not have."""

    def test_rounds_to_honest_precision(self):
        from podharvest.estimate import money
        assert money(0.02) == "a few cents"
        assert money(0.40) == "40 cents"
        assert money(3.24) == "$3"
        assert money(9.72) == "$10"
        assert money(87.0) == "$85"

    def test_zero_and_negative(self):
        from podharvest.estimate import money
        assert money(0) == "nothing"
        assert money(-1) == "nothing"


class TestPriceProvenance:
    def test_a_stale_price_says_so_and_links_out(self):
        from podharvest import cloud
        from podharvest.estimate import describe_model
        openai_model = next(c for c in cloud.CLOUD_ASR_CHOICES if c.provider == "openai")
        text = describe_model(openai_model, 3600)
        assert cloud.PRICES_CHECKED in text
        assert "not updated automatically" in text
        assert cloud.PROVIDERS["openai"].pricing_url in text

    def test_only_openrouter_claims_live_pricing(self):
        from podharvest.cloud import PROVIDERS
        live = {n for n, p in PROVIDERS.items() if p.live_pricing}
        assert live == {"openrouter"}

    def test_every_provider_links_to_its_prices(self):
        from podharvest.cloud import PROVIDERS
        assert all(p.pricing_url.startswith("https://") for p in PROVIDERS.values())

    def test_live_prices_are_empty_without_a_key(self):
        from podharvest import appspace
        from podharvest.cloud import live_prices
        assert live_prices(appspace.resolve(), "openai") == {}
