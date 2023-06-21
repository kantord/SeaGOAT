import sys

from .codector import Codector


my_codector = Codector(sys.argv[1])
my_codector.analyze_files()
