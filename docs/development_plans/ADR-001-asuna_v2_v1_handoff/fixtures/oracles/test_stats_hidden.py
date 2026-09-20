"""Operator-side oracle; do not include in model prompt or writable workspace."""
import unittest
from stats import summarize_readings
class HiddenTests(unittest.TestCase):
    def test_empty(self): self.assertEqual(summarize_readings([]),(None,None,None))
    def test_only_none(self): self.assertEqual(summarize_readings([None,None]),(None,None,None))
    def test_no_mutation(self):
        x=[3,None,1]; before=x.copy();summarize_readings(x);self.assertEqual(x,before)
    def test_negative_float(self): self.assertEqual(summarize_readings([-2.5,0,2.5]),(-2.5,2.5,0))
    def test_one(self): self.assertEqual(summarize_readings([8]),(8,8,8))
if __name__=='__main__':unittest.main()
