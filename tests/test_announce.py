"""Giving a run a voice, without breaking the no-dependencies promise."""

from __future__ import annotations

from podharvest import announce


class _Settings:
    """Only the flags `say` reads, so a test can state them plainly."""

    def __init__(self, **flags):
        self.announce_completions = flags.get("completions", False)
        self.announce_progress = flags.get("progress", False)
        self.announce_errors = flags.get("errors", False)
        self.announce_braille = flags.get("braille", False)


class TestItIsSafeWithoutTheComponent:
    """Nothing here may raise, ever. An app that dies because a screen
    reader was closed is worse than one that says nothing."""

    def test_speaking_without_the_component_returns_false(self, monkeypatch):
        monkeypatch.setattr(announce, "_output", lambda: None)
        assert announce.speak("hello") is False

    def test_brailling_without_the_component_returns_false(self, monkeypatch):
        monkeypatch.setattr(announce, "_output", lambda: None)
        assert announce.braille("hello") is False

    def test_a_reader_that_goes_away_mid_sentence_is_not_fatal(self, monkeypatch):
        class Broken:
            def output(self, *_a, **_k):
                raise RuntimeError("the screen reader exited")

            def braille(self, *_a, **_k):
                raise RuntimeError("the screen reader exited")

        monkeypatch.setattr(announce, "_output", lambda: Broken())
        assert announce.speak("hello") is False
        assert announce.braille("hello") is False

    def test_availability_is_answerable_without_installing_anything(self):
        assert isinstance(announce.is_available(), bool)


class TestCategories:
    def test_a_category_that_is_off_says_nothing(self, monkeypatch):
        spoken = []
        monkeypatch.setattr(announce, "speak",
                            lambda text, **_k: spoken.append(text) or True)
        announce.say("done", category="completions", settings=_Settings())
        assert spoken == []

    def test_a_category_that_is_on_speaks(self, monkeypatch):
        spoken = []
        monkeypatch.setattr(announce, "speak",
                            lambda text, **_k: spoken.append(text) or True)
        announce.say("done", category="completions",
                     settings=_Settings(completions=True))
        assert spoken == ["done"]

    def test_an_unknown_category_is_ignored_rather_than_spoken(self, monkeypatch):
        """A typo at a call site should be silence, not a surprise."""
        spoken = []
        monkeypatch.setattr(announce, "speak",
                            lambda text, **_k: spoken.append(text) or True)
        announce.say("hm", category="nonsense",
                     settings=_Settings(completions=True, progress=True,
                                        errors=True))
        assert spoken == []

    def test_an_error_interrupts_and_a_progress_note_does_not(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            announce, "speak",
            lambda text, **kw: calls.append((text, kw.get("interrupt"))) or True)
        announce.say("broke", category="errors", settings=_Settings(errors=True))
        announce.say("3 of 9", category="progress",
                     settings=_Settings(progress=True))
        assert calls == [("broke", True), ("3 of 9", False)]


class TestBrailleIsSeparate:
    """Braille follows speech but is its own choice."""

    def _capture(self, monkeypatch, *, spoke=True):
        brailled = []
        monkeypatch.setattr(announce, "speak", lambda text, **_k: spoke)
        monkeypatch.setattr(announce, "braille",
                            lambda text: brailled.append(text) or True)
        return brailled

    def test_braille_is_not_sent_when_its_box_is_off(self, monkeypatch):
        brailled = self._capture(monkeypatch)
        announce.say("done", category="completions",
                     settings=_Settings(completions=True))
        assert brailled == []

    def test_braille_is_sent_when_its_box_is_on(self, monkeypatch):
        brailled = self._capture(monkeypatch)
        announce.say("done", category="completions",
                     settings=_Settings(completions=True, braille=True))
        assert brailled == ["done"]

    def test_braille_is_not_attempted_when_speech_failed(self, monkeypatch):
        """No speech means no screen reader, which means no braille."""
        brailled = self._capture(monkeypatch, spoke=False)
        announce.say("done", category="completions",
                     settings=_Settings(completions=True, braille=True))
        assert brailled == []


class TestTheSettings:
    def test_every_announcement_setting_defaults_to_off(self):
        from podharvest.config import Settings

        settings = Settings()
        assert settings.announce_completions is False
        assert settings.announce_progress is False
        assert settings.announce_errors is False
        assert settings.announce_braille is False

    def test_they_survive_a_round_trip(self):
        from podharvest.config import Settings

        settings = Settings()
        settings.announce_errors = True
        settings.announce_braille = True
        restored = Settings.from_dict(settings.to_dict())
        assert restored.announce_errors is True
        assert restored.announce_braille is True
