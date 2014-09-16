from setuptools import setup, find_packages
import codecs

VERSION = '0.0.0'

entry_points = {
	"z3c.autoinclude.plugin": [
		'target = nti.app',
	],
	"console_scripts": [
		"nti_submission_report = nti.app.assessment.scripts.submissions:main",
		"nti_extract_assessments = nti.app.assessment._assignment_policy_extractor:main_extract_assignments",
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
	#url = 'https://github.com/NextThought/nti.nose_traceback_info',
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
		# NOTE: We actually depend on nti.dataserver
		# as well, but for the sake of legacy
		# deployments, we do not yet declare that.
		# We will declare it when everything is in
		# buildout
	],
	entry_points=entry_points
)
