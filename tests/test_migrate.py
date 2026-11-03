import sqlite3

import pytest

from wn.db import open_catalog, open_profile
from wn.db.migrate import current_version, migrate


def test_fresh_databases_are_created_and_seeded(tmp_path):
    catalog, profile = open_catalog(tmp_path), open_profile(tmp_path)
    assert current_version(catalog) == 4
    assert current_version(profile) == 2
    names = [r[0] for r in catalog.execute("SELECT name FROM source ORDER BY name")]
    assert names == ["jjwxc", "syosetu"]
    assert profile.execute("SELECT COUNT(*) FROM setting").fetchone()[0] == 0


def test_running_twice_changes_nothing(tmp_path):
    open_catalog(tmp_path).close()
    again = open_catalog(tmp_path)
    assert again.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 2
    open_profile(tmp_path).close()
    open_profile(tmp_path).close()
    assert not (tmp_path / "backups").exists()  # no pending migration, no backup


def _folder(tmp_path, **files):
    folder = tmp_path / "migrations"
    folder.mkdir()
    for name, sql in files.items():
        (folder / f"{name}.sql").write_text(sql)
    return folder


def test_failed_migration_leaves_no_trace(tmp_path):
    folder = _folder(
        tmp_path,
        **{
            "001_a": "CREATE TABLE a (x);",
            "002_b": "CREATE TABLE b (x); INSERT INTO nope VALUES (1);",
        },
    )
    conn = sqlite3.connect(tmp_path / "t.db")
    with pytest.raises(sqlite3.Error):
        migrate(conn, folder)
    assert current_version(conn) == 1
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert tables == ["a"]


def test_upgrade_backs_up_existing_data_first(tmp_path):
    folder = _folder(tmp_path, **{"001_a": "CREATE TABLE a (x); INSERT INTO a VALUES (7);"})
    conn = sqlite3.connect(tmp_path / "t.db")
    backups = tmp_path / "backups"
    migrate(conn, folder, backup_dir=backups)
    assert not backups.exists()  # nothing to protect on a fresh database

    (folder / "002_b.sql").write_text("CREATE TABLE b (y);")
    assert migrate(conn, folder, backup_dir=backups) == 2
    (backup,) = backups.glob("profile-v1-*.db")
    saved = sqlite3.connect(backup)
    assert saved.execute("SELECT x FROM a").fetchone()[0] == 7
    assert current_version(saved) == 1


def test_only_the_newest_backups_are_kept(tmp_path):
    files = {"001_a": "CREATE TABLE a (x);"}
    for n in range(2, 7):
        files[f"{n:03d}_t{n}"] = f"CREATE TABLE t{n} (x);"
    folder = _folder(tmp_path, **{"001_a": files.pop("001_a")})
    conn = sqlite3.connect(tmp_path / "t.db")
    migrate(conn, folder, backup_dir=tmp_path / "backups", backup_keep=2)
    for name, sql in files.items():
        (folder / f"{name}.sql").write_text(sql)
        migrate(conn, folder, backup_dir=tmp_path / "backups", backup_keep=2)
    assert len(list((tmp_path / "backups").glob("*.db"))) == 2
