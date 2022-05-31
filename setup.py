import setuptools

with open("README.md", "r") as f:
    long_description = f.read()

with open("requirements.txt") as f:
    requires = f.read().splitlines()

setuptools.setup(
    name="ondewo-client-utils",
    version="0.1.1",
    author="Ondewo GbmH",
    author_email="info@ondewo.com",
    description="This library contains utilities and base classes for gRPC clients.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ondewo/ondewo-client-utils-python",
    packages=[
        np for np in filter(lambda n: n.startswith("ondewo.") or n == "ondewo", setuptools.find_packages())
    ],
    package_data={"ondewo.utils": ["py.typed"]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "Development Status :: 3 - Alpha",
        "Topic :: Software Development :: Libraries",
    ],
    python_requires=">=2.6,!=3.0.*",
    install_requires=requires,
)
