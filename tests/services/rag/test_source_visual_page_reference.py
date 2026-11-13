"""A page reference must name a page — not a question.

"第1题" names the first question of a paper; reading it as "page 1" sends the
retrieval to the wrong place and hides the document's own text.
"""

from __future__ import annotations

import pytest

from deeptutor.services.rag.source_visuals import figure_labels, page_reference


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("第5页", 5),
        ("第 5 頁", 5),
        ("page 7", 7),
        ("Page 7", 7),
        ("p. 7", 7),
        ("看第3页的图", 3),
        ("没有页码", None),
    ],
)
def test_an_explicit_page_marker_names_a_page(text, expected) -> None:
    assert page_reference(text) is expected


@pytest.mark.parametrize(
    "text",
    [
        "第1题考的是什么",
        "2025年浙江6月高考地理真题 第1题 题干 选择题",
        "洛川塬考察区 第6题 设问",
        "第26题图1",
    ],
)
def test_a_question_number_is_not_a_page(text) -> None:
    assert page_reference(text) is None


def test_a_figure_label_is_still_recognized() -> None:
    assert figure_labels("第26题图1") == ["1"]
    assert figure_labels("Figure 3.2") == ["3.2"]
