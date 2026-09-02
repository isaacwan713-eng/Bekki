import unittest
from pathlib import Path

import history
import message_markdown
import result_cards


ROOT = Path(__file__).resolve().parents[1]


class MarkdownEvidenceV11040Tests(unittest.TestCase):
    def test_safe_markdown_keeps_structure_but_blocks_html_and_inline_images(self):
        value = (
            "## 标题\n\n- **重点**\n"
            "<script>alert(1)</script>\n"
            "![远程图](https://example.com/a.jpg)"
        )
        cleaned = message_markdown.sanitize_markdown(value)
        self.assertIn("## 标题", cleaned)
        self.assertIn("- **重点**", cleaned)
        self.assertIn("&lt;script&gt;", cleaned)
        self.assertNotIn("<script>", cleaned)
        self.assertIn("🖼 远程图", cleaned)
        self.assertNotIn("a.jpg", cleaned)

    def test_legacy_highlights_become_markdown_emphasis(self):
        value = message_markdown.apply_highlights(
            "结论是 250，字段是 ranking_mode。",
            [
                {"text": "250", "style": "important"},
                {"text": "ranking_mode", "style": "technical"},
            ],
        )
        self.assertIn("**250**", value)
        self.assertIn("`ranking_mode`", value)

    def test_recommendation_context_contains_candidate_specific_details(self):
        card = {
            "type": "product",
            "title": "候选一",
            "summary": "适合用户需求。",
            "url": "https://example.com/one",
            "metadata": {
                "price": "$99",
                "brand": "Example",
                "profile_fit": 92,
                "popularity_status": "HIGH",
            },
            "requirements": [
                {"requirement": "预算内", "status": "MATCH", "evidence": "$99"}
            ],
            "sections": [
                {"kind": "pros_cons", "pros": ["轻"], "cons": ["库存未知"]}
            ],
        }
        card = result_cards.clean_card(card)
        self.assertIsNotNone(card)
        context = message_markdown.card_context_markdown(card)
        self.assertIn("### 候选一", context)
        self.assertIn("**价格：** $99", context)
        self.assertIn("**需求匹配度：** 92", context)
        self.assertIn("**热度：** HIGH", context)
        self.assertIn("✅ 预算内", context)
        self.assertIn("⚠️ 库存未知", context)

    def test_evidence_block_binds_context_graph_and_link_in_order(self):
        card = {
            "type": "product",
            "title": "候选一",
            "summary": "说明一",
            "url": "https://example.com/one",
            "images": [
                {"url": "https://img.example.com/one.jpg", "label": "图片一"},
                {"url": "https://img.example.com/two.jpg", "label": "图片二"},
            ],
        }
        block = message_markdown.evidence_block(card)
        self.assertEqual(
            list(block),
            ["context_markdown", "graphs", "graph_placeholder", "link"],
        )
        self.assertEqual(len(block["graphs"]), 1)
        self.assertEqual(block["graphs"][0]["label"], "图片一")
        self.assertEqual(block["link"]["url"], card["url"])

    def test_social_post_keeps_its_gallery_inside_one_bound_block(self):
        card = {
            "type": "social_post",
            "title": "帖子",
            "summary": "正文",
            "url": "https://www.rednote.com/explore/abc",
            "images": [
                {"url": f"https://img.example.com/{index}.jpg", "label": f"图 {index}"}
                for index in range(1, 5)
            ],
        }
        block = message_markdown.evidence_block(card)
        self.assertEqual([item["label"] for item in block["graphs"]], [
            "图 1", "图 2", "图 3", "图 4"
        ])
        self.assertEqual(block["link"]["label"], "打开原帖  ↗")

    def test_plain_source_becomes_complete_evidence_card_and_keeps_order(self):
        sources = [
            {
                "title": "来源一",
                "description": "context one",
                "domain": "one.example",
                "url": "https://one.example/a",
                "image_url": "https://img.example/one.jpg",
                "content_type": "NEWS",
            },
            {
                "title": "来源二",
                "description": "context two",
                "domain": "two.example",
                "url": "https://two.example/b",
            },
        ]
        cards = result_cards.cards_from_sources(sources)
        self.assertEqual([card["title"] for card in cards], ["来源一", "来源二"])
        self.assertEqual(cards[0]["image"]["url"], "https://img.example/one.jpg")
        self.assertIsNone(cards[1]["image"])
        self.assertEqual(cards[1]["url"], "https://two.example/b")

    def test_source_card_dedupes_a_link_already_owned_by_recommendation(self):
        sources = [
            {"title": "重复", "url": "https://example.com/one"},
            {"title": "保留", "url": "https://example.com/two"},
        ]
        cards = result_cards.cards_from_sources(
            sources,
            exclude_urls={"https://example.com/one"},
        )
        self.assertEqual([card["title"] for card in cards], ["保留"])

    def test_history_upgrades_plain_messages_to_markdown_without_data_loss(self):
        cleaned = history._clean_message(
            {
                "role": "Bekki",
                "text": "旧消息仍然可读",
                "sources": [
                    {
                        "title": "来源",
                        "description": "说明",
                        "image_url": "https://img.example/a.jpg",
                        "domain": "example.com",
                        "url": "https://example.com/a",
                    }
                ],
            }
        )
        self.assertEqual(cleaned["text"], "旧消息仍然可读")
        self.assertEqual(cleaned["content_format"], "markdown")
        self.assertEqual(cleaned["sources"][0]["title"], "来源")
        self.assertEqual(cleaned["sources"][0]["image_url"], "https://img.example/a.jpg")

    def test_all_message_and_result_surfaces_use_markdown_and_bound_source_cards(self):
        ui_source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("document.setMarkdown", ui_source)
        self.assertIn("self.source_cards = ResultCardList()", ui_source)
        self.assertIn("result_cards.cards_from_sources", ui_source)
        self.assertNotIn("self.source_layout = QGridLayout()", ui_source)
        context_position = ui_source.index("layout.addWidget(context_label)")
        graph_position = ui_source.index("for label_text, image in zip(graph_labels, graph_widgets)")
        link_position = ui_source.index("footer.addWidget(open_button")
        self.assertLess(context_position, graph_position)
        self.assertLess(graph_position, link_position)

    def test_final_prompts_explicitly_allow_safe_markdown_inside_reply(self):
        full = (ROOT / "prompts" / "system.txt").read_text(encoding="utf-8")
        light = (ROOT / "prompts" / "system_light.txt").read_text(encoding="utf-8")
        self.assertIn("reply string is rendered as safe Markdown", full)
        self.assertIn("reply string itself is displayed as safe Markdown", light)


if __name__ == "__main__":
    unittest.main()
