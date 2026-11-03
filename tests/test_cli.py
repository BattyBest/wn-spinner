import respx
from typer.testing import CliRunner

from wn.cli import app

runner = CliRunner()


def test_robots_command_prints_the_delay_in_force(tmp_path, monkeypatch):
    monkeypatch.setenv("WN_DATA_DIR", str(tmp_path))
    with respx.mock:
        respx.get("https://ncode.syosetu.com/robots.txt").respond(
            200, text="User-agent: *\nCrawl-delay: 1\n"
        )
        result = runner.invoke(app, ["robots", "ncode.syosetu.com"])
    assert result.exit_code == 0, result.output
    assert "their delay:    1 s" in result.output
    assert "delay in force: 1 s" in result.output
    assert "/: allowed" in result.output


def test_fetch_then_cache_then_purge(tmp_path, monkeypatch):
    monkeypatch.setenv("WN_DATA_DIR", str(tmp_path))
    url = "https://ncode.syosetu.com/n0000aa/1/"
    with respx.mock:
        respx.get("https://ncode.syosetu.com/robots.txt").respond(404)
        route = respx.get(url).respond(200, text="本文")
        first = runner.invoke(app, ["fetch", url])
        second = runner.invoke(app, ["fetch", url, "--show"])
    assert "network" in first.output and "cache" in second.output and "本文" in second.output
    assert route.call_count == 1

    stats = runner.invoke(app, ["cache", "stats"])
    assert "ncode.syosetu.com" in stats.output
    assert "removed 1" in runner.invoke(app, ["cache", "purge", "--kind", "page"]).output


def test_dry_run_sends_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("WN_DATA_DIR", str(tmp_path))
    with respx.mock:
        result = runner.invoke(app, ["fetch", "https://ncode.syosetu.com/n1/1/", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "would be fetched first" in result.output


def test_disallowed_fetch_exits_with_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("WN_DATA_DIR", str(tmp_path))
    with respx.mock:
        respx.get("https://x.test/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
        result = runner.invoke(app, ["fetch", "https://x.test/a"])
    assert result.exit_code == 1


def _fake_syosetu(router):
    from pathlib import Path

    fx = Path(__file__).parent / "fixtures" / "syosetu"
    router.get("https://api.syosetu.com/robots.txt").respond(404)
    router.get("https://ncode.syosetu.com/robots.txt").respond(404)
    router.get(url__startswith="https://api.syosetu.com/rank/rankget/").respond(
        200, text=(fx / "ranking_daily.json").read_text(encoding="utf-8")
    )
    router.get(url__startswith="https://api.syosetu.com/novelapi/api/").respond(
        200, text=(fx / "novels.json").read_text(encoding="utf-8")
    )
    router.get(url__regex=r"https://ncode\.syosetu\.com/n\d+\w+/.*").respond(
        200, text=(fx / "chapter_new.html").read_text(encoding="utf-8")
    )


def test_syosetu_run_collects_then_a_second_run_has_nothing_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("WN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("wn.collector.http.DEFAULT_DELAY", 0.0)
    monkeypatch.setattr("wn.syosetu.pipeline.DEFAULT_DELAY", 0.0)
    with respx.mock(assert_all_called=False) as router:
        _fake_syosetu(router)
        first = runner.invoke(app, ["syosetu", "run", "--limit", "10", "--target", "50", "--yes"])
        assert first.exit_code == 0, first.output
        assert "novels to read:  4" in first.output and "4 scored" in first.output
        again = runner.invoke(app, ["syosetu", "sample", "--target", "50", "--yes"])
        assert again.exit_code == 0 and "nothing to read" in again.output

    stats = runner.invoke(app, ["cache", "stats"])
    assert "chapter" not in stats.output  # raw chapter text was deleted after analysis
    done = runner.invoke(app, ["analyse"])
    assert done.exit_code == 0 and "statistics for 4 novels" in done.output


def test_syosetu_sample_dry_run_sends_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("WN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("wn.collector.http.DEFAULT_DELAY", 0.0)
    with respx.mock(assert_all_called=False) as router:
        _fake_syosetu(router)
        runner.invoke(app, ["syosetu", "discover", "--limit", "10"])
        calls_before = len(router.calls)
        result = runner.invoke(app, ["syosetu", "sample", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "novels to read:  4" in result.output
        assert len(router.calls) == calls_before


def test_analyse_refits_a_saved_model(tmp_path, monkeypatch):
    from wn.db import open_catalog, open_profile

    from .synthetic import build

    monkeypatch.setenv("WN_DATA_DIR", str(tmp_path))
    catalog, profile = open_catalog(tmp_path), open_profile(tmp_path)
    ids = build(catalog)
    lemma = catalog.execute(
        "SELECT lemma, pos FROM lemma WHERE id = ?", (ids["lemmas"][3],)
    ).fetchone()
    with profile:
        profile.execute(
            "INSERT INTO answer (language, kind, lemma, pos, known, weight, at)"
            " VALUES ('ja', 'word', ?, ?, 1, 1.0, 1.0)",
            (lemma[0], lemma[1]),
        )
        profile.execute(
            "INSERT INTO model (language, version, params, guess_rate, answers, fitted_at)"
            " VALUES ('ja', 2, '{\"theta\": [5.0, 1.0], \"domains\": {}}', 0.1, 0, 1.0)"
        )
    result = runner.invoke(app, ["analyse", "--lang", "ja"])
    assert result.exit_code == 0, result.output
    assert "refitted your model from 1 answers" in result.output
    assert open_profile(tmp_path).execute("SELECT answers FROM model").fetchone()[0] == 1
