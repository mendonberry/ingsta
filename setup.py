from setuptools import setup, find_packages

setup(name='instagram-scraper',
      version='0.1',
      description=("instagram-scraper is a command-line application written in Python"
                    "that scrapes and downloads an instagram user\'s photos and videos. Use responsibly."),
      url='https://github.com/rarcega/instagram-scraper',
      author='Richard Arcega',
      license='Public domain',
      packages=find_packages(exclude=['tests*']),
      install_requires=["requests>=1.0.4",
                        "futures==2.2.0",
                        "tqdm>=3.8.0"],
      entry_points = {
        'console_scripts': ['instagram-scraper=instagram_scraper.app:main'],
      },
      zip_safe=False)
