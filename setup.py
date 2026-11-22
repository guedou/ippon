# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

from setuptools import setup

setup(
    name="ippon",
    description="A sports scores display",
    author="Guillaume Valadon",
    author_email="guillaume@valadon.net",
    version="0.2.2",
    python_requires=">=3.10",
    packages=["ippon"],
    package_data={"ippon": ["assets/fonts/*.ttf", "assets/fonts/*.txt",
                             "assets/logos/*.png", "assets/logos/*.txt",
                             "assets/schedules/*.json"]},
    install_requires=[
        "beautifulsoup4",
        "cffi",
        "click",
        "raylib",
        "requests",
        "pronotepy==2.15.7",
    ],
    entry_points={"console_scripts": ["ippon=ippon:main"]},
)
