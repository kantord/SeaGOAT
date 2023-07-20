# CHANGELOG



## v0.5.4 (2023-07-20)

### Fix

* fix: fix version handling (#34) ([`1418ab7`](https://github.com/kantord/SeaGOAT/commit/1418ab7217a2851a29c21ce3df6999f25160c7bc))

### Refactor

* refactor: remove redundant pytest-ordering (#33)

* refactor: remove redundant pytest-ordering

* fix: fix version handling ([`4995ef0`](https://github.com/kantord/SeaGOAT/commit/4995ef0c63dedf037e4256be4075a091381fb8c5))


## v0.5.3 (2023-07-19)

### Fix

* fix: fix package version in pypi (#31) ([`aaaeda7`](https://github.com/kantord/SeaGOAT/commit/aaaeda747d5f4a57aa901aff9429629f40cef700))


## v0.5.2 (2023-07-19)

### Fix

* fix: fix build for semantic release (#30) ([`4e93c88`](https://github.com/kantord/SeaGOAT/commit/4e93c88db5180d82f3fcdb7ffa36d4e17a816772))


## v0.5.1 (2023-07-19)

### Fix

* fix: server reported as running when process died ([`2758c18`](https://github.com/kantord/SeaGOAT/commit/2758c181b637e5eb1d947992b43bd5ea7611d8d2))


## v0.5.0 (2023-07-19)

### Chore

* chore: update dependencies ([`7f48ea1`](https://github.com/kantord/SeaGOAT/commit/7f48ea18e3a9f7e562a5d138fb31a4e9d8beb149))

* chore: only test changed files ([`cd5892b`](https://github.com/kantord/SeaGOAT/commit/cd5892b46aba52fa1592c1251230c8ac0a7c901c))

* chore: improve test output format ([`dbaa873`](https://github.com/kantord/SeaGOAT/commit/dbaa8732217330df3c801e5d71021a182a2497a1))

### Ci

* ci: add id to release step ([`afddc91`](https://github.com/kantord/SeaGOAT/commit/afddc91d5c5a9754be83f1f8886dc92e3fdcfc91))

### Feature

* feat: allow getting server status in JSON ([`0a9210d`](https://github.com/kantord/SeaGOAT/commit/0a9210d145679b5e298283e162ce5a03a82bf4c9))

### Test

* test: reduce logging level of chromadb in pytest ([`fff8693`](https://github.com/kantord/SeaGOAT/commit/fff869375bd4f510c14bbb181471da147b6a8ee9))

* test: run fast tests first ([`c7c60cf`](https://github.com/kantord/SeaGOAT/commit/c7c60cfa5085cb51faf3194450b3fcf7aff03720))


## v0.4.0 (2023-07-18)

### Ci

* ci: fix pypi release ([`6877972`](https://github.com/kantord/SeaGOAT/commit/68779722fa2517aded9ad21d05f5cf854cff58d7))

### Feature

* feat: add improved documentation to cli ([`02c10b4`](https://github.com/kantord/SeaGOAT/commit/02c10b41130fe21ae3f6ccf835079e123dd57ace))

### Test

* test: move server fixture to conftest ([`d510e87`](https://github.com/kantord/SeaGOAT/commit/d510e87ef7c2dbfab464e929703ba2b4299e7be3))


## v0.3.1 (2023-07-18)

### Chore

* chore: add setuptools as a dependency

it&#39;s needed because pkg_resources is used ([`efc23a3`](https://github.com/kantord/SeaGOAT/commit/efc23a3cd58cfd1d1555fd24a597c17c33036166))

* chore: don&#39;t markdownlint CHANGELOG.md ([`005fe21`](https://github.com/kantord/SeaGOAT/commit/005fe21d1b1bab7b2e43ddb1e9c148d224df1136))

### Ci

* ci: show console output in real time in pytest ([`573bd72`](https://github.com/kantord/SeaGOAT/commit/573bd7245448313700d78d031f43550862315a71))

* ci: add a timeout for tests ([`edea9cc`](https://github.com/kantord/SeaGOAT/commit/edea9cc72eec9533938ec852540b398dabe0ec8e))

* ci: make pytest verbose ([`834c1e1`](https://github.com/kantord/SeaGOAT/commit/834c1e18a242880d962727905838132508c4f2a5))

### Fix

* fix: use importlib.metadata for getting the version ([`d0c442c`](https://github.com/kantord/SeaGOAT/commit/d0c442cb63aa6dcfe8640c4bc02bb42df788528a))


## v0.3.0 (2023-07-18)

### Ci

* ci: release to pypi ([`8531561`](https://github.com/kantord/SeaGOAT/commit/8531561226e134b1b6fcb8d94294f91c6df70649))

### Feature

* feat: reveal seagoat version in query response ([`cd5c0ba`](https://github.com/kantord/SeaGOAT/commit/cd5c0ba86e75062a10a25118c68a0598bb5d9c13))


## v0.2.1 (2023-07-18)

### Fix

* fix: fix server imports ([`7d01530`](https://github.com/kantord/SeaGOAT/commit/7d015305582bb5a674b7abc7be1e12311bc18a04))


## v0.2.0 (2023-07-18)

### Chore

* chore: set up semantic-release ([`74e4085`](https://github.com/kantord/SeaGOAT/commit/74e40859faa469ae813944de31c4ff54e9e64615))

* chore: release new version ([`dc29537`](https://github.com/kantord/SeaGOAT/commit/dc295372787583cd8825899c951568f630558a11))

* chore: set license field in the package ([`3469a2e`](https://github.com/kantord/SeaGOAT/commit/3469a2e71b3e065d08141e130715c3737495379a))

* chore: rename project to seagoat ([`51c3415`](https://github.com/kantord/SeaGOAT/commit/51c3415e55d07ee31fd0361aca23bb3fa5678b17))

* chore: add tqdm dependency ([`ea32062`](https://github.com/kantord/SeaGOAT/commit/ea320623ad8c90ec24eb1ca6e3a55a8c9416d16d))

* chore: add pytest-watch ([`d2e97d9`](https://github.com/kantord/SeaGOAT/commit/d2e97d9956ad4a467110470546b4a9e1d3be8f35))

* chore: add pre-commit to simplify the CI ([`9d527cf`](https://github.com/kantord/SeaGOAT/commit/9d527cfe8a797aa19abd7a170fb3065d401caee0))

* chore: add some basic dependencies ([`680ce4a`](https://github.com/kantord/SeaGOAT/commit/680ce4a3ec56e7ea29423b0cfa88234187dc1b2a))

* chore: set up basic test framework ([`107fb7f`](https://github.com/kantord/SeaGOAT/commit/107fb7f351a15664a24b60b7ee02e8944f05162c))

### Ci

* ci: auto format yaml files ([`d01e233`](https://github.com/kantord/SeaGOAT/commit/d01e2331520e0ccbb91a23284dca1fa9df3a3f30))

* ci: add markdown linting ([`45a7c1e`](https://github.com/kantord/SeaGOAT/commit/45a7c1ec2a95c75125dd73c99d5a9b8febeee1a4))

* ci: test on osx ([`4e22195`](https://github.com/kantord/SeaGOAT/commit/4e22195d180156fa636205725ca076a54aaab064))

* ci: test on windows ([`09bdde0`](https://github.com/kantord/SeaGOAT/commit/09bdde0217b73bb8761cf961090f9899d5e11533))

* ci: install ripgrep ([`06e2fe9`](https://github.com/kantord/SeaGOAT/commit/06e2fe9e6e637c47c2de18d5ec7e9a4d5b1fc803))

* ci: fix test running in ci ([`6c7aed6`](https://github.com/kantord/SeaGOAT/commit/6c7aed6f2ac338d08f273f6d763ebc27a862300b))

* ci: add pyright ([`b6ba07b`](https://github.com/kantord/SeaGOAT/commit/b6ba07b9833d32b113eaba025cab5486e295c9f3))

* ci: test code formatting ([`ed3e68a`](https://github.com/kantord/SeaGOAT/commit/ed3e68a8ac92c2d1ba515932288d0ba08a048e57))

* ci: add pylint for code style tests ([`6b5c02c`](https://github.com/kantord/SeaGOAT/commit/6b5c02cceb3cdb6f53820ef712204d74ea314f22))

* ci: run tests in ci ([`c6b3c2c`](https://github.com/kantord/SeaGOAT/commit/c6b3c2cf55ec45e1ace8d7b0fb7a5c6c5a720eac))

### Documentation

* docs: add license ([`cdef01c`](https://github.com/kantord/SeaGOAT/commit/cdef01c2965abf9d91619bcbe6cb582d4a4569b8))

* docs: add ripgrep as a requirement ([`822bd19`](https://github.com/kantord/SeaGOAT/commit/822bd197f28aec03d1e3f6823c0d256bdc2c23b0))

* docs: add some minimal documentation ([`6b1aebd`](https://github.com/kantord/SeaGOAT/commit/6b1aebd734f4237f011154b74e2e02e6d5988c71))

### Feature

* feat: add seagoat-server ([`df55e71`](https://github.com/kantord/SeaGOAT/commit/df55e71e64936fa39173aa3e58305e22fdd697ee))

* feat: add seagoat script ([`56cfdf1`](https://github.com/kantord/SeaGOAT/commit/56cfdf112a237f548fc80badc616f9db93a7186f))

* feat: remove interactive mode ([`85388d4`](https://github.com/kantord/SeaGOAT/commit/85388d42ace22542691a69bcfb712a2ecf4b9b35))

* feat: consider file edit frequency in final sort ([`7e5ff3e`](https://github.com/kantord/SeaGOAT/commit/7e5ff3e7e634a4b5c51da8201527ff75ae55ecf6))

* feat: add grep style command line api ([`b904b28`](https://github.com/kantord/SeaGOAT/commit/b904b2800feef2004ad03f4be7dbcf9808538577))

* feat: sort files based on the best line in the file ([`1cba384`](https://github.com/kantord/SeaGOAT/commit/1cba384df89137571430517cf9c6f41af0a3d685))

* feat: fetch ripgrep and chromadb at the same time ([`bd7de64`](https://github.com/kantord/SeaGOAT/commit/bd7de649f9f57538697850a08d98a8fff4e6f17c))

* feat: ignore unsupported files also in ripgrep results ([`6eb75f6`](https://github.com/kantord/SeaGOAT/commit/6eb75f6c5defde4c75f43474c92a6ce40b2cf84d))

* feat: include results from ripgrep as well as chromadb ([`d9ff761`](https://github.com/kantord/SeaGOAT/commit/d9ff761745679649f3323cc068c90476b84c8412))

* feat: simplify prompt ([`2866251`](https://github.com/kantord/SeaGOAT/commit/286625182973296b7733106ad13ca485e327e5c4))

* feat: save cursor location before printing ([`37c4f58`](https://github.com/kantord/SeaGOAT/commit/37c4f58e1675112cd9c262cecd35d5b69065d2e7))

* feat: give extra score to exact matches ([`5ee1d8b`](https://github.com/kantord/SeaGOAT/commit/5ee1d8b824376b61d94116c89ecf5754617f7197))

* feat: prioritize including more files in the results ([`af7b2b3`](https://github.com/kantord/SeaGOAT/commit/af7b2b3a8f4bc0b583e4d9906814da76701e22a6))

* feat: include at least 20% of files ([`10541e4`](https://github.com/kantord/SeaGOAT/commit/10541e4bb6dcf7b4318e976e3f3dff8fb441af0c))

* feat: be more strict ignoring irrelevant lines ([`d41b4e7`](https://github.com/kantord/SeaGOAT/commit/d41b4e7ac42c18932ee04615695e185a73a7b70c))

* feat: show continous fragments visually ([`337e560`](https://github.com/kantord/SeaGOAT/commit/337e560ef1f0e33c2dfc8c70eb6fa848ee61fe92))

* feat: add syntax highlighting ([`100a57f`](https://github.com/kantord/SeaGOAT/commit/100a57f53f347b18cf6b51170cd6c0d755b1492c))

* feat: query results in real time ([`36e34b8`](https://github.com/kantord/SeaGOAT/commit/36e34b8a5072e853aff9ef027c17de2ed1ab1752))

* feat: group results by file ([`3323b2b`](https://github.com/kantord/SeaGOAT/commit/3323b2baf662682716b236491358e7bd09660268))

* feat: add simple interactive main command ([`7b846e9`](https://github.com/kantord/SeaGOAT/commit/7b846e9f4029acc8810b8be3a374e91eaab26f06))

* feat: add click library for CLI ([`c4ace51`](https://github.com/kantord/SeaGOAT/commit/c4ace51f92e0de520706b601da49458974187ed2))

* feat: add more lines of context if needed for relevance ([`27e9660`](https://github.com/kantord/SeaGOAT/commit/27e966087bd106d06b50a4e15eb9fb53d9b5a1cf))

* feat: do not create chunks for lines with little content ([`63bd3c8`](https://github.com/kantord/SeaGOAT/commit/63bd3c8a4044dea0730c2bfb9330662ef91aafdf))

* feat: cache vector embeddings ([`8626f93`](https://github.com/kantord/SeaGOAT/commit/8626f938aa134e96d54cc4a2de89ae3e011db0e3))

* feat: allow querying using vector embeddings ([`c9d7338`](https://github.com/kantord/SeaGOAT/commit/c9d73383e6ee4d4b4f6f4e8e617fd08350d99634))

* feat: allow querying results using chromadb ([`ae5dbea`](https://github.com/kantord/SeaGOAT/commit/ae5dbeace1626e0d340099c21420b9ce8fb4be0a))

* feat: only cache supported file types ([`192dc53`](https://github.com/kantord/SeaGOAT/commit/192dc539bdaf2d5d22462f6422a4d6c23b84717e))

* feat: avoid failing when cache is damaged ([`d8b1c42`](https://github.com/kantord/SeaGOAT/commit/d8b1c42f8ea0a57fb659af6b1995087dff270ac6))

* feat: persist cache between different sessions ([`3192679`](https://github.com/kantord/SeaGOAT/commit/31926791a849b069ce4f1b825f9291def9cc2dda))

* feat: don&#39;t analyze same commit twice ([`726bb18`](https://github.com/kantord/SeaGOAT/commit/726bb1855bc5da386d20724351d3f0cec326545c))

* feat: enable getting metadata from File ([`e082c10`](https://github.com/kantord/SeaGOAT/commit/e082c1028c88970855efbe702d42d5983b1f0ea5))

* feat: allow testing with local repositories ([`b4b1cd7`](https://github.com/kantord/SeaGOAT/commit/b4b1cd74a9ca1f8ddb308adc9806733b56519e95))

* feat: collect commit messages ([`50f08ee`](https://github.com/kantord/SeaGOAT/commit/50f08ee90824fc261825a4c302b8805a15c92aab))

* feat: prioritize recently changed files ([`c338c6f`](https://github.com/kantord/SeaGOAT/commit/c338c6f2bd80bc32d651f6f1841d2dd7853b6718))

* feat: return frequently changed files first ([`8076547`](https://github.com/kantord/SeaGOAT/commit/8076547798afd5c61a229074658e1ddd5b680049))

* feat: list files from all branches ([`116f6e8`](https://github.com/kantord/SeaGOAT/commit/116f6e8f7650fae3fd71b34c337940600e4e83ca))

* feat: allow returning list of files ([`3bac9dd`](https://github.com/kantord/SeaGOAT/commit/3bac9dda7d48acf164710b864232c95ac0270ee2))

### Fix

* fix: fix path for ripgrep source ([`00aecf0`](https://github.com/kantord/SeaGOAT/commit/00aecf0bd95f825c34725af916f8afa1b2c79f50))

* fix: disable chromadb telemetry ([`1392c27`](https://github.com/kantord/SeaGOAT/commit/1392c27d2f0a4d6bf2a935a278a5251c84f8cc1d))

* fix: fix minor problems with how the prompt is displayed ([`0fecb8b`](https://github.com/kantord/SeaGOAT/commit/0fecb8bb6df69eedaf409f6957b15c50c9bcb620))

* fix: correctly recalculate score over time ([`9d7c716`](https://github.com/kantord/SeaGOAT/commit/9d7c716befc66da6ccc7860698f25fda46eb7c5d))

* fix: avoid infinite recursion when saving cache ([`8fffec2`](https://github.com/kantord/SeaGOAT/commit/8fffec29ed1ceb3df4c9ba61e5e42fece25e62ea))

* fix: avoid division by zero when calculating file score ([`2a29cd1`](https://github.com/kantord/SeaGOAT/commit/2a29cd15c5fac605f98d559cac20d3bf4533a8dc))

* fix: fix import style in manual testing file ([`7af3247`](https://github.com/kantord/SeaGOAT/commit/7af32470b7b0c43a5fbb541b1e8ac8849ae446c6))

### Performance

* perf: use server to make all queries ([`c07d3cb`](https://github.com/kantord/SeaGOAT/commit/c07d3cbaa37d8d93b0099b3a023300ae1a42a651))

* perf: improve highlight performance ([`1507166`](https://github.com/kantord/SeaGOAT/commit/15071662c43476066a2a6fd767cdf9937475b91a))

### Refactor

* refactor: remove unused pylint ignore comment ([`f37c4bd`](https://github.com/kantord/SeaGOAT/commit/f37c4bd85fd970c85ce305a345291067681c9ef7))

* refactor: extract ripgrep fetcher to a separate file ([`0b43a40`](https://github.com/kantord/SeaGOAT/commit/0b43a4015f14f90080a9458650c9a8b20a55bb31))

* refactor: extract get_score() ([`ec986a1`](https://github.com/kantord/SeaGOAT/commit/ec986a10be41f903265ecd0d282f7fdca9c973ce))

* refactor: extract ResultLine ([`c267a4e`](https://github.com/kantord/SeaGOAT/commit/c267a4e3a54cc7b100cf317c42edaaeeeed70f6f))

* refactor: extract _get_chunk_for_line ([`ba2c292`](https://github.com/kantord/SeaGOAT/commit/ba2c2922307b77fed8256e2955f5b662bbf1d33c))

* refactor: extract _format_chunk_summary() ([`90fe7f9`](https://github.com/kantord/SeaGOAT/commit/90fe7f9af50f5d0de06cb67c445a5d55636125fd))

* refactor: extract _get_file_lines() ([`8a0b5e7`](https://github.com/kantord/SeaGOAT/commit/8a0b5e7a99ab1ae83c2b4e7109f83e6704e893bd))

* refactor: extract cache logic to separate class ([`4d75f7e`](https://github.com/kantord/SeaGOAT/commit/4d75f7e4b80158121d21096957a02bb21bdabe25))

* refactor: rename analyze_files to analyze_codebase ([`cbff894`](https://github.com/kantord/SeaGOAT/commit/cbff8940d103fa4d4e616b3baee90af235ba8e86))

* refactor: extract Repository class ([`43352fc`](https://github.com/kantord/SeaGOAT/commit/43352fcade163e25d56eba71fa41cba47a01a402))

* refactor: rename test_engine to test_repo_analysis ([`d32feb4`](https://github.com/kantord/SeaGOAT/commit/d32feb4e265484064339f858ec88b5163d1fa6dd))

* refactor: simplify cache logic ([`b85a914`](https://github.com/kantord/SeaGOAT/commit/b85a914d66e6b654ac74c40487820c43bec54a49))

* refactor: rename Codector class to Engine ([`d40d1cb`](https://github.com/kantord/SeaGOAT/commit/d40d1cba7156a3f92f5846453e567ed5377a7a2e))

* refactor: move commit analysis to File ([`a29d2ce`](https://github.com/kantord/SeaGOAT/commit/a29d2cecb5f7d7f34c9b9bfc2b59c7cc17494316))

* refactor: move file class to separate file ([`5a1a592`](https://github.com/kantord/SeaGOAT/commit/5a1a5927422c505fee49d55bce9cbc174af61156))

* refactor: simplify getting metadata for each file ([`b37d7a5`](https://github.com/kantord/SeaGOAT/commit/b37d7a587bfc37006433e2dcc4f14f83c702ff62))

* refactor: extract _sort_files ([`df2190e`](https://github.com/kantord/SeaGOAT/commit/df2190efc3c8454bb458a3673e4b8b2c5468a931))

* refactor: extract _get_all_commits ([`c40c372`](https://github.com/kantord/SeaGOAT/commit/c40c372f5ddc5dbba9801b8ed0373b136da82c04))

* refactor: remove useless methods ([`8bd3542`](https://github.com/kantord/SeaGOAT/commit/8bd35429d1dc1b9f17e14bbcd7866ee9e8411859))

* refactor: extract add_file_change_commit()

Initial commit for Markdown file

Update to Markdown file

Initial commit for Python file

Update to Python file

Initial commit for another Python file

Initial commit for JavaScript file

Update to JavaScript file

Second update to JavaScript file

Initial commit for Markdown file

Update to Markdown file

Initial commit for Python file

Update to Python file

Initial commit for another Python file

Initial commit for JavaScript file

Update to JavaScript file

Second update to JavaScript file

Initial commit for Markdown file

Update to Markdown file

Initial commit for Python file

Update to Python file

Initial commit for another Python file

Initial commit for JavaScript file

Update to JavaScript file

Second update to JavaScript file

Initial commit for Markdown file

Update to Markdown file

Initial commit for Python file

Update to Python file

Initial commit for another Python file

Initial commit for JavaScript file

Update to JavaScript file

Second update to JavaScript file

Initial commit for Markdown file

Update to Markdown file

Initial commit for Python file

Update to Python file

Initial commit for another Python file

Initial commit for JavaScript file

Update to JavaScript file

Second update to JavaScript file ([`54434a8`](https://github.com/kantord/SeaGOAT/commit/54434a861003248176069d537edbcd39bf770ff1))

### Test

* test: allow reusing commit authors ([`98fd476`](https://github.com/kantord/SeaGOAT/commit/98fd476d3deafa372fd3a8fd41df9fd32e1a95a5))

* test: add fake git repo fixture ([`8b50561`](https://github.com/kantord/SeaGOAT/commit/8b50561782241134e12011a269ef0078625c83d0))

### Unknown

* Merge pull request #1 from kantord/fix-score-computation

fix: correctly recalculate score over time ([`bf23f40`](https://github.com/kantord/SeaGOAT/commit/bf23f40a90f0a0aab2cf903d065362ba4490f722))

* Initial commit ([`69202ce`](https://github.com/kantord/SeaGOAT/commit/69202ce7acd3644c413e2882f44410784aaa8e6f))
