"""The cloud transcription engines, and the catalogue they serve.

Nothing here talks to a provider. The request assembly and reply parsing are
what break, and both are checkable against fixed data; the two additions in
this round (Groq, ElevenLabs) were chosen partly because QUILL already vetted
the same two, so the family offers the same choices everywhere.
"""

from __future__ import annotations

import inspect

import pytest

from podharvest import cloud
from podharvest.util import HarvestError


class TestTheCatalogue:
    def _by_model(self, model):
        return next(c for c in cloud.CLOUD_ASR_CHOICES if c.model == model)

    def test_groq_whisper_is_offered_with_timestamps(self):
        choice = self._by_model("whisper-large-v3-turbo")
        assert choice.provider == "groq"
        assert choice.provides_timestamps is True

    def test_scribe_is_offered_with_speakers_built_in(self):
        choice = self._by_model("scribe_v1")
        assert choice.provider == "elevenlabs"
        assert choice.speakers_built_in is True
        assert choice.provides_timestamps is True

    def test_every_cloud_model_has_a_provider_entry(self):
        for choice in cloud.CLOUD_ASR_CHOICES:
            assert choice.provider in cloud.PROVIDERS, choice.model
            assert cloud.PROVIDERS[choice.provider].can_transcribe, choice.model

    def test_every_transcribing_provider_has_an_upload_cap_or_a_reason(self):
        """A provider with no cap silently gets the 20 MB default, which for
        ElevenLabs would split files that fit in one request."""
        for name in ("openai", "gemini", "groq", "elevenlabs"):
            assert name in cloud.PROVIDER_MAX_UPLOAD_BYTES, name

    def test_every_provider_gets_a_key_field_automatically(self):
        for name in ("groq", "elevenlabs"):
            assert name in cloud.ALL_PROVIDERS

    def test_the_dispatcher_knows_every_transcribing_provider(self):
        source = inspect.getsource(cloud.build_cloud_engine)
        for name in cloud.TRANSCRIBE_PROVIDERS:
            assert name in source, name


class TestTheOpenAiShape:
    def test_groq_is_the_openai_engine_with_different_constants(self):
        """One code path, tested once, rather than a near-copy that drifts."""
        assert issubclass(cloud.GroqTranscribeEngine, cloud.OpenAITranscribeEngine)
        assert cloud.GroqTranscribeEngine.PROVIDER == "groq"
        assert cloud.GroqTranscribeEngine.URL.startswith("https://api.groq.com/")
        assert cloud.GroqTranscribeEngine.transcribe is cloud.OpenAITranscribeEngine.transcribe

    def test_timestamps_come_from_the_catalogue_not_the_model_name(self):
        """The hardcoded whisper-1 check was why only whisper-1 ever asked for
        segments -- Groq's Whisper would have been silently timestamp-less."""
        source = inspect.getsource(cloud.OpenAITranscribeEngine.transcribe)
        assert "provides_timestamps" in source
        assert 'model == "whisper-1"' not in source

    def test_the_engine_tag_names_the_actual_provider(self):
        source = inspect.getsource(cloud.OpenAITranscribeEngine.transcribe)
        assert 'f"cloud:{self.PROVIDER}"' in source


class TestScribeSegments:
    def _engine(self):
        choice = next(c for c in cloud.CLOUD_ASR_CHOICES if c.model == "scribe_v1")
        return cloud.ElevenLabsTranscribeEngine(app=None, choice=choice)

    def _word(self, text, start, end, speaker="speaker_0", kind="word"):
        return {"text": text, "start": start, "end": end,
                "speaker_id": speaker, "type": kind}

    def test_words_become_one_segment_when_nothing_breaks_them(self):
        segments = self._engine()._segments_from({"words": [
            self._word("Hello", 0.0, 0.4), self._word("there", 0.5, 0.9)]})
        assert len(segments) == 1
        assert segments[0].text == "Hello there"
        assert segments[0].start == 0.0 and segments[0].end == 0.9

    def test_a_speaker_change_starts_a_new_segment(self):
        segments = self._engine()._segments_from({"words": [
            self._word("Hello", 0.0, 0.4),
            self._word("Hi", 0.5, 0.8, speaker="speaker_1")]})
        assert [s.text for s in segments] == ["Hello", "Hi"]
        assert segments[0].speaker == "Speaker 0"
        assert segments[1].speaker == "Speaker 1"

    def test_a_long_pause_starts_a_new_segment(self):
        segments = self._engine()._segments_from({"words": [
            self._word("End.", 0.0, 0.4), self._word("New", 2.0, 2.4)]})
        assert len(segments) == 2

    def test_unbroken_speech_is_still_cut_into_readable_lengths(self):
        words = [self._word(f"w{n}", n * 0.5, n * 0.5 + 0.4) for n in range(120)]
        segments = self._engine()._segments_from({"words": words})
        assert len(segments) > 1
        assert all(s.end - s.start <= 31.0 for s in segments)

    def test_spacing_tokens_are_not_words(self):
        segments = self._engine()._segments_from({"words": [
            self._word("Hello", 0.0, 0.4),
            self._word(" ", 0.4, 0.5, kind="spacing"),
            self._word("there", 0.5, 0.9)]})
        assert segments[0].text == "Hello there"

    def test_a_reply_with_only_text_still_yields_a_transcript(self):
        segments = self._engine()._segments_from({"text": "Just words."})
        assert segments[0].text == "Just words."

    def test_an_empty_reply_is_an_error_not_an_empty_transcript(self):
        with pytest.raises(HarvestError):
            self._engine()._segments_from({"words": [], "text": ""})
