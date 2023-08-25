from setuptools import setup

setup(
    name='homgarapi',
    version='0.0.1',
    description='HomGar API client',
    url='https://github.com/Remboooo/ha-core',
    author='Rembrand van Lakwijk',
    author_email='rem@lakwijk.com',
    license='MIT',
    packages=['homgarapi'],
    install_requires=[
        'requests>=2.0.0',
        'PyYAML>=5.0.0',
    ],
)
