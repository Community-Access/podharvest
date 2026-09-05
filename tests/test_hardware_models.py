"""Which models a machine is offered, and why one must not come and go.

The list of models offered has to be a property of the machine, not of what
happens to be open on it. Filtering against free RAM made models appear and
disappear between one launch and the next, and the one it hid most often was
the model that exists for exactly the machines that need it.
"""

from __future__ import annotations

from podharvest import hardware as hw_mod


def _machine(*, total_gb: float, free_gb: float, cuda: bool = False):
    """A plain CPU machine with the memory figures we want to test.

    `accelerator` is derived from the GPU list and `has_cuda`, not set, so
    the flag is what a test controls.
    """
    return hw_mod.Hardware(
        cpu_name="Test CPU",
        ram_total_bytes=int(total_gb * hw_mod.GB),
        ram_available_bytes=int(free_gb * hw_mod.GB),
        has_cuda=cuda,
    )


def _model_names(machine) -> set[str]:
    return {c.model for c in hw_mod.available_models(machine)}


class TestTheListDoesNotDependOnWhatIsOpen:
    def test_a_busy_machine_offers_what_an_idle_one_does(self):
        """The bug: free RAM decided the list, so it changed hour to hour.

        Eight gigabytes of RAM is eight gigabytes whether or not a browser
        is using six of them right now. A model offered at breakfast and
        gone by lunchtime is indistinguishable from a broken program.
        """
        idle = _model_names(_machine(total_gb=8, free_gb=7))
        busy = _model_names(_machine(total_gb=8, free_gb=1.2))
        assert idle == busy

    def test_the_cpu_parakeet_survives_a_busy_machine(self):
        """The model most often hidden, on the machines that most need it.

        Parakeet TDT via sherpa-onnx is the multilingual model that runs on
        plain CPU. Hiding it when memory is momentarily tight took it away
        from exactly the people it was added for.
        """
        busy = _model_names(_machine(total_gb=8, free_gb=1.2))
        assert any("parakeet-tdt" in name for name in busy), (
            "the CPU Parakeet must be offered on an 8 GB machine even when "
            "little of that memory is free right now")

    def test_a_genuinely_small_machine_is_still_told_the_truth(self):
        """Half of very little is still very little. The floor is not a lie."""
        tiny = _model_names(_machine(total_gb=2, free_gb=1.5))
        assert not any("0.6b" in name for name in tiny), (
            "a 2 GB machine should not be offered a model needing 2.5 GB")

    def test_there_is_always_something_to_offer(self):
        """An empty model list is a dead end, whatever the machine."""
        assert _model_names(_machine(total_gb=1, free_gb=0.2))
