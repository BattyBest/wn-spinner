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
