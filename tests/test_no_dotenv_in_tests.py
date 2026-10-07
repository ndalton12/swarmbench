import os

import inspect_ai._eval.context


def test_dotenv_is_never_loaded_during_tests(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=should-never-load\n")
    monkeypatch.chdir(tmp_path)
    inspect_ai._eval.context.init_dotenv()
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert os.environ.get("SWARMBENCH_NO_DOTENV") == "1"
