"""Every control must explain itself. This is what checks that it does.

The same gate QUILL runs over each of its apps (`quill/tools/*_help_audit.py`),
sized for one flat package. It AST-scans podHarvest's wx modules for every
control a person can focus, and asks one question of each: does the code that
builds it also say what it is for, right there?

**Right there** is the whole point. Help set anywhere else -- in a loop that
runs later, in a dictionary consulted at show time -- may well work, but it
cannot be verified by reading the construction site, and what cannot be
verified rots. So the rule is inline: `explain(...)`, `SetToolTip(...)` or
`SetHelpText(...)` on the control, in the same function that made it.

A new control is `missing` until somebody writes a sentence, and `missing` is
a failing build. That is deliberate: the alternative is a control that answers
F1 with its name and nothing else, which reads to a screen-reader user as
"this program does not know what this is either".

Run it::

    python -m podharvest.help_audit          # report, exit 1 on anything missing
    python -m podharvest.help_audit --write  # record the reviewed snapshot
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SNAPSHOT = _ROOT.parent / "tests" / "help_inventory.json"

#: The modules that build windows. Everything else in the package is wx-free.
SCAN_FILES: tuple[str, ...] = (
    "gui.py", "editor.py", "player.py", "reader.py", "discover.py",
    "status_bar.py", "chapter_jump.py", "transcript_search.py",
    "model_download.py", "model_manager.py",
)

#: wx classes a person can focus and therefore press F1 on. `StaticText` is
#: excluded: it names the control beside it and is not a focus stop.
HELPABLE: frozenset[str] = frozenset({
    "Button", "ToggleButton", "BitmapButton", "CheckBox", "RadioBox",
    "RadioButton", "TextCtrl", "SearchCtrl", "ComboBox", "Choice", "ListBox",
    "CheckListBox", "ListCtrl", "TreeCtrl", "Slider", "SpinCtrl",
    "SpinCtrlDouble", "Gauge", "Notebook",
})

#: The calls that count as authoring help on a control.
HELP_CALLS: frozenset[str] = frozenset({"SetToolTip", "SetHelpText"})

#: Statuses a site can carry in the snapshot.
HELPED = "helped"
MISSING = "missing"
#: Deliberately unhelped, with the reason in the diff that added it. Rare: a
#: control whose own name says everything and whose role line covers the rest.
OPT_OUT = "opt-out"


@dataclass(frozen=True, slots=True)
class Site:
    """One control construction, and whether its own code explains it."""

    key: str
    helped: bool


def _target_names(node: ast.AST) -> set[str]:
    """The names a construction is assigned to, if any."""
    names: set[str] = set()
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        return names
    for target in targets:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _helped_in_scope(scope: ast.AST, targets: set[str]) -> bool:
    """Whether *scope* explains one of *targets* inline.

    Either ``x.SetToolTip(...)``/``x.SetHelpText(...)`` on the control, or
    ``explain(x, ...)``, or a ``helpText=``/``toolTip=`` keyword at
    construction. A control built inside a loop over a table counts when the
    loop body explains the loop variable -- the sentence is still authored at
    the construction site, which is what this is checking for.
    """
    if not targets:
        return False
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in HELP_CALLS:
            owner = func.value
            if isinstance(owner, ast.Name) and owner.id in targets:
                return True
            if isinstance(owner, ast.Attribute) and owner.attr in targets:
                return True
        if isinstance(func, ast.Name) and func.id == "explain" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name) and first.id in targets:
                return True
            if isinstance(first, ast.Attribute) and first.attr in targets:
                return True
        if isinstance(func, ast.Attribute) and func.attr == "explain" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name) and first.id in targets:
                return True
            if isinstance(first, ast.Attribute) and first.attr in targets:
                return True
    return False


def _wx_subclasses(tree: ast.AST) -> dict[str, str]:
    """Local classes that extend a helpable wx control: name -> wx class.

    A control built through a subclass is still a control a person focuses
    and presses F1 on, and it would otherwise leave the gate's sight the
    moment somebody wrote ``class MyButton(wx.Button)``. That is not
    hypothetical: taking the status bar's cells out of the tab order needed
    exactly such a subclass, and the gate quietly stopped counting them.

    One level deep, which is all this codebase has and all a rule anybody
    can remember should need.
    """
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            if (isinstance(base, ast.Attribute)
                    and isinstance(base.value, ast.Name)
                    and base.value.id == "wx"
                    and base.attr in HELPABLE):
                found[node.name] = base.attr
    return found


def _wx_class(call: ast.Call, subclasses: dict[str, str] | None = None) -> str:
    """``wx.Button`` -> ``Button``; anything else -> ""."""
    func = call.func
    if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.value.id == "wx"):
        return func.attr
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute):
        # wx.media.MediaCtrl and friends: not focusable help targets.
        return ""
    # A local subclass of a wx control, and a variable holding one -- the
    # status bar builds its cells through `button_class(...)` so the class
    # can be made against the injected wx module.
    if isinstance(func, ast.Name) and subclasses:
        return subclasses.get(func.id, "")
    return ""


def scan_file(path: Path) -> list[Site]:
    """Every helpable control built in *path*, and whether it is explained."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module = path.name
    sites: list[Site] = []
    counters: dict[str, int] = {}
    subclasses = _wx_subclasses(tree)
    # A factory returning a subclass is the same thing once removed: the
    # status bar builds one so the class can be made against the injected
    # wx module. Treat the variable it is assigned to as that class.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else getattr(func, "id", ""))
            if name.endswith("button_class") or name.endswith("_cell_button_class"):
                for target in _target_names(node):
                    subclasses[target] = "Button"

    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        qualname = scope.name
        for statement in ast.walk(scope):
            call: ast.Call | None = None
            targets: set[str] = set()
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = statement.value
                if isinstance(value, ast.Call):
                    call = value
                    targets = _target_names(statement)
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                call = statement.value
            if call is None:
                continue
            cls = _wx_class(call, subclasses)
            if cls not in HELPABLE:
                continue
            inline_kw = any(
                kw.arg in ("helpText", "toolTip") for kw in call.keywords
            )
            helped = inline_kw or _helped_in_scope(scope, targets)
            index = counters.get(f"{module}::{qualname}::{cls}", 0)
            counters[f"{module}::{qualname}::{cls}"] = index + 1
            suffix = f"#{index + 1}" if index else ""
            sites.append(
                Site(key=f"{module}::{qualname}::wx.{cls}{suffix}", helped=helped)
            )
    return sites


def scan() -> list[Site]:
    """Every helpable control in podHarvest's wx modules."""
    sites: list[Site] = []
    for name in SCAN_FILES:
        path = _ROOT / name
        if path.is_file():
            sites.extend(scan_file(path))
    return sorted(sites, key=lambda s: s.key)


def load_snapshot() -> dict[str, str]:
    if not _SNAPSHOT.is_file():
        return {}
    try:
        return dict(json.loads(_SNAPSHOT.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def build_snapshot(sites: list[Site], previous: dict[str, str]) -> dict[str, str]:
    """Statuses for every site: inline-helped sites are always ``helped``.

    A previously reviewed ``opt-out`` is kept, because that classification was
    somebody's decision. Everything else that is unhelped is ``missing``, which
    fails the build until a sentence is written or the opt-out is argued for.
    """
    snapshot: dict[str, str] = {}
    for site in sites:
        if site.helped:
            snapshot[site.key] = HELPED
        elif previous.get(site.key) == OPT_OUT:
            snapshot[site.key] = OPT_OUT
        else:
            snapshot[site.key] = MISSING
    return snapshot


def write_snapshot(snapshot: dict[str, str]) -> None:
    _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    sites = scan()
    snapshot = build_snapshot(sites, load_snapshot())
    counts: dict[str, int] = {}
    for status in snapshot.values():
        counts[status] = counts.get(status, 0) + 1

    if "--write" in args:
        write_snapshot(snapshot)
        print(f"Wrote {len(snapshot)} control sites to {_SNAPSHOT}")
        return 0

    print(", ".join(f"{status}: {count}" for status, count in sorted(counts.items())))
    missing = [key for key, status in snapshot.items() if status == MISSING]
    if missing:
        print("\nControls with no help of their own:", file=sys.stderr)
        for key in missing:
            print(f"  {key}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
