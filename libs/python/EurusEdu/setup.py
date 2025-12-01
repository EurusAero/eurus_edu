from setuptools import setup, find_packages

setup(
    name='EurusEdu',
    version='0.0.1',
    author='EURUS',
    author_email='info@eurus-aero.ru',
    description='Eurus-Edu',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/EurusAero/Eurus-Edu',
    python_requires='>=3.10',
    packages=find_packages(),
    install_requires=[
    ]
)