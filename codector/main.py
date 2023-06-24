import sys

from engine import Engine


my_codector = Engine(sys.argv[1])
my_codector.analyze_codebase()
for file in my_codector.repository.top_files()[:1000]:
    print(file)
