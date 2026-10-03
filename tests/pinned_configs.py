"""C-17-8 (S-12): the demo proxy configurations are pinned to the demo model. The C-17
offline fixtures keep the model they were written with (TEST-T1-v2, TEST-T2-v2, the DM-37 copy of A-1-v4 and the
C-17-4 baseline requests), so tests run them through a copy of the same configuration pinned to that model.
The copy keeps the file name (the proxy records it) and differs only in the pin (tests/test_c17_8_part1.py)."""
import atexit
from pathlib import Path
import shutil
import tempfile

import yaml

_DIRECTORY = Path(tempfile.mkdtemp(prefix="pinned-configs-"))
atexit.register(shutil.rmtree, _DIRECTORY, True)


def for_model(config, model):
    """The configuration a fixture run goes through: a pinned configuration re-pinned to the fixture's model, an
    unpinned one (Groq era, the protected v0.2 configuration) as it is."""
    data = yaml.safe_load(Path(config).read_text(encoding="utf-8")) or {}
    return pinned_copy(config, model) if {"run_conditions", "pinned_model"} & set(data) else Path(config)


def pinned_copy(config, model):
    """config with run_conditions / pinned_model replaced by pinned_model: model, in a temporary folder."""
    config = Path(config)
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    data.pop("run_conditions", None)
    data["pinned_model"] = model
    folder = _DIRECTORY / (model.replace("/", "_") + "-" + str(abs(hash(str(config.resolve())))))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / config.name
    target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return target


def demo_model():
    """The model the real demo proxy configurations are pinned to (demo-conditions.yaml); direct proxy API tests send it."""
    from experiment_config import load_config, pinned_model
    return pinned_model(load_config(Path(__file__).resolve().parents[1] / "guardrail-deadlock-v0.3-kmu.yaml"))["name"]
