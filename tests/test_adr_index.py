"""The ADR index keeps up with the ADR folders: every folder has a README and one row in the index, and no number is
used twice, by a folder or by a row (an archived ADR keeps its row after its folder is gone)."""
import collections
import pathlib
import re

PLANS = pathlib.Path(__file__).resolve().parents[1] / 'docs' / 'development_plans'


def test_every_adr_folder_has_a_readme_and_one_index_row_and_no_number_is_taken_twice():
    folders = sorted(p for p in PLANS.iterdir() if p.is_dir())
    assert folders
    number = lambda folder: re.fullmatch(r'ADR-(\d{3})-[a-z0-9-]+', folder.name).group(1)
    assert [f.name for f in folders if not (f / 'README.md').is_file()] == []
    taken = collections.Counter(number(f) for f in folders)
    assert [n for n, count in taken.items() if count > 1] == []
    rows = collections.Counter(re.findall(r'^\| (\d{3}) \|', (PLANS / 'README.md').read_text(encoding='utf-8'), re.M))
    assert [n for n, count in rows.items() if count > 1] == []
    assert [f.name for f in folders if number(f) not in rows] == []
