from __future__ import annotations

import unittest
from unittest.mock import patch

from flowstudy.config import LULU_PET_IMAGE
from flowstudy.pet import render_lulu_pet


class LuluPetTests(unittest.TestCase):
    def test_pet_asset_has_real_transparency(self) -> None:
        png = LULU_PET_IMAGE.read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(png[25], 6)  # PNG color type 6 is RGBA.

    @patch("flowstudy.pet.st.iframe")
    def test_pet_mount_contains_required_interactions(self, iframe_mock) -> None:
        render_lulu_pet()

        html = iframe_mock.call_args.args[0]
        self.assertIn("flowstudy-lulu-pet-position-v1", html)
        self.assertIn("pointerdown", html)
        self.assertIn("localStorage", html)
        self.assertIn("previous.remove()", html)
        self.assertIn("__flowstudyLuluCleanup", html)
        self.assertIn("粉粉加油！", html)
        self.assertIn("/app/static/lulu/images/pet-transparent.png", html)
        iframe_mock.assert_called_once_with(html, width=1, height=1)

    @patch("flowstudy.pet.st.iframe")
    def test_each_rerun_gets_a_fresh_mount_script(self, iframe_mock) -> None:
        render_lulu_pet()
        render_lulu_pet()

        first_html = iframe_mock.call_args_list[0].args[0]
        second_html = iframe_mock.call_args_list[1].args[0]
        self.assertNotEqual(first_html, second_html)

    @patch("flowstudy.pet.components.html")
    @patch("flowstudy.pet.st.iframe", None)
    def test_pet_supports_older_streamlit(self, html_mock) -> None:
        render_lulu_pet()

        html = html_mock.call_args.args[0]
        html_mock.assert_called_once_with(html, height=1, scrolling=False)


if __name__ == "__main__":
    unittest.main()
