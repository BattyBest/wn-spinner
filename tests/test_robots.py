import pytest

from wn.collector.robots import RobotsRules

# Qidian's robots.txt as of 2026-11-03 (public file).
QIDIAN = """
User-agent: ClaudeBot
Disallow: /

User-agent: GPTbot
Disallow: /

User-Agent: Googlebot
Allow: /

User-Agent: *
Allow: /
Disallow: /*.css
Disallow: /*.js
Disallow: /so/*
Disallow: /webcommon/*
Disallow: /ajax/*
"""

SYOSETU = """
User-agent: *
Crawl-delay: 1

User-agent: BingBot
Crawl-delay: 3

User-agent: meta-externalagent/1.1
Disallow: /
"""


def test_wildcards_in_disallow_rules():
    rules = RobotsRules.parse(QIDIAN)
    assert rules.allowed("wn-spinner", "/book/1234")
    assert not rules.allowed("wn-spinner", "/so/search?kw=x")
    assert not rules.allowed("wn-spinner", "/ajax/chapter")
    assert not rules.allowed("wn-spinner", "/static/site.css")
    assert not rules.allowed("wn-spinner", "/webcommon/a/b")


def test_named_agent_group_beats_star():
    rules = RobotsRules.parse(QIDIAN)
    assert not rules.allowed("ClaudeBot", "/book/1234")
    assert rules.allowed("Googlebot", "/so/anything")


def test_crawl_delay_for_us_comes_from_the_star_group():
    rules = RobotsRules.parse(SYOSETU)
    assert rules.crawl_delay("wn-spinner") == 1.0
    assert rules.crawl_delay("BingBot") == 3.0
    assert RobotsRules.parse(QIDIAN).crawl_delay("wn-spinner") is None


def test_longest_match_wins_and_allow_wins_ties():
    rules = RobotsRules.parse(
        "User-agent: *\nDisallow: /a/\nAllow: /a/b\nDisallow: /same\nAllow: /same"
    )
    assert not rules.allowed("x", "/a/c")
    assert rules.allowed("x", "/a/b/c")
    assert rules.allowed("x", "/same")


def test_end_anchor_and_empty_disallow():
    rules = RobotsRules.parse("User-agent: *\nDisallow: /*.pdf$\n\nUser-agent: open\nDisallow:")
    assert not rules.allowed("x", "/files/a.pdf")
    assert rules.allowed("x", "/files/a.pdf?download=1")
    assert rules.allowed("open", "/anything")


def test_comments_and_grouped_agents():
    text = "# hello\nUser-agent: a\nUser-agent: b  # two agents\nDisallow: /x # no\n"
    rules = RobotsRules.parse(text)
    assert not rules.allowed("a", "/x")
    assert not rules.allowed("b", "/x")
    assert rules.allowed("c", "/x")


def test_no_matching_group_allows_everything():
    assert RobotsRules.parse("User-agent: other\nDisallow: /").allowed("wn-spinner", "/x")


def test_status_rules():
    assert not RobotsRules.from_status(403).allowed("x", "/")
    assert RobotsRules.from_status(404).allowed("x", "/")
    with pytest.raises(ValueError):
        RobotsRules.from_status(503)
