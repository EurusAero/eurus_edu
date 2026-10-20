from setuptools import find_packages, setup
from pathlib import Path

setup(
    name="EurusEdu",
    version="0.1.3",
    author="EURUS-AERO",
    author_email="info@eurus-aero.ru",
    description="Eurus-Edu",
    long_description=Path(__file__).with_name("README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    url="https://github.com/EurusAero/eurus_edu",
    python_requires=">=3.10",
    packages=find_packages(),
    install_requires=["opencv-python", "numpy", "websocket-client>=1.9.0,<2", "keyring>=25,<27"],
)
