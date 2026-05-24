import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vercel_installs_python_requirements():
    config = json.loads((ROOT / "vercel.json").read_text())

    assert config["installCommand"] == "python3 -m pip install -r requirements.txt"


def test_captcha_runtime_dependency_is_listed_for_vercel():
    requirements = (ROOT / "requirements.txt").read_text().splitlines()

    assert "captcha==0.7.1" in requirements
