"""The global secrets store: modes, symlinks, line breaks, names only in listings."""
import os
import stat

import pytest

from phoenix9 import keys, paths

SENTINEL = "sk-SENTINEL-123"


def test_secret_file_mode_0600_and_dir_0700():
    keys.write_secret_file("service-x.env", {"X_KEY": SENTINEL})
    assert stat.S_IMODE((paths.secrets() / "service-x.env").stat().st_mode) == 0o600
    assert stat.S_IMODE(paths.secrets().stat().st_mode) == 0o700
    assert keys.read_secret_file("service-x.env") == {"X_KEY": SENTINEL}
    assert keys.secret_files()[0]["names"] == ["X_KEY"] and SENTINEL not in str(keys.secret_files())


def test_wider_dir_mode_is_fixed():
    paths.secrets().mkdir(parents=True)
    paths.secrets().chmod(0o755)
    keys.secrets_dir()
    assert stat.S_IMODE(paths.secrets().stat().st_mode) == 0o700


def test_symlink_target_refused(tmp_path):
    keys.secrets_dir()
    (tmp_path / "elsewhere").write_text("A=1\n")
    os.symlink(tmp_path / "elsewhere", paths.secrets() / "service-x.env")
    with pytest.raises(keys.KeyError_, match="symlink"):
        keys.write_secret_file("service-x.env", {"X_KEY": SENTINEL})
    with pytest.raises(keys.KeyError_, match="symlink"):
        keys.read_secret_file("service-x.env")
    assert (tmp_path / "elsewhere").read_text() == "A=1\n"


def test_group_readable_file_refused_on_read():
    keys.write_secret_file("service-x.env", {"X_KEY": SENTINEL})
    (paths.secrets() / "service-x.env").chmod(0o640)
    with pytest.raises(keys.KeyError_, match="other users"):
        keys.read_secret_file("service-x.env")


def test_values_with_newline_refused():
    with pytest.raises(keys.KeyError_, match="line break"):
        keys.write_secret_file("service-x.env", {"X_KEY": "a\nB=c"})
    assert not (paths.secrets() / "service-x.env").exists()


def test_bad_file_name_refused():
    with pytest.raises(keys.KeyError_):
        keys.write_secret_file("../x.env", {"X_KEY": SENTINEL})
