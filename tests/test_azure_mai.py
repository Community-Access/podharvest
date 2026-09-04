"""Azure MAI-Transcribe-2, wired in the way a preview service should be.

The PRD is explicit about the posture: build it behind a flag, never make it
the only path, and be able to switch it off quickly if the preview regresses.
These check that each of those is true of the code rather than only of the
intention.

Nothing here talks to Azure. The request bodies, the configuration checks and
the reply parsing are all exercised against fixed data -- which is most of
what can go wrong, and all of what can be checked without somebody's
subscription.
"""

from __future__ import annotations

import inspect

import pytest

from podharvest import azure_mai
from podharvest.util import HarvestError


def _config(**overrides) -> azure_mai.Configuration:
    base = {
        "enabled": True,
        "has_key": True,
        "endpoint": "https://r.cognitiveservices.azure.com",
        "region": "eastus",
    }
    base.update(overrides)
    return azure_mai.Configuration(**base)


class TestThePreviewPosture:
    def test_it_is_off_until_it_is_turned_on(self):
        from podharvest.config import Settings

        assert Settings().azure_mai_enabled is False

    def test_a_key_alone_does_not_put_it_in_the_picker(self, monkeypatch):
        """A key left over from trying it once must not switch a preview
        service back on behind somebody's back."""
        from podharvest import cloud as cloud_mod
        from podharvest.config import Settings

        monkeypatch.setattr(cloud_mod, "load_key", lambda _a, _p: "a-key")
        settings = Settings()

        settings.azure_mai_enabled = False
        offered = cloud_mod.available_cloud_models(None, kind="asr",
                                                   settings=settings)
        assert not any(c.provider == "azure-mai" for c in offered)

        settings.azure_mai_enabled = True
        offered = cloud_mod.available_cloud_models(None, kind="asr",
                                                   settings=settings)
        assert any(c.provider == "azure-mai" for c in offered)

    def test_the_flag_does_not_affect_the_other_providers(self, monkeypatch):
        from podharvest import cloud as cloud_mod
        from podharvest.config import Settings

        monkeypatch.setattr(cloud_mod, "load_key", lambda _a, _p: "a-key")
        offered = cloud_mod.available_cloud_models(None, kind="asr",
                                                   settings=Settings())
        assert any(c.provider == "openai" for c in offered)
        assert any(c.provider == "gemini" for c in offered)

    def test_the_provider_declares_what_makes_it_unusual(self):
        from podharvest.cloud import PROVIDERS

        provider = PROVIDERS["azure-mai"]
        assert provider.preview is True
        assert provider.needs_endpoint is True
        assert provider.can_transcribe is True
        assert provider.can_summarise is False, "it is a speech service"

    def test_no_price_or_speed_is_claimed(self):
        """Microsoft has not published a MAI price. A confident wrong number
        is worse than no number."""
        from podharvest.cloud import CLOUD_ASR_CHOICES

        found = next(c for c in CLOUD_ASR_CHOICES if c.provider == "azure-mai")
        assert found.cost_per_audio_minute == 0.0
        assert found.speed_measured is False
        assert "preview" in found.notes.lower()

    def test_the_api_version_is_pinned_and_changeable(self):
        """A preview API that changes shape under a released program is a bug
        report nobody can act on."""
        from podharvest.config import Settings

        assert azure_mai.DEFAULT_API_VERSION
        assert Settings().azure_speech_api_version == azure_mai.DEFAULT_API_VERSION


class TestSayingWhatIsMissing:
    def test_everything_missing_is_reported_at_once(self):
        problems = azure_mai.Configuration().problems()
        assert len(problems) == 4
        joined = " ".join(problems).lower()
        for wanted in ("switched off", "key", "endpoint", "region"):
            assert wanted in joined, wanted

    def test_a_fully_configured_provider_has_no_complaints(self):
        assert _config().problems() == []

    def test_an_insecure_endpoint_is_refused(self):
        """A key is not worth sending in the clear."""
        problems = _config(endpoint="http://r.example.com").problems()
        assert any("https" in p for p in problems)

    def test_an_unlisted_region_warns_rather_than_refusing(self):
        """Availability changes. A list compiled at build time must not be a
        gate on a region added since."""
        config = _config(region="westeurope")
        assert config.problems() == []
        assert "westeurope" in config.region_warning()

    def test_a_listed_region_says_nothing(self):
        for region in azure_mai.KNOWN_REGIONS:
            assert _config(region=region).region_warning() == ""

    def test_the_check_reads_settings_and_the_keystore(self):
        source = inspect.getsource(azure_mai.configuration_from)
        assert "load_key" in source
        assert "azure_speech_endpoint" in source


class TestTheRequest:
    def test_the_url_is_the_documented_one(self):
        url = azure_mai.transcribe_url(_config())
        assert url.startswith("https://r.cognitiveservices.azure.com/")
        assert "/speechtotext/transcriptions:transcribe" in url
        assert f"api-version={azure_mai.DEFAULT_API_VERSION}" in url

    def test_enhanced_mode_names_the_model(self):
        definition = azure_mai.build_definition(
            _config(), want_word_timestamps=True, want_speakers=True)
        assert definition["enhancedMode"]["enabled"] is True
        assert definition["enhancedMode"]["model"] == "MAI-Transcribe-2"

    def test_automatic_detection_sends_no_locale_at_all(self):
        """Microsoft's own guidance: a locale is a strong hint, and a strong
        hint towards the wrong language is worse than none."""
        definition = azure_mai.build_definition(
            _config(language="auto"), want_word_timestamps=False,
            want_speakers=False)
        assert "locales" not in definition

    def test_naming_a_language_sends_exactly_one(self):
        for code in ("en", "es"):
            definition = azure_mai.build_definition(
                _config(language=code), want_word_timestamps=False,
                want_speakers=False)
            assert definition["locales"] == [code]

    def test_only_the_two_supported_languages_are_offered(self):
        codes = {code for code, _label in azure_mai.LANGUAGES}
        assert codes == {"auto", "en", "es"}

    def test_the_style_reaches_the_request(self):
        for style in ("clean", "verbatim"):
            definition = azure_mai.build_definition(
                _config(style=style), want_word_timestamps=False,
                want_speakers=False)
            assert definition["enhancedMode"]["modelOptions"][
                "transcribeStyle"] == style

    def test_a_nonsense_style_falls_back_rather_than_being_sent(self):
        definition = azure_mai.build_definition(
            _config(style="sideways"), want_word_timestamps=False,
            want_speakers=False)
        assert definition["enhancedMode"]["modelOptions"][
            "transcribeStyle"] == "clean"

    def test_word_timings_are_only_asked_for_when_wanted(self):
        options = azure_mai.build_definition(
            _config(), want_word_timestamps=True,
            want_speakers=False)["enhancedMode"]["modelOptions"]
        assert options["timestamps"] == "word"
        options = azure_mai.build_definition(
            _config(), want_word_timestamps=False,
            want_speakers=False)["enhancedMode"]["modelOptions"]
        assert options["timestamps"] == "segment"

    def test_diarization_is_only_asked_for_when_wanted(self):
        assert "diarization" in azure_mai.build_definition(
            _config(), want_word_timestamps=False, want_speakers=True)
        assert "diarization" not in azure_mai.build_definition(
            _config(), want_word_timestamps=False, want_speakers=False)

    def test_phrases_are_sent_and_blanks_are_not(self):
        definition = azure_mai.build_definition(
            _config(phrases=["ACB Media", "  ", "", "Pinecast"]),
            want_word_timestamps=False, want_speakers=False)
        assert definition["phraseList"]["phrases"] == ["ACB Media", "Pinecast"]

    def test_no_phrases_means_no_phrase_list(self):
        definition = azure_mai.build_definition(
            _config(phrases=[]), want_word_timestamps=False,
            want_speakers=False)
        assert "phraseList" not in definition


class TestReliability:
    def test_only_transient_failures_are_retried(self):
        """Bad audio, a bad key or a wrong region give the same answer more
        slowly the second time."""
        for status in (408, 429, 500, 502, 503, 504):
            assert status in azure_mai.RETRY_STATUS
        for status in (400, 401, 403, 404, 413, 415):
            assert status not in azure_mai.RETRY_STATUS

    def test_there_is_a_ceiling_on_attempts(self):
        assert 1 < azure_mai.MAX_ATTEMPTS <= 6

    def test_the_size_limit_is_below_what_azure_documents(self):
        assert azure_mai.MAX_UPLOAD_BYTES <= 300 * 1024 * 1024

    def test_a_status_code_is_recognised_in_an_error_message(self):
        assert azure_mai._status_in("Azure said 429: too many requests") == 429
        assert azure_mai._status_in("connection reset") is None


class TestReadingTheReply:
    def _payload(self, **overrides):
        payload = {
            "durationMilliseconds": 12000,
            "phrases": [
                {"text": "Hello there.", "offsetMilliseconds": 0,
                 "durationMilliseconds": 4000, "speaker": 1, "locale": "en-US"},
                {"text": "And hello to you.", "offsetMilliseconds": 4000,
                 "durationMilliseconds": 8000, "speaker": 2, "locale": "en-US"},
            ],
        }
        payload.update(overrides)
        return payload

    def test_phrases_become_timed_segments(self):
        segments, language, duration, warnings = azure_mai.parse_response(
            self._payload())
        assert [s.text for s in segments] == ["Hello there.", "And hello to you."]
        assert segments[0].start == 0.0 and segments[0].end == 4.0
        assert segments[1].start == 4.0
        assert language == "en"
        assert duration == 12.0
        assert warnings == []

    def test_milliseconds_become_seconds(self):
        """Azure reports milliseconds; everything downstream is in seconds."""
        segments, _lang, duration, _warnings = azure_mai.parse_response(
            self._payload(durationMilliseconds=90000))
        assert duration == 90.0
        assert segments[0].end == 4.0

    def test_a_reply_with_no_timings_says_what_was_lost(self):
        """Quietly returning less than was asked for is the failure mode the
        PRD names."""
        segments, _language, _duration, warnings = azure_mai.parse_response({
            "durationMilliseconds": 9000,
            "combinedPhrases": [{"text": "One block of text."}],
        })
        assert len(segments) == 1
        assert any("no timestamps" in w for w in warnings)

    def test_an_empty_reply_is_an_error_not_an_empty_transcript(self):
        with pytest.raises(HarvestError):
            azure_mai.parse_response({"phrases": []})

    def test_the_duration_falls_back_to_the_last_segment(self):
        _segments, _language, duration, _warnings = azure_mai.parse_response(
            self._payload(durationMilliseconds=0))
        assert duration == 12.0

    def test_junk_among_the_phrases_is_skipped(self):
        payload = self._payload()
        payload["phrases"].insert(1, "not a phrase")
        payload["phrases"].append({"text": "   "})
        segments, _lang, _dur, _warn = azure_mai.parse_response(payload)
        assert len(segments) == 2


class TestItIsWiredIn:
    def test_the_engine_is_reachable_from_the_dispatcher(self):
        from podharvest import cloud as cloud_mod

        source = inspect.getsource(cloud_mod.build_cloud_engine)
        assert "azure-mai" in source
        assert "AzureMaiTranscribeEngine" in source

    def test_it_is_listed_as_a_transcription_provider(self):
        from podharvest.cloud import ALL_PROVIDERS, TRANSCRIBE_PROVIDERS

        assert "azure-mai" in TRANSCRIBE_PROVIDERS
        assert "azure-mai" in ALL_PROVIDERS

    def test_it_is_in_the_model_catalogue_once(self):
        from podharvest.cloud import CLOUD_ASR_CHOICES

        found = [c for c in CLOUD_ASR_CHOICES if c.provider == "azure-mai"]
        assert len(found) == 1
        assert found[0].model == "MAI-Transcribe-2"
        assert found[0].speakers_built_in is True

    def test_the_json_part_is_typed_as_json(self):
        """Most APIs accept an untyped text part. Azure rejects it."""
        from podharvest import cloud as cloud_mod

        source = inspect.getsource(cloud_mod._multipart_with_json)
        assert "application/json" in source

    def test_the_settings_all_round_trip(self):
        from podharvest.config import Settings

        settings = Settings()
        settings.azure_mai_enabled = True
        settings.azure_speech_endpoint = "https://r.cognitiveservices.azure.com"
        settings.azure_speech_region = "westus"
        settings.mai_language = "es"
        settings.mai_transcribe_style = "verbatim"
        settings.mai_phrases = ["ACB Media"]
        restored = Settings.from_dict(settings.to_dict())
        assert restored.azure_mai_enabled is True
        assert restored.azure_speech_region == "westus"
        assert restored.mai_language == "es"
        assert restored.mai_transcribe_style == "verbatim"
        assert restored.mai_phrases == ["ACB Media"]

    def test_nonsense_settings_are_cleaned_rather_than_sent(self):
        from podharvest.config import Settings

        restored = Settings.from_dict({
            "mai_language": "fr", "mai_transcribe_style": "sideways",
            "azure_speech_api_version": "", "mai_phrases": ["  ", "ACB "]})
        assert restored.mai_language == "auto"
        assert restored.mai_transcribe_style == "clean"
        assert restored.azure_speech_api_version
        assert restored.mai_phrases == ["ACB"]

    def test_the_key_is_never_written_to_the_settings_file(self):
        """Every other provider's key goes to the credential store; so does
        this one, and there must be no field tempting it into a file."""
        from podharvest.config import Settings

        keys = Settings().to_dict()
        assert not any("key" in name.lower() and "azure" in name.lower()
                       for name in keys)

    def test_the_settings_window_offers_all_of_it(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.SettingsDialog._build_mai_settings)
        for control in ("chk_mai_enabled", "mai_endpoint_ctrl",
                        "mai_region_ctrl", "mai_language_choice",
                        "mai_style_choice", "mai_phrases_ctrl",
                        "chk_mai_diarize", "chk_mai_words"):
            assert control in source, control

    def test_the_setup_check_sends_nothing_anywhere(self):
        """It reports what is missing; it is not a connection test."""
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.SettingsDialog._on_check_mai)
        for forbidden in ("_post", "urlopen", "transcribe_url", "HttpClient"):
            assert forbidden not in source, forbidden

    def test_the_module_ships(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "podharvest.azure_mai" in spec
