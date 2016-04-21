from setuptools import setup

setup(
    name='wpas',
    version='0.1',
    description='Command line tool for simple wpa_supplicant management',
    py_modules=['wpas'],
    author='Thiago de Arruda',
    author_email='tpadilha84@gmail.com',
    url='http://github.com/tarruda/wpas',
    download_url='https://github.com/tarruda/wpas/archive/0.1.tar.gz',
    license='MIT',
    install_requires=[
        'Click',
        'click-default-group',
        'pydbus',
    ],
    entry_points='''
    [console_scripts]
    wpas=wpas:cli
    ''',
    )
