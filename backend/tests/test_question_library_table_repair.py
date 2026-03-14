import unittest

from backend.question_library.table_repair import repair_obvious_broken_tables


class TestQuestionLibraryTableRepair(unittest.TestCase):
    def test_repairs_obvious_generic_frequency_table(self) -> None:
        text = """甲乙二人的最近60次出拳如下表．
出拳情况
石头
剪刀
布

甲
30次
20次
10次

乙
15次
30次
15次

用频率估计概率，假设两人每次出拳相互独立．"""

        repaired = repair_obvious_broken_tables(text)

        self.assertIn("\\begin{array}", repaired)
        self.assertIn("出拳情况 & 石头 & 剪刀 & 布", repaired)
        self.assertIn("甲 & 30次 & 20次 & 10次", repaired)
        self.assertIn("乙 & 15次 & 30次 & 15次", repaired)
        self.assertIn("用频率估计概率", repaired)
