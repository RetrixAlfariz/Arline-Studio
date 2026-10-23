from __future__ import annotations

import unittest

from src.cli.shutdown import _looks_like_arline, _parse_windows_netstat


class ShutdownCliTests(unittest.TestCase):
    def test_netstat_parser_matches_listening_port_only(self):
        output = """
          TCP    127.0.0.1:7860    0.0.0.0:0    LISTENING    1234
          TCP    127.0.0.1:78601   0.0.0.0:0    LISTENING    9999
          TCP    127.0.0.1:7860    0.0.0.0:0    ESTABLISHED  8888
        """
        self.assertEqual(_parse_windows_netstat(output, 7860), {1234})

    def test_process_guard(self):
        self.assertTrue(_looks_like_arline("python app.py"))
        self.assertTrue(_looks_like_arline("python -m uvicorn src.interface.web.app:app"))
        self.assertFalse(_looks_like_arline("node unrelated-server.js"))


if __name__ == "__main__":
    unittest.main()
