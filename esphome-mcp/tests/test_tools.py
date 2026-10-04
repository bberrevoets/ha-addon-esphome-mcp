"""Tests for file confinement, pull arguments and lenient YAML parsing."""

import os

import pytest

from server import tools


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A fake /config with an esphome/ directory and an HA config next to it."""
    esphome = tmp_path / "esphome"
    (esphome / "archive").mkdir(parents=True)
    (esphome / "kitchen.yaml").write_text("esphome:\n  name: kitchen\n")
    (esphome / "archive" / "old.yaml").write_text("esphome:\n  name: old\n")
    (esphome / "secrets.yaml").write_text("wifi_password: hunter2\n")
    (tmp_path / "configuration.yaml").write_text("homeassistant:\n")
    monkeypatch.setattr(tools, "ESPHOME_DIR", str(esphome))
    monkeypatch.setattr(tools, "_LOCAL_VERSION", "test")
    return tmp_path


# ---------------------------------------------------------------------------
# push_files
# ---------------------------------------------------------------------------
def test_push_inside_directory(config_dir):
    out = tools.push_files({"new.yaml": "a: 1\n", "archive/gone.yaml": "b: 2\n"})
    assert "new.yaml: OK" in out
    assert "archive/gone.yaml: OK" in out
    assert (config_dir / "esphome" / "new.yaml").read_text() == "a: 1\n"
    assert (config_dir / "esphome" / "archive" / "gone.yaml").exists()


@pytest.mark.parametrize(
    "name",
    ["../configuration.yaml", "archive/../../configuration.yaml"],
)
def test_push_rejects_parent_traversal(config_dir, name):
    out = tools.push_files({name: "pwned: true\n"})
    assert "REJECTED (outside the ESPHome directory)" in out
    assert (config_dir / "configuration.yaml").read_text() == "homeassistant:\n"


def test_push_rejects_absolute_path(config_dir):
    target = str(config_dir / "configuration.yaml")
    out = tools.push_files({target: "pwned: true\n"})
    assert "REJECTED (outside the ESPHome directory)" in out
    assert (config_dir / "configuration.yaml").read_text() == "homeassistant:\n"


def test_push_rejects_symlink_escape(config_dir):
    outside = config_dir / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, config_dir / "esphome" / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    out = tools.push_files({"link/x.yaml": "a: 1\n"})
    assert "REJECTED (outside the ESPHome directory)" in out
    assert not (outside / "x.yaml").exists()


def test_push_rejects_secrets_and_non_yaml(config_dir):
    out = tools.push_files({"secrets.yaml": "x: 1\n", "notes.txt": "hi"})
    assert "secrets.yaml: REJECTED" in out
    assert "notes.txt: REJECTED (only .yaml files allowed)" in out


# ---------------------------------------------------------------------------
# pull_files / pull_fonts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pull", [tools.pull_files, tools.pull_fonts])
def test_pull_requires_explicit_all(config_dir, pull):
    with pytest.raises(tools.ToolInputError, match="all=true"):
        pull()
    with pytest.raises(tools.ToolInputError, match="all=true"):
        pull([])
    with pytest.raises(tools.ToolInputError, match="not both"):
        pull(["kitchen.yaml"], all_files=True)


def test_pull_all(config_dir):
    result = tools.pull_files(all_files=True)
    assert set(result) == {"kitchen.yaml", "archive/old.yaml"}


def test_pull_named_files(config_dir):
    result = tools.pull_files(["kitchen", "old.yaml", "missing"])
    assert result["kitchen.yaml"].startswith("esphome:")
    assert result["archive/old.yaml"].startswith("esphome:")
    assert result["missing.yaml"] == "ERROR: not found"


@pytest.mark.parametrize("name", ["../configuration", "../configuration.yaml"])
def test_pull_rejects_traversal(config_dir, name):
    result = tools.pull_files([name])
    assert list(result.values()) == ["REJECTED: outside the ESPHome directory"]


def test_pull_rejects_absolute_path(config_dir):
    result = tools.pull_files([str(config_dir / "configuration.yaml")])
    assert list(result.values()) == ["REJECTED: outside the ESPHome directory"]


def test_pull_rejects_secrets(config_dir):
    assert tools.pull_files(["secrets"]) == {
        "secrets.yaml": "REJECTED: secrets files cannot be pulled"
    }


# ---------------------------------------------------------------------------
# Device tools
# ---------------------------------------------------------------------------
def test_device_path_is_confined(config_dir):
    assert tools._device_yaml_path("kitchen") == os.path.join(
        tools.ESPHOME_DIR, "kitchen.yaml"
    )
    with pytest.raises(tools.DeviceLookupError, match="outside"):
        tools._device_yaml_path("../configuration.yaml")


# ---------------------------------------------------------------------------
# Lenient YAML metadata
# ---------------------------------------------------------------------------
LVGL_MERGE = """\
substitutions:
  devname: panel
esphome:
  name: ${devname}
  friendly_name: Hall Panel
lvgl:
  pages:
    - id: main_page
      <<: !include some-package/widgets/swipe_navigation.yaml
      widgets: []
    - id: second
      <<: [!include a.yaml, {layout: 2x2}]
"""


def test_merge_key_with_include_is_parsed(config_dir):
    path = config_dir / "esphome" / "panel.yaml"
    path.write_text(LVGL_MERGE)
    info = tools._parse_device_info(str(path))
    assert "error" not in info
    assert info["name"] == "panel"
    assert info["friendly_name"] == "Hall Panel"


def test_regular_merge_keys_still_work():
    import yaml

    data = yaml.load(
        "base: &b {a: 1}\nx:\n  <<: *b\n  c: 2\n", Loader=tools._LenientLoader
    )
    assert data["x"] == {"a": 1, "c": 2}


def test_unparseable_metadata_is_not_reported_as_error_device(config_dir):
    (config_dir / "esphome" / "broken.yaml").write_text("esphome: [unclosed\n")
    out = tools.list_devices()
    line = next(line for line in out.splitlines() if "broken.yaml" in line)
    assert "could not parse metadata" in line
    assert "- error " not in line
    assert "\n" not in line
