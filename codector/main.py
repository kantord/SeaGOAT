import sys

from engine import Engine


my_codector = Engine(sys.argv[1])
my_codector.analyze_files()
