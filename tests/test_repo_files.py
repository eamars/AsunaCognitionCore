"""A source tree's files as git lists them, with or without git (asuna.repo_files): a publication's candidate is a
plain copy, and the repository guards must run there too."""
from asuna import repo_files
from asuna.config import ROOT


def test_a_checkout_asks_git():
    assert repo_files.checkout(ROOT)
    listed = repo_files.files(ROOT)
    assert 'AGENTS.md' in listed and not any(name.startswith('.runtime/') for name in listed)


def test_a_plain_copy_is_read_with_its_gitignore(tmp_path):
    (tmp_path / '.gitignore').write_text('ignored/\n*.log\n', encoding='utf-8')
    for name in ('a.txt', 'sub/c.py', 'ignored/x.txt', 'b.log', 'sub/deep/d.py'):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text('x', encoding='utf-8')
    assert not repo_files.checkout(tmp_path)
    assert repo_files.files(tmp_path) == ['.gitignore', 'a.txt', 'sub/c.py', 'sub/deep/d.py']
    assert repo_files.files(tmp_path, 'sub') == ['sub/c.py', 'sub/deep/d.py']
    assert repo_files.files(tmp_path, 'sub/deep/*.py') == ['sub/deep/d.py']
    assert repo_files.ignored(tmp_path, 'ignored/probe.md') and not repo_files.ignored(tmp_path, 'a.txt')
