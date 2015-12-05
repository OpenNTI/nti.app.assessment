import codecs
from setuptools import setup, find_packages

VERSION = '0.0.0'

entry_points = {
	"z3c.autoinclude.plugin": [
		'target = nti.app',
	],
	"console_scripts": [
		"nti_fix_enrollements = nti.app.assessment.scripts.nti_fix_enrollements:main",
		"nti_submission_report = nti.app.assessment.scripts.nti_submission_report:main",
		"nti_savepoint_migrator = nti.app.assessment.scripts.nti_savepoint_migrator:main",
		"nti_fix_assessment_leaks = nti.app.assessment.scripts.nti_fix_assessment_leaks:main",
		"nti_fix_assessment_units = nti.app.assessment.scripts.nti_fix_assessment_units:main"
	],
}

setup(
	name = 'nti.app.assessment',
	version = VERSION,
	author = 'Jason Madden',
	author_email = 'jason@nextthought.com',
	description = "Application-level assessment support",
	long_description = codecs.open('README.rst', encoding='utf-8').read(),
	license = 'Proprietary',
	keywords = 'pyramid assessment',
	classifiers = [
		'Intended Audience :: Developers',
		'Natural Language :: English',
		'Operating System :: OS Independent',
		'Programming Language :: Python :: 2',
		'Programming Language :: Python :: 2.7',
		'Framework :: Pyramid',
	],
	packages=find_packages('src'),
	package_dir={'': 'src'},
	namespace_packages=['nti', 'nti.app'],
	install_requires=[
		'setuptools',
		'nti.assessment',
		'nti.contenttypes.courses',
		'nti.app.products.courseware'
	],
	entry_points=entry_points
)
