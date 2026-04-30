from setuptools import setup, find_packages

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="bitcoin-sentinel",
    version="0.1.0",
    description="Real-time Bitcoin fraud and scam detection engine",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Bitcoin Sentinel Contributors",
    license="Apache-2.0",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.10",
    install_requires=[
        "websockets>=12.0",
        "aiohttp>=3.9.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0.0",
            "pytest-asyncio>=0.23.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "bitcoin-sentinel=main:cli_main",
        ]
    },
    package_data={
        "": ["data/*.json"],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Security",
        "Topic :: Internet :: WWW/HTTP",
    ],
)
