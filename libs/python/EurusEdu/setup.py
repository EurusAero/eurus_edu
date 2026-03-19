from setuptools import setup, find_packages

setup(
    name='EurusEdu',
    version='0.1.0',
    author='EURUS-AERO',
    author_email='info@eurus-aero.ru',
    description='Eurus-Edu',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/EurusAero/eurus_edu',
    python_requires='>=3.10',
    packages=find_packages(),
    install_requires=["opencv-python",
                      "numpy"
                      ]
)