import os
from setuptools import setup
from pathlib import Path

# read the contents of your README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

# Prefer the GitHub Actions tag when building a release, but fall back to a
# local version so `pip install git+...` (e.g. from a Home Assistant custom
# integration manifest) doesn't blow up outside CI.
version = os.environ.get('GITHUB_REF_NAME') or '0.0.0+local'

setup(
    name='homgarapi',
    version=version,
    description='HomGar API client',
    long_description=long_description,
    long_description_content_type='text/markdown',
    keywords=['homgar'],
    url='https://github.com/Remboooo/homgarapi',
    download_url=f"https://github.com/Remboooo/homgarapi/archive/refs/tags/{version}.tar.gz",
    author='Rembrand van Lakwijk',
    author_email='rem@lakwijk.com',
    license='MIT',
    packages=['homgarapi'],
    install_requires=[
        'requests>=2.0.0',
        'PyYAML>=5.0.0',
        'platformdirs>=4.2.2',
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',

        'License :: OSI Approved :: MIT License',

        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
)
