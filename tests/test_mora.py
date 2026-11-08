import pytest

from mimikara.mora import count_morae, count_morae_kana, count_morae_romaji


@pytest.mark.parametrize("kana,n", [
    ("カイゾク", 4), ("オー", 2), ("オウ", 2), ("ニ", 1), ("トーキョー", 4), ("キップ", 3),
    ("ガッコウ", 4), ("シンブン", 4), ("チョット", 3), ("ティー", 2), ("ファン", 2), ("", 0),
])
def test_kana(kana, n):
    assert count_morae_kana(kana) == n


@pytest.mark.parametrize("romaji,n", [
    ("kaizoku", 4), ("ō", 2), ("ou", 2), ("ni", 1), ("tōkyō", 4), ("kippu", 3), ("gakkō", 4),
    ("shinbun", 4), ("chotto", 3), ("naru", 2), ("!", 0), ("kan'i", 3), ("ore", 2),
])
def test_romaji(romaji, n):
    assert count_morae_romaji(romaji) == n


def test_prefers_kana():
    assert count_morae("ou", "オー") == 2
    assert count_morae("kaizoku") == 4
