"""R-semantics spot checks the port depends on (values confirmed against R 4.4.3)."""
import unittest

from gates import rsem as R
from gates.rsem import RError, RVec


class RSem(unittest.TestCase):
    def test_partial_dollar(self):
        self.assertEqual(R.dollar({"status_code": 1}, "status"), 1)
        self.assertIsNone(R.dollar({"status_a": 1, "status_b": 2}, "status"))
        self.assertIsNone(R.elt({"status_code": 1}, "status"))
        with self.assertRaises(RError):
            R.dollar("x", "a")

    def test_identical_is_type_strict(self):
        self.assertFalse(R.identical(0, 0.0))
        self.assertTrue(R.identical("a", "a"))

    def test_as_numeric_strings(self):
        self.assertEqual(R.str2num(" 1 "), 1.0)
        self.assertEqual(R.str2num("0x1A"), 26.0)
        self.assertEqual(R.str2num("Inf"), float("inf"))
        self.assertIsNone(R.str2num("abc"))

    def test_num2str(self):
        self.assertEqual(R.num2str(1e5), "1e+05")
        self.assertEqual(R.num2str(0.1 + 0.2), "0.3")
        self.assertEqual(R.num2str(15.0), "15")
        # as printed by R 4.4.3 as.character()
        for x, want in [(1 / 3, "0.333333333333333"), (123456789012345678.0, "123456789012345680"), (1e-20, "1e-20"),
                        (100000.5, "100000.5"), (1e15, "1e+15"), (0.1 + 0.7, "0.8")]:
            self.assertEqual(R.num2str(x), want)

    def test_and_scalar_rules(self):
        self.assertIsNone(R.AND(True, RVec("lgl", [])))
        with self.assertRaises(RError):
            R.AND(RVec("lgl", [True, True]), True)

    def test_json(self):
        self.assertIsInstance(R.json_loads("3000000000"), float)
        self.assertEqual(R.json_loads('{"a":1,"a":2}')["a"], 1)
        with self.assertRaises(Exception):
            R.json_loads("NaN")


if __name__ == "__main__":
    unittest.main()
