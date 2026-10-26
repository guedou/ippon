# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

from setuptools import setup

setup(
    name="ippon",
    description="A sports scores display",
    author="Guillaume Valadon",
    author_email="guillaume@valadon.net",
    version="0.1.0",
    packages=["ippon"],
    install_requires=[
        "beautifulsoup4",
        "cffi",
        "click",
        "raylib",
        "requests",
    ],
    entry_points={"console_scripts": ["ippon=ippon:main"]},
)
