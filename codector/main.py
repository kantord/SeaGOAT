import sys

from engine import Engine


my_codector = Engine(sys.argv[1])
my_codector.analyze_files()
for file in my_codector.top_files()[:100]:
    print(file)
