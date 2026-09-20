import unittest
from stats import summarize_readings
class VisibleTests(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(summarize_readings([2,4,6]), (2,6,4))
    def test_missing(self):
        self.assertEqual(summarize_readings([None,2,4]), (2,4,3))
if __name__ == '__main__': unittest.main()
