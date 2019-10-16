import codecs
from setuptools import setup, find_packages

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

TESTS_REQUIRE = [
    'nti.app.testing',
    'nti.testing',
    'zope.dottedname',
    'zope.testrunner',
]


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
        'Framework :: Zope',
        'Framework :: Pyramid',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: Implementation :: CPython',
    ],
    url="https://github.com/NextThought/nti.app.assessment",
    zip_safe=True,
    packages=find_packages('src'),
    package_dir={'': 'src'},
    include_package_data=True,
    namespace_packages=['nti', 'nti.app'],
    tests_require=TESTS_REQUIRE,
    install_requires=[
        'setuptools',
        'BTrees',
        'nti.app.contentlibrary',
        'nti.app.contenttypes.completion',
        'nti.app.contenttypes.calendar',
        'nti.assessment',
        'nti.base',
        'nti.common',
        'nti.containers',
        'nti.contentlibrary',
        'nti.contenttypes.courses',
        'nti.dublincore',
        'nti.externalization',
        'nti.links',
        'nti.namedfile',
        'nti.ntiids',
        'nti.property',
        'nti.publishing',
        'nti.recorder',
        'nti.schema',
        'nti.site',
        'nti.traversal',
        'nti.wref',
        'nti.zodb',
        'nti.zope_catalog',
        'ordered-set',
        'persistent',
        'pyramid',
        'simplejson',
        'six',
        'ZODB',
        'zope.annotation',
        'zope.cachedescriptors',
        'zope.component',
        'zope.container',
        'zope.deferredimport',
        'zope.deprecation',
        'zope.generations',
        'zope.i18n',
        'zope.i18nmessageid',
        'zope.interface',
        'zope.intid',
        'zope.lifecycleevent',
        'zope.location',
        'zope.mimetype',
        'zope.proxy',
        'zope.security',
        'zope.securitypolicy',
        'zope.traversing',
    ],
    extras_require={
        'test': TESTS_REQUIRE,
        'docs': [
            'Sphinx',
            'repoze.sphinx.autointerface',
            'sphinx_rtd_theme',
        ],
    },
    entry_points=entry_points,
)
