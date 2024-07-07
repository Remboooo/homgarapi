from setuptools import setup

setup(
    name='homgarapi',
    version='0.0.1',
    description='HomGar API client',
    keywords=['homgar'],
    url='https://github.com/Remboooo/homgarapi',
    download_url='https://github.com/Remboooo/homgarapi/archive/refs/tags/v0.0.1.tar.gz',
    author='Rembrand van Lakwijk',
    author_email='rem@lakwijk.com',
    license='MIT',
    packages=['homgarapi'],
    install_requires=[
        'requests>=2.0.0',
        'PyYAML>=5.0.0',
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
