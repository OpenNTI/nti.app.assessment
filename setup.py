import codecs
from setuptools import setup, find_packages

VERSION = '0.0.0'

entry_points = {
    "z3c.autoinclude.plugin": [
        'target = nti.app',
    ],
    "console_scripts": [
        "nti_fix_enrollements = nti.app.assessment.scripts.nti_fix_enrollements:main",
        "nti_savepoint_migrator = nti.app.assessment.scripts.nti_savepoint_migrator:main",
        "nti_check_assessment_integrity = nti.app.assessment.scripts.nti_check_assessment_integrity:main",
        "nti_remove_invalid_assessments = nti.app.assessment.scripts.nti_remove_invalid_assessments:main"
    ],
}


def _read(fname):
    with codecs.open(fname, encoding='utf-8') as f:
        return f.read()


setup(
    name='nti.app.assessment',
    version=_read('version.txt').strip(),
    author='Jason Madden',
    author_email='jason@nextthought.com',
    description="Application-level assessment support",
    long_description=(_read('README.rst') + '\n\n' + _read("CHANGES.rst")),
    license='Apache',
    keywords='pyramid assessment',
    classifiers=[
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: Implementation :: CPython'
    ],
    zip_safe=True,
    packages=find_packages('src'),
    package_dir={'': 'src'},
    include_package_data=True,
    namespace_packages=['nti', 'nti.app'],
    install_requires=[
        'setuptools',
        'nti.assessment',
        'nti.contenttypes.courses',
        'ordered-set'
    ],
    entry_points=entry_points,
)
