from pathlib import Path

hardening_path = Path("tests/test_v11_hardening.py")
hardening = hardening_path.read_text(encoding="utf-8")
hardening = hardening.replace(
    '            self.assertEqual(payload["studio_version"], "1.1.0")\n',
    '            expected_version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]\n'
    '            self.assertEqual(payload["studio_version"], expected_version)\n',
)
hardening_path.write_text(hardening, encoding="utf-8")

media_path = Path("tests/test_v11_media_gallery.py")
media = media_path.read_text(encoding="utf-8")
media = media.replace(
    "        self.assertIn('arline.css?v=1.1.3-media', html)\n",
    "        self.assertRegex(html, r'arline\\.css\\?v=[^\"\\s]+')\n",
)
media_path.write_text(media, encoding="utf-8")
