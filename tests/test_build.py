import importlib.util
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from build import build

class BuildTests(unittest.TestCase):
    def test_public_bundle_excludes_backend_and_credentials(self):
        build()
        output=ROOT/'dist'
        self.assertTrue((output/'index.html').exists())
        self.assertTrue((output/'harbours.json').exists())
        self.assertFalse((output/'.env').exists())
        self.assertFalse((output/'collector').exists())
        page=(output/'index.html').read_text()
        self.assertNotIn('{{',page)
        self.assertIn('Collector not connected',page)
        self.assertIn('canonical',page)
        self.assertIn('https://coolcode.ca/harbournow/',page)
