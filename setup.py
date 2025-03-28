import re
from typing import List

import setuptools

from ondewo.version import __version__


def read_file(file_path: str, encoding: str = 'utf-8') -> str:
    with open(file_path, 'r', encoding=encoding) as f:
        return f.read()


def read_requirements(file_path: str, encoding: str = 'utf-8') -> List[str]:
    with open(file_path, 'r', encoding=encoding) as f:
        requires = [
            re.sub(r'(.*)#egg=(.*)', r'\2 @ \1', line.strip())  # replace #egg= with @
            for line in f
            if line.strip() and not line.startswith('#')  # ignore empty lines and comments
        ]
    return requires


long_description: str = read_file('README.md')
requires: List[str] = read_requirements('requirements.txt')

setuptools.setup(
    name='ondewo-client-utils',
    version=f'{__version__}',
    author='Ondewo GmbH',
    author_email='office@ondewo.com',
    description='This library contains utilities and base classes for gRPC clients.',
    long_description=long_description,
    include_package_data=True,
    long_description_content_type='text/markdown',
    url='https://github.com/ondewo/ondewo-client-utils-python',
    packages=setuptools.find_packages(include=['ondewo*', ]),
    # https://pypi.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.9',
    install_requires=requires,
)
