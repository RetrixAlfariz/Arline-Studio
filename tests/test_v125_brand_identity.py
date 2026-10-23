from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/interface/web/static"


class V125BrandIdentityTests(unittest.TestCase):
    def test_official_palette_is_the_ui_source_of_truth(self):
        css = (STATIC / "brand-v125.css").read_text(encoding="utf-8")
        for token in (
            "--brand-teal:#2F9B81",
            "--brand-charcoal:#1E2120",
            "--brand-white:#FFFFFF",
            "--brand-light:#F3F6F4",
            "--brand-dark-surface:#292D2B",
            "--brand-flow:#45B99B",
            "--brand-gold:#C7A76A",
            "--brand-sage:#8EA39B",
        ):
            self.assertIn(token, css)
        self.assertIn("color:var(--brand-charcoal)!important", css)
        self.assertIn("flex-direction:column", css)

    def test_brand_marks_are_single_color_vector_assets(self):
        brand = STATIC / "assets/brand"
        expected = {
            "arline-primary.svg": "#2F9B81",
            "arline-dark.svg": "#1E2120",
            "arline-reverse.svg": "#FFFFFF",
        }
        for name, color in expected.items():
            svg = (brand / name).read_text(encoding="utf-8")
            self.assertIn(color, svg)
            self.assertNotIn("linearGradient", svg)
            self.assertNotIn("radialGradient", svg)
            self.assertNotIn("stroke=", svg)
            self.assertEqual(svg.count("<path"), 4)

    def test_brand_shell_is_loaded_before_the_application_runtime(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('/static/brand-v125.css?v=1.2.5-brand', html)
        self.assertIn('/static/assets/brand/arline-primary.svg', html)
        self.assertIn('content="#1E2120"', html)
        self.assertIn("Studio v1.2.5 α", html)
        self.assertLess(html.index("brand-v125.css"), html.index("static/js/stream.js"))

    def test_logo_geometry_is_used_as_a_mask_not_decorated(self):
        css = (STATIC / "brand-v125.css").read_text(encoding="utf-8")
        self.assertIn(".brand-mark::before,.hero-orb::before", css)
        self.assertIn("mask:url('/static/assets/brand/arline-primary.svg')", css)
        self.assertIn("background:var(--brand-teal)", css)
        self.assertIn("background:none!important", css)
        self.assertIn("box-shadow:none!important", css)


if __name__ == "__main__":
    unittest.main()
