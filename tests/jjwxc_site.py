"""Synthetic jjwxc pages (invented text, GBK-encoded). Real pages are never committed."""

from __future__ import annotations

# A short invented story; long enough that a few chapters reach a small character target.
SENTENCES = [
    "她推开窗户，看见远处的山被晨雾遮住了。",
    "“你今天怎么这么早？”他笑着问。",
    "城里的人都说，这位将军从来不会输掉任何一场战争。",
    "她慢慢地走过长长的走廊，心里想着昨天发生的事情。",
    "夜晚的风吹过院子，灯笼在树下轻轻摇晃。",
]


def story(paragraphs: int = 12) -> str:
    return "\n".join(SENTENCES[i % len(SENTENCES)] for i in range(paragraphs))


def chapter_page(text: str, title: str = "第一章 重逢") -> bytes:
    body = "<br>".join(["《测试小说》", "2026-10-01 作者:某某", title, *text.splitlines()])
    html = (
        "<html><body><div class='sidebar'>推荐</div>"
        f"<div id='paragraph_comment_content'>{body}</div></body></html>"
    )
    return html.encode("gb18030")


def ranking_page(books: list[tuple[str, str]]) -> bytes:
    """``books`` are (novel_id, title) pairs, best first."""
    rows = "".join(
        f"<tr><td>{n}</td><td>作者{n}</td>"
        f"<td><a href='onebook.php?novelid={nid}' title='{title}'>{title}</a></td>"
        "<td>原创-言情-近代现代-爱情</td><td>连载</td><td>1,200,000</td>"
        f"<td>{9_000_000 - n * 1000}</td><td>2026-10-01</td></tr>"
        for n, (nid, title) in enumerate(books, 1)
    )
    return f"<html><body><table>{rows}</table></body></html>".encode("gb18030")


def book_page(
    nid: int,
    title: str,
    free: int = 3,
    vip: int = 2,
    mature: bool = False,
    words: int = 900,
    updated: str = "2026-10-20 12:00:00",
) -> bytes:
    rows = []
    for n in range(1, free + 1):
        rows.append(
            f"<tr itemprop='chapter'><td>{n}</td>"
            f"<td><a itemprop='url' href='//www.jjwxc.net/onebook.php?novelid={nid}&chapterid={n}'>"
            f"第{n}章</a></td><td itemprop='wordCount'>{words}</td></tr>"
        )
    for n in range(free + 1, free + vip + 1):
        rows.append(
            f"<tr itemprop='chapter'><td>{n}</td>"
            "<td><a itemprop='url' rel='https://my.jjwxc.net/onebook_vip.php'>"
            f"第{n}章</a><font color='red'>[VIP]</font></td>"
            f"<td itemprop='wordCount'>{words}</td></tr>"
        )
    flag = "<div style='color:red'>本文作者建议18岁以上读者观看</div>" if mature else ""
    html = f"""<html><head><meta itemprop='dateModified' content='{updated}'></head><body>
<h1 itemprop='name'><span itemprop='articleSection'>{title}</span></h1>
<span itemprop='author'>某某</span>
<span itemprop='genre'>原创-言情-近代现代-爱情</span>
<span itemprop='updataStatus'>连载</span>
<span itemprop='wordCount'>{words * (free + vip)}</span>
<span itemprop='collectedCount'>4,321</span>
<span itemprop='scoreCount'>1,234,567</span>
{flag}
<div id='novelintro'>一个关于重逢的故事。<br>第二行。</div>
<div class='smallreadbody'><a href='bookbase.php?bq=1'>甜文</a>
<a href='bookbase.php?bq=2'>都市</a></div>
<ul class='rightul'><li>作品视角：女主</li></ul>
<table id='oneboolt'>{"".join(rows)}</table></body></html>"""
    return html.encode("gb18030")
