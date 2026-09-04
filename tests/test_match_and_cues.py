"""Two ideas taken from the script podHarvest grew out of.

Michael Babcock's `feedParser.py` did two things this program did not: it let
you name a search term and take only the episodes matching it, and it beeped
as each download finished, at a rising pitch.

The first is an obvious gap -- podHarvest could only ever take "the first N".
The second is more interesting than it looks. podHarvest's activity log cannot
announce itself to a screen reader, and that is documented as the program's
most important limitation. A sound is not speech, but it is the difference
between a silent hour and knowing something happened.
"""

from __future__ import annotations

import inspect

import pytest

from podharvest import cues
from podharvest.harvest import match_episodes


class _Episode:
    def __init__(self, title: str) -> None:
        self.title = title


def _titles(episodes) -> list[str]:
    return [e.title for e in episodes]


class TestMatchingEpisodes:
    @pytest.fixture
    def episodes(self):
        return [
            _Episode("The Badger Interview"),
            _Episode("Interview: Badgers Revisited"),
            _Episode("Otters at Home"),
            _Episode("badger tracks in winter"),
        ]

    def test_it_matches_anywhere_in_the_title(self, episodes):
        assert _titles(match_episodes(episodes, "badger")) == [
            "The Badger Interview",
            "Interview: Badgers Revisited",
            "badger tracks in winter",
        ]

    def test_it_ignores_case(self, episodes):
        assert len(match_episodes(episodes, "BADGER")) == 3

    def test_every_word_must_appear_but_the_order_is_free(self, episodes):
        """"badger interview" should find it written either way round."""
        found = _titles(match_episodes(episodes, "badger interview"))
        assert found == ["The Badger Interview", "Interview: Badgers Revisited"]

    def test_an_empty_term_means_everything(self, episodes):
        assert match_episodes(episodes, "") == episodes
        assert match_episodes(episodes, "   ") == episodes

    def test_nothing_matching_is_an_empty_list_not_an_error(self, episodes):
        assert match_episodes(episodes, "aardvark") == []

    def test_an_episode_with_no_title_does_not_explode(self):
        class Untitled:
            title = None

        assert match_episodes([Untitled()], "badger") == []

    def test_it_does_not_search_the_show_notes(self):
        """A term buried in a paragraph of credits is not what was meant."""
        episode = _Episode("Otters at Home")
        episode.description = "with thanks to the badger appreciation society"
        assert match_episodes([episode], "badger") == []


class TestWhereTheFilterApplies:
    def test_it_runs_before_the_limit(self):
        """"5 episodes about badgers", not "badgers among the latest 5"."""
        from podharvest import harvest

        source = inspect.getsource(harvest.run_harvest)
        assert "match_episodes" in source
        assert source.index("match_episodes") < source.index("feed.episodes[:limit]")

    def test_it_says_how_many_matched(self):
        from podharvest import harvest

        source = inspect.getsource(harvest.run_harvest)
        assert "match(es)" in source or "episode(s) match" in source

    def test_nothing_matching_is_called_out(self):
        """Silently harvesting nothing looks identical to a broken feed."""
        from podharvest import harvest

        source = inspect.getsource(harvest.run_harvest)
        assert "Nothing matches" in source

    def test_it_is_a_command_line_option(self):
        from podharvest.cli import build_parser

        args = build_parser().parse_args(["fetch", "u", "--match", "badger"])
        assert args.match == "badger"

    def test_it_is_a_setting(self):
        from podharvest.config import Settings

        settings = Settings()
        assert settings.episode_match == ""
        settings.episode_match = "badger"
        assert Settings.from_dict(settings.to_dict()).episode_match == "badger"

    def test_the_window_hands_it_to_the_run(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._run_harvest_worker)
        assert "match=self.settings.episode_match" in source


class TestSoundCues:
    """Sound is the only progress report that does not need the log read."""

    def test_the_four_things_worth_hearing_have_cues(self):
        assert set(cues.TONES) == {"episode", "finished", "failed", "cancelled"}

    def test_they_are_told_apart_by_pitch_not_loudness(self):
        """A screen reader user hears these while doing something else."""
        pitches = {name: tuple(f for f, _d in tones)
                   for name, tones in cues.TONES.items()}
        assert len(set(pitches.values())) == len(pitches), "two cues sound alike"

    def test_finishing_rises_and_cancelling_falls(self):
        """Shape carries the meaning when you are not counting beeps."""
        finished = [f for f, _d in cues.TONES["finished"]]
        cancelled = [f for f, _d in cues.TONES["cancelled"]]
        assert finished == sorted(finished), "an ending should rise"
        assert cancelled == sorted(cancelled, reverse=True), "a stop should fall"

    def test_failure_is_the_lowest_thing_you_will_hear(self):
        lowest = min(f for f, _d in cues.TONES["failed"])
        others = [f for name, tones in cues.TONES.items() if name != "failed"
                  for f, _d in tones]
        assert lowest < min(others)

    def test_the_per_episode_cue_is_the_shortest(self):
        """It plays once per episode; on a long run anything else grates."""
        episode = sum(d for _f, d in cues.TONES["episode"])
        for name, tones in cues.TONES.items():
            if name != "episode":
                assert episode <= sum(d for _f, d in tones)

    def test_every_tone_is_in_a_range_a_laptop_can_reproduce(self):
        for name, tones in cues.TONES.items():
            for frequency, duration in tones:
                assert 300 <= frequency <= 2000, f"{name} at {frequency} Hz"
                assert 50 <= duration <= 400, f"{name} for {duration} ms"

    def test_switched_off_means_silent(self, monkeypatch):
        played = []
        monkeypatch.setattr(cues, "_play_windows", lambda t: played.append(t) or True)
        cues.play("episode", enabled=False)
        assert played == []

    def test_an_unknown_cue_is_ignored_rather_than_raised(self):
        """Decoration must never be able to fail a run."""
        cues.play("no-such-cue", enabled=True)

    def test_it_never_blocks_the_caller(self, monkeypatch):
        """winsound.Beep blocks for the tone; the UI thread calls this."""
        import threading

        started = threading.Event()
        release = threading.Event()

        def slow(_tones):
            started.set()
            release.wait(5)
            return True

        monkeypatch.setattr(cues, "_play_windows", slow)
        cues.play("episode", enabled=True)
        assert started.wait(5), "the cue never started"
        release.set()          # the caller got here without waiting for it

    def test_a_machine_with_no_way_to_make_a_sound_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(cues, "_play_windows", lambda _t: False)
        monkeypatch.setattr(cues, "_play_bell", lambda _t: False)
        cues.play("finished", enabled=True)


class TestTheCuesAreWiredIn:
    def test_an_episode_finishing_makes_a_sound(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._on_episode_progress)
        assert 'cues.play(' in source
        assert '"failed"' in source, "a failure should not sound like progress"

    def test_the_end_of_a_run_makes_a_different_one(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._finish_worker)
        assert "cues.play(" in source
        for outcome in ("failed", "cancelled", "finished"):
            assert f'"{outcome}"' in source

    def test_it_is_off_unless_asked_for(self):
        from podharvest.config import Settings

        assert Settings().sound_cues is False

    def test_the_setting_survives_a_round_trip(self):
        from podharvest.config import Settings

        settings = Settings()
        settings.sound_cues = True
        assert Settings.from_dict(settings.to_dict()).sound_cues is True

    def test_every_call_respects_the_setting(self):
        """A cue that plays with the setting off is a bug, not a feature."""
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame)
        assert source.count("cues.play(") == source.count("enabled=self.settings.sound_cues")

    def test_the_module_ships_in_the_frozen_build(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "podharvest.cues" in spec
