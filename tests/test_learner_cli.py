import json

from typer.testing import CliRunner

from wn.cli import app
from wn.db import open_catalog

from .synthetic import build
from .test_learner_dictionary import document

runner = CliRunner()


def test_dict_load_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("WN_DATA_DIR", str(tmp_path))
    conn = open_catalog(tmp_path)
    conn.execute(
        "INSERT INTO lemma (language, lemma, pos, corpus_rank) VALUES ('ja', '魔法', '名詞', 5)"
    )
    conn.commit()
    conn.close()
    jmdict = tmp_path / "jmdict.json"
    jmdict.write_text(document(), encoding="utf-8")
    jlpt = tmp_path / "jlpt-n3.csv"
    jlpt.write_text("expression,reading\n魔法,まほう\n", encoding="utf-8")

    before = runner.invoke(app, ["dict", "status"])
    assert "jmdict  not loaded" in before.output

    result = runner.invoke(app, ["dict", "load", "--jmdict", str(jmdict), "--jlpt", str(jlpt)])
    assert result.exit_code == 0, result.output
    assert "4 entries" in result.output and "JLPT: 1 words" in result.output
    after = runner.invoke(app, ["dict", "status"])
    assert "4 entries from jmdict.json" in after.output
    assert "ranked words with a gloss: 1 of 1" in after.output


def test_dict_load_needs_a_file(tmp_path, monkeypatch):
    monkeypatch.setenv("WN_DATA_DIR", str(tmp_path))
    assert runner.invoke(app, ["dict", "load"]).exit_code == 1
    broken = tmp_path / "x.json"
    broken.write_text(json.dumps({"hello": 1}))
    result = runner.invoke(app, ["dict", "load", "--jmdict", str(broken)])
    assert result.exit_code == 1 and "jmdict-simplified" in result.output


def test_analyse_domains_reports_each_group(tmp_path, monkeypatch):
    monkeypatch.setenv("WN_DATA_DIR", str(tmp_path))
    conn = open_catalog(tmp_path)
    build(conn)
    conn.close()
    result = runner.invoke(app, ["analyse", "--domains"])
    assert result.exit_code == 0, result.output
    assert "domains:" in result.output and "fantasy" in result.output
    assert "school" in result.output and "too few novels, skipped" in result.output
