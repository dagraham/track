from setuptools import setup, find_packages
from __version__ import version
from track import main

setup(
    name="track-dgraham",  # Replace with your app's name
    version=version,
    author="Daniel A Graham",  # Replace with your name
    author_email="dnlgrhm@gmail.com",  # Replace with your email
    description="This is a simple application for tracking the sequence of occasions on which a task is completed and predicting when the next completion might be needed.",
    long_description=open("README.md").read(),  # If you have a README file
    long_description_content_type="text/markdown",
    url="https://github.com/dagraham/track-dgraham",  # Replace with the repo URL if applicable
    packages=find_packages(),
    py_modules=["track"],  # If `track.py` is your main module
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",  # Replace with your license
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7.3",  # Specify the minimum Python version
    install_requires=[
        'prompt-toolkit>=3.0.24',
        'ruamel.yaml>=0.15.88',
        'python-dateutil>=2.7.3',
    ],
    entry_points={
        'console_scripts': [
            'track=main',  # Replace `main` with the main function to run
        ],
    },
)
