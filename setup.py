from setuptools import setup, find_packages

setup(
    name="linklocal",
    version="1.0.0",
    description="A Python LAN P2P Chat System",
    packages=find_packages(),
    install_requires=[
        # Add required dependencies if any, likely cryptography or similar based on `peer.py`
        "cryptography",
        "flask", # Dashboard dependency maybe
    ],
    entry_points={
        "console_scripts": [
            "linklocal=linklocal.main:main", 
        ],
    },
)
