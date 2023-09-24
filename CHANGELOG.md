# CHANGELOG



## v0.30.1 (2023-09-24)

### Fix

* fix: avoid crashing when file no longer exists (#247)

fixes #245 ([`d85231a`](https://github.com/kantord/SeaGOAT/commit/d85231a9647052c773fb7c38dc618b3e46298f81))


## v0.30.0 (2023-09-24)

### Feature

* feat: detect file encoding to support encodings other than UTF-8

* Try to ignore binary files

* Fix typo in README

* fix: always detect a file encoding

* test: test that other encodings are supported

* add FileReader

* docs: document list of supported character encodings

---------

Co-authored-by: Daniel Kantor &lt;git@daniel-kantor.com&gt; ([`3b889bc`](https://github.com/kantord/SeaGOAT/commit/3b889bc43a5464f457a461b321f3bf851e75d6cc))


## v0.29.3 (2023-09-23)

### Chore

* chore(deps): update actions/checkout digest to 8ade135 (#242)

Co-authored-by: renovate[bot] &lt;29139614+renovate[bot]@users.noreply.github.com&gt; ([`6e774aa`](https://github.com/kantord/SeaGOAT/commit/6e774aad53d29eae0bb289554db4d1d6578ee17f))

### Fix

* fix: support Windows file paths (#234) ([`fe11547`](https://github.com/kantord/SeaGOAT/commit/fe11547432240fa6d0dab41894bee34fc054cf6a))


## v0.29.2 (2023-09-23)

### Chore

* chore(deps): update dependency mkdocs-material to v9.4.1 (#239)

Co-authored-by: renovate[bot] &lt;29139614+renovate[bot]@users.noreply.github.com&gt; ([`3af3112`](https://github.com/kantord/SeaGOAT/commit/3af311251506f5d99f319b493f20a258e2625e4c))

### Fix

* fix: support commit messages that contain :::

* Fix exception in repositories with commits containing &#39;:::&#39; in commit message

Setting [maxsplit](https://docs.python.org/3/library/stdtypes.html#str.split).

The following exception was thrown:

```
Exception in thread Thread-1 (_worker_function):
Traceback (most recent call last):
  File &#34;/home/user/.local/pipx/venvs/seagoat/lib/python3.11/site-packages/seagoat/queue/base_queue.py&#34;, line 76, in _worker_function
    task = self._task_queue.get(timeout=1)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File &#34;/usr/lib/python3.11/queue.py&#34;, line 179, in get
    raise Empty
_queue.Empty

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File &#34;/usr/lib/python3.11/threading.py&#34;, line 1038, in _bootstrap_inner
    self.run()
  File &#34;/usr/lib/python3.11/threading.py&#34;, line 975, in run
    self._target(*self._args, **self._kwargs)
  File &#34;/home/user/.local/pipx/venvs/seagoat/lib/python3.11/site-packages/seagoat/queue/base_queue.py&#34;, line 81, in _worker_function
    self.handle_maintenance(context)
  File &#34;/home/user/.local/pipx/venvs/seagoat/lib/python3.11/site-packages/seagoat/queue/task_queue.py&#34;, line 50, in handle_maintenance
    remaining_chunks_to_analyze = context[&#34;seagoat_engine&#34;].analyze_codebase(
                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File &#34;/home/user/.local/pipx/venvs/seagoat/lib/python3.11/site-packages/seagoat/engine.py&#34;, line 82, in analyze_codebase
    self.repository.analyze_files()
  File &#34;/home/user/.local/pipx/venvs/seagoat/lib/python3.11/site-packages/seagoat/repository.py&#34;, line 46, in analyze_files
    current_commit_info = parse_commit_info(line)
                          ^^^^^^^^^^^^^^^^^^^^^^^
  File &#34;/home/user/.local/pipx/venvs/seagoat/lib/python3.11/site-packages/seagoat/repository.py&#34;, line 12, in parse_commit_info
    commit_hash, date_str, author, commit_subject = raw_line.split(&#34;:::&#34;)
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ValueError: too many values to unpack (expected 4)
```

* Test commit messages with three or more colons

* style: fix code style issues

---------

Co-authored-by: Daniel Kantor &lt;git@daniel-kantor.com&gt; ([`2a2df42`](https://github.com/kantord/SeaGOAT/commit/2a2df42cd84ebd4be9484a1c2a2c87903d7304b1))


## v0.29.1 (2023-09-22)

### Chore

* chore(deps): update dependency mkdocs-material to v9.4.0 (#235)

Co-authored-by: renovate[bot] &lt;29139614+renovate[bot]@users.noreply.github.com&gt; ([`4b6e74a`](https://github.com/kantord/SeaGOAT/commit/4b6e74a06bf8ff02c0ca2a4e0c4df963d42636ea))

### Documentation

* docs: document why SeaGOAT is not maxing out CPU (#233) ([`2499b6b`](https://github.com/kantord/SeaGOAT/commit/2499b6b2e1965299b1b514dbebd40b47906e198e))

### Fix

* fix(deps): update dependency gitpython to v3.1.37 (#237)

Co-authored-by: renovate[bot] &lt;29139614+renovate[bot]@users.noreply.github.com&gt; ([`28e3c2d`](https://github.com/kantord/SeaGOAT/commit/28e3c2d21b601feb66cdf808fe0c7f79768cfc04))

### Unknown

* Update README.md (#230)

fixing typo about Operating Systems ([`51ae32c`](https://github.com/kantord/SeaGOAT/commit/51ae32c845365e64226f49d031769c6b47673bb1))


## v0.29.0 (2023-09-20)

### Feature

* feat: support .cc and .cxx files

* added support for alternative C++ extension (cc)

* modified readme to reflect that .cc extension is supported

* .cxx for C++ also ([`8ebd516`](https://github.com/kantord/SeaGOAT/commit/8ebd516b456d6655c7ba07b575bfdb19e919c5a5))


## v0.28.0 (2023-09-20)

### Chore

* chore(deps): update python-semantic-release/python-semantic-release action to v8.1.1 (#219)

Co-authored-by: renovate[bot] &lt;29139614+renovate[bot]@users.noreply.github.com&gt; ([`1b581e3`](https://github.com/kantord/SeaGOAT/commit/1b581e32546321d2ed04bd8c030b355c1fa3ac01))

* chore(deps): update dependency mkdocs-material to v9.3.2 (#217)

Co-authored-by: renovate[bot] &lt;29139614+renovate[bot]@users.noreply.github.com&gt; ([`c444f9e`](https://github.com/kantord/SeaGOAT/commit/c444f9edfd496872b80d1e4d665596d77e5db8b3))

### Documentation

* docs: fix URL for Bat (#221) ([`55c3ab3`](https://github.com/kantord/SeaGOAT/commit/55c3ab3bb3f2130e4b213656cc27b906dd31279d))

* docs: add notice about me looking for a job

* Update README.md

* docs: small grammar fix ([`05b4805`](https://github.com/kantord/SeaGOAT/commit/05b4805765b293b0c3b8a2caa14c3124da113bf0))

### Feature

* feat: support more programming languages

this is an empty commit to trigger a release
after this malformed commit message:
https://github.com/kantord/SeaGOAT/commit/5b33c3eff26e6d8c157c6cac6d2524fc9bc8f06a ([`634b129`](https://github.com/kantord/SeaGOAT/commit/634b129f2e38ed58c57697842cfa08299bd4d07c))

### Unknown

* Support more programming languages (#223)

* feat: extend set of supported languages

To support at least this list:
https://huggingface.co/datasets/code_search_net#languages

* docs: document list of supported languages ([`5b33c3e`](https://github.com/kantord/SeaGOAT/commit/5b33c3eff26e6d8c157c6cac6d2524fc9bc8f06a))


## v0.27.2 (2023-09-20)

### Fix

* fix(deps): update dependency chromadb to v0.4.12 ([`73f7826`](https://github.com/kantord/SeaGOAT/commit/73f78265aad6c75974697c300a67f6352d425902))


## v0.27.1 (2023-09-19)

### Documentation

* docs: document query API ([`08f8cee`](https://github.com/kantord/SeaGOAT/commit/08f8cee0998ecd86ce55f19a235ad5c577297a25))

### Fix

* fix(deps): update dependency chromadb to v0.4.11 ([`a2f494c`](https://github.com/kantord/SeaGOAT/commit/a2f494ceaad9481f8aa22d9fd37c03e3c53d4aa0))


## v0.27.0 (2023-09-18)

### Feature

* feat: include isRunning for server-info ([`023ea85`](https://github.com/kantord/SeaGOAT/commit/023ea85ca4f7c40b5c27fb609b45a3612e2e661f))


## v0.26.0 (2023-09-18)

### Feature

* feat: allow getting list of servers as JSON ([`21ff638`](https://github.com/kantord/SeaGOAT/commit/21ff638f517f64256460ca37c9c09dc20898dbec))


## v0.25.1 (2023-09-17)

### Chore

* chore(deps): update dependency pyright to v1.1.327 ([`ffcc519`](https://github.com/kantord/SeaGOAT/commit/ffcc519342fef9cffabb783b0887dc823b84c234))

### Fix

* fix(deps): update dependency nest-asyncio to v1.5.8 ([`7483c99`](https://github.com/kantord/SeaGOAT/commit/7483c99540d364bb4023a5280307a2223f442853))

### Refactor

* refactor: use a single file for all server info ([`76471bb`](https://github.com/kantord/SeaGOAT/commit/76471bb9f22245868e27c9d48bda5c0ff34677eb))


## v0.25.0 (2023-09-13)

### Feature

* feat: make scores rounded to 4 digits ([`80c4ec2`](https://github.com/kantord/SeaGOAT/commit/80c4ec2b6800b09714a32480af83e7a38fef596f))

* feat: include score for result lines ([`868d01f`](https://github.com/kantord/SeaGOAT/commit/868d01fa7f25b01255beeb1207f77327e152f632))

* feat: include score in results ([`2cde673`](https://github.com/kantord/SeaGOAT/commit/2cde67396b7e97302091883dbe8bf68169811aec))


## v0.24.0 (2023-09-13)

### Feature

* feat: make grep vs chroma results more balanced ([`c802358`](https://github.com/kantord/SeaGOAT/commit/c8023586ffcd92d0c0d3b74aa00e819f615ad03d))


## v0.23.6 (2023-09-13)

### Documentation

* docs: update macos call to action in README ([`ad53cad`](https://github.com/kantord/SeaGOAT/commit/ad53cad2013fb4b822c01f6183b4fcfd004b57d4))

### Fix

* fix: avoid crashing when there are no results

test: test what happens when there are no results ([`49d28a2`](https://github.com/kantord/SeaGOAT/commit/49d28a2cd768633868199400673c70ba2095e6e6))


## v0.23.5 (2023-09-12)

### Fix

* fix(deps): update dependency setuptools to v68.2.2 ([`45c69a0`](https://github.com/kantord/SeaGOAT/commit/45c69a07de8f050c90ec981b4af16214eee20d11))


## v0.23.4 (2023-09-12)

### Fix

* fix(deps): update dependency gitpython to v3.1.36 ([`48c9a18`](https://github.com/kantord/SeaGOAT/commit/48c9a181d8955fbc4de333b1797b404322edf823))

* fix(deps): update dependency chromadb to v0.4.10 ([`837443e`](https://github.com/kantord/SeaGOAT/commit/837443ef8c648ebc7e0736e822a564d422897f4f))


## v0.23.3 (2023-09-12)

### Ci

* ci: run all tests on Mac OS ([`68cb84a`](https://github.com/kantord/SeaGOAT/commit/68cb84a6c02d07dc667688485de43099d08f93fc))

* ci: run more tests for Mac OS ([`b3f8406`](https://github.com/kantord/SeaGOAT/commit/b3f84065210dd844536c2a843e96d6616d480b51))

### Fix

* fix: fix tests in mac os ([`9f215fd`](https://github.com/kantord/SeaGOAT/commit/9f215fdafa5b8ef33e8e8eaddeed70d14c70b74a))


## v0.23.2 (2023-09-11)

### Chore

* chore(deps): update dependency mkdocs-material to v9.3.0 ([`fa540bc`](https://github.com/kantord/SeaGOAT/commit/fa540bc7576e61b72bad09b35fe58045d534fdac))

* chore(deps): update dependency black to v23.9.1 ([`d414da7`](https://github.com/kantord/SeaGOAT/commit/d414da7d2219f6bb72d6d212f3a76495723cb366))

### Fix

* fix(deps): update dependency setuptools to v68.2.1 ([`54cfc12`](https://github.com/kantord/SeaGOAT/commit/54cfc128c2fc66764724ae9f1701ea868bd10540))


## v0.23.1 (2023-09-10)

### Fix

* fix: use a Queue type that works on Mac OS ([`d6d6761`](https://github.com/kantord/SeaGOAT/commit/d6d67616aaf7012c8019477541f3b56ab971f3be))


## v0.23.0 (2023-09-10)

### Chore

* chore(deps): update dependency black to v23.9.0 ([`8b82efc`](https://github.com/kantord/SeaGOAT/commit/8b82efc3dcafa16c5471e6fcf6bc50fa2f111d9a))

### Documentation

* docs: add info about system requirements ([`4cf71fa`](https://github.com/kantord/SeaGOAT/commit/4cf71faeb8738e1a01a48bc2560a2628c83da585))

* docs: add titles to slideshow gif ([`c581e36`](https://github.com/kantord/SeaGOAT/commit/c581e3660938c9f9bbb0654a0b039f891f73208b))

* docs: use a slideshow for the demo gif ([`0e8c510`](https://github.com/kantord/SeaGOAT/commit/0e8c5107e098c676915b153305ef8bc91e772cb3))

* docs: change gif theme ([`a9b76ad`](https://github.com/kantord/SeaGOAT/commit/a9b76adc4c21418fbf5709ae9440d71841412af6))

* docs: improve gif quality

.

.

docs: update asciinema cast

docs: update dmoe gif ([`3c7a96a`](https://github.com/kantord/SeaGOAT/commit/3c7a96abcfa57aee14dcbd1c32b665622c98b677))

### Feature

* feat: use waitress as an HTTP server ([`16b31c2`](https://github.com/kantord/SeaGOAT/commit/16b31c244056d29d6d90d5e6c6b4348c53cffe9e))


## v0.22.1 (2023-09-08)

### Fix

* fix(deps): update dependency orjson to v3.9.7 ([`43b963c`](https://github.com/kantord/SeaGOAT/commit/43b963c98fd5c5d24a5571c4abfea4948bbc4185))


## v0.22.0 (2023-09-08)

### Documentation

* docs: fix too long lines in SECURITY.md ([`73c8d0b`](https://github.com/kantord/SeaGOAT/commit/73c8d0b3977c0ecd9459b32014215d2ad24f206a))

### Feature

* feat: make regular expressions case insensitive ([`868c5f5`](https://github.com/kantord/SeaGOAT/commit/868c5f528b4f1f5cfbbdd047d5bd823a3d97b9db))

### Unknown

* Create SECURITY.md ([`013af0d`](https://github.com/kantord/SeaGOAT/commit/013af0d4b6a5408a5bcf35b44aa242d000430c3f))


## v0.21.0 (2023-09-08)

### Feature

* feat: automatically update database if codebase changes ([`1218f2c`](https://github.com/kantord/SeaGOAT/commit/1218f2c5bf929349198493fefae1ca5d3343f7d3))


## v0.20.2 (2023-09-08)

### Chore

* chore(deps): update dependency pytest to v7.4.2 ([`499c433`](https://github.com/kantord/SeaGOAT/commit/499c433fbc006d47ea478b710328cef4ab57e9e3))

### Fix

* fix(deps): update dependency orjson to v3.9.6 ([`7dd57be`](https://github.com/kantord/SeaGOAT/commit/7dd57be96b3bedcbf1185af9c8d6e694a7a50a2b))


## v0.20.1 (2023-09-07)

### Chore

* chore(deps): update dependency pyright to v1.1.326 ([`2d3ec94`](https://github.com/kantord/SeaGOAT/commit/2d3ec94476a340821d9cd04dbc488c36f6c6ba7a))

### Ci

* ci: enable testing for windows ([`1edae8e`](https://github.com/kantord/SeaGOAT/commit/1edae8e4b9272906300046cf99bb5de8fd4256aa))

* ci: enable testing for mac os ([`6033e9e`](https://github.com/kantord/SeaGOAT/commit/6033e9ea7c7fca95ee716d58db39f68fce053e63))

### Documentation

* docs: update project description in readme ([`d0a268a`](https://github.com/kantord/SeaGOAT/commit/d0a268a388299a0bedba86971f58740154489c68))

* docs: add faq section ([`e02bb1b`](https://github.com/kantord/SeaGOAT/commit/e02bb1badeca0b2289dc6e6ac045f2d7edf97c9f))

### Fix

* fix(deps): update dependency gitpython to v3.1.35 ([`282cba4`](https://github.com/kantord/SeaGOAT/commit/282cba4e95fbf4cc5a276265fc51b0c3b90ba10f))


## v0.20.0 (2023-09-07)

### Feature

* feat: show a warning when SeaGOAT is outdated

fixes #171 ([`6c64239`](https://github.com/kantord/SeaGOAT/commit/6c6423926a49ea343e7d45faad9a5beb51174607))


## v0.19.5 (2023-09-07)

### Fix

* fix(deps): update dependency setuptools to v68.2.0 ([`2925223`](https://github.com/kantord/SeaGOAT/commit/292522369e14c0cd658fa31c01bbd5ae62eabdc3))


## v0.19.4 (2023-09-06)

### Performance

* perf: avoid wasting time processing irrelevant results ([`b03b936`](https://github.com/kantord/SeaGOAT/commit/b03b9364550977c70dd88241ba41b3217994069a))


## v0.19.3 (2023-09-06)

### Chore

* chore(deps): update dependency mkdocs-material to v9.2.8 ([`2f23318`](https://github.com/kantord/SeaGOAT/commit/2f233184f64692d632968ac183b88532f2bd3a25))

### Fix

* fix(deps): update dependency chromadb to v0.4.9 ([`9ec0b6a`](https://github.com/kantord/SeaGOAT/commit/9ec0b6acf6af29d7caffa0a141815e5fc8eae2a6))

### Refactor

* refactor: move get_free_port to utils ([`9caefa9`](https://github.com/kantord/SeaGOAT/commit/9caefa9170d81144f38cc6fe1e9c74b80c351915))

* refactor: remove load_server_info ([`be71e62`](https://github.com/kantord/SeaGOAT/commit/be71e6269012097775f69012f43b3d8bb0d25938))

* refactor: simplify load_server_info ([`ec6e501`](https://github.com/kantord/SeaGOAT/commit/ec6e5015456b6e3e217b87bfcfdd0798f43e8518))

* refactor: add address to get_server_info ([`e8e33b6`](https://github.com/kantord/SeaGOAT/commit/e8e33b6d706c21c17f990e3f57e4cb885bcfdbe1))

* refactor: create get_server_info() ([`963a6d5`](https://github.com/kantord/SeaGOAT/commit/963a6d573a73d682c643ae93a4958b1a248abc44))

* refactor: extract get_json_file_contents ([`48264b9`](https://github.com/kantord/SeaGOAT/commit/48264b906093cd18862d20d7f47639bca46db642))

* refactor: use orjson in utils ([`6bd61e4`](https://github.com/kantord/SeaGOAT/commit/6bd61e4e9883cbbd0db6868e9474ff6978d5f7ee))

* refactor: simplify args of is_server_running() ([`f9c2b4b`](https://github.com/kantord/SeaGOAT/commit/f9c2b4b6041083448219c45ce25c24562df5353c))

* refactor: move is_server_running to utils ([`a9004c9`](https://github.com/kantord/SeaGOAT/commit/a9004c9a6eaca8c497216d78cc9865c461cd6a0f))


## v0.19.2 (2023-09-04)

### Chore

* chore(deps): update actions/checkout action to v4 ([`56934cb`](https://github.com/kantord/SeaGOAT/commit/56934cb2da053cd59deb0da038060cf8b3bd4013))

* chore(deps): update dependency pre-commit to v3.4.0 ([`0dfd947`](https://github.com/kantord/SeaGOAT/commit/0dfd9473dc7f53055e669c9920dbcbc0449e2e11))

* chore(deps): update dependency mkdocs-material to v9.2.7 ([`ead0117`](https://github.com/kantord/SeaGOAT/commit/ead01173b2f0620c7e33a754e87a074b04923fd5))

* chore(deps): update dependency pytest to v7.4.1 ([`8479a16`](https://github.com/kantord/SeaGOAT/commit/8479a1673a78bfbc1860c151653e652eabbeda8f))

### Performance

* perf: use a faster json deserialization tool ([`090e8d5`](https://github.com/kantord/SeaGOAT/commit/090e8d5e106487635638a8651fc37386b0770064))

* perf: avoid double deserlization ([`6e1ecc4`](https://github.com/kantord/SeaGOAT/commit/6e1ecc40bec81ba211959707ecc176f5c658d932))

* perf: use a faster JSON serialization tool ([`3187315`](https://github.com/kantord/SeaGOAT/commit/31873152ae936f6925f8569f18026b6aea2d9250))

* perf: avoid double serialization ([`981532a`](https://github.com/kantord/SeaGOAT/commit/981532af82541768b891f29b5a9423ffab3910f0))

* perf: remove redundant code ([`8752892`](https://github.com/kantord/SeaGOAT/commit/87528920fe11e1cfda5cbfdf42503a847055759a))

* perf: avoid overfetching results ([`c0c1c6c`](https://github.com/kantord/SeaGOAT/commit/c0c1c6c494a48bab71a8ac5ca871b22180fe71c0))


## v0.19.1 (2023-09-02)

### Chore

* chore: log when a task on the queue is being handled ([`55321ba`](https://github.com/kantord/SeaGOAT/commit/55321ba252da05f0fe833ba9fcfb8217231b8630))

* chore(deps): update dependency syrupy to v4.5.0 ([`d1d6700`](https://github.com/kantord/SeaGOAT/commit/d1d670016853708eaec7d5c86035d9323f3b02ad))

### Fix

* fix(deps): update dependency gitpython to v3.1.34 ([`0548a84`](https://github.com/kantord/SeaGOAT/commit/0548a84d96e06e9202014b6f82a07e951c7abc6e))


## v0.19.0 (2023-09-01)

### Chore

* chore(deps): update dependency ipython to v8.15.0 ([`9c19d36`](https://github.com/kantord/SeaGOAT/commit/9c19d367355cea2f17f7c4e22cc1820570638be8))

### Documentation

* docs: document bat usage ([`173853c`](https://github.com/kantord/SeaGOAT/commit/173853cd93463e1c436e96357442a0a5a93b7437))

### Feature

* feat: group results together when printing with bat ([`f8e26f8`](https://github.com/kantord/SeaGOAT/commit/f8e26f8dd7a58becccd494a2f48b8fa04993364f))

* feat: display results with bat

fixes: #145 ([`199b06d`](https://github.com/kantord/SeaGOAT/commit/199b06daa293875da8d192cf97bf54c3861255bb))

### Fix

* fix: never use pager in bat ([`86e8d5d`](https://github.com/kantord/SeaGOAT/commit/86e8d5d8697d3999690e475969ec27a5fd255551))

### Refactor

* refactor: extract print_result_block() ([`3acbe18`](https://github.com/kantord/SeaGOAT/commit/3acbe18bcd50bd1d37df42aa871512d5ceed6b8e))

* refactor: iterate lines in display_results() ([`ebadc81`](https://github.com/kantord/SeaGOAT/commit/ebadc8157685bd271210c376d940cac6f9b4a349))


## v0.18.0 (2023-09-01)

### Feature

* feat: only display full code blocks in result ([`e2767f9`](https://github.com/kantord/SeaGOAT/commit/e2767f98ece3023e01ec4a6d95cd14701b11f842))

### Refactor

* refactor: count line types for each block ([`aa13645`](https://github.com/kantord/SeaGOAT/commit/aa1364569541205696930663ae34543ea5353dcc))


## v0.17.2 (2023-09-01)

### Fix

* fix(deps): update dependency gitpython to v3.1.33 ([`7e25ab5`](https://github.com/kantord/SeaGOAT/commit/7e25ab52bfe3b2d4c95126fac25ba82250b92011))

### Refactor

* refactor: group continuous lines into blocks ([`6a15673`](https://github.com/kantord/SeaGOAT/commit/6a15673e27bf906f8aca4e7eb000a8e24ba56acf))

* refactor: nest lines under blocks ([`b50158f`](https://github.com/kantord/SeaGOAT/commit/b50158f0e6181f3f6721c321475112dfef512542))

* refactor: add to_json() to ResultBlock ([`a1423be`](https://github.com/kantord/SeaGOAT/commit/a1423be803e6892ac0a362f058e7a3dfb07d3cec))

* refactor: rename &#34;lines&#34; to &#34;blocks&#34; ([`27321fc`](https://github.com/kantord/SeaGOAT/commit/27321fc7579690a67dcebe43756d5e994dd95081))

* refactor: create ResultBlock ([`f02fdcd`](https://github.com/kantord/SeaGOAT/commit/f02fdcdeeffc2406a2a18ad0d918fa93a4d4e22b))

* refactor: move wait_for to utils ([`1bb1255`](https://github.com/kantord/SeaGOAT/commit/1bb12558c5e24d0b1302a59de1f8ae06e05639de))

* refactor: create utils folder ([`6244c51`](https://github.com/kantord/SeaGOAT/commit/6244c51de8a27e83f4ee152375150d6da1386214))

* refactor: extract display utils to a separate files ([`9efef1b`](https://github.com/kantord/SeaGOAT/commit/9efef1bef098564e0ccff1ee4fea628306f9733c))

* refactor: reuse _handle_task ([`cdfca1e`](https://github.com/kantord/SeaGOAT/commit/cdfca1ea8e1bfc0c4529282bbb15a49dbbd81a81))

* refactor: move worker function to BaseQueue ([`0ff8be2`](https://github.com/kantord/SeaGOAT/commit/0ff8be2bffbcf9339c58f603b41d8f8dcecc7b1e))

* refactor: handle chunks using task handlers ([`9489715`](https://github.com/kantord/SeaGOAT/commit/9489715105999bfdd428dccf0f6caa722e75c191))

* refactor: use Task dataclass instead of named tuple ([`ba81343`](https://github.com/kantord/SeaGOAT/commit/ba813431b229e1b6aac4880120a23f5afdfe6e3b))

* refactor: use Task for low prio queues ([`b61bc29`](https://github.com/kantord/SeaGOAT/commit/b61bc292ed2f6d868def8ae9d272cf195ead66b7))

* refactor: force kwargs only for queues ([`2127263`](https://github.com/kantord/SeaGOAT/commit/21272634d777cb819c713ae3ecc4f6d7ad7c4319))

* refactor: extract _get_context ([`2d8c24a`](https://github.com/kantord/SeaGOAT/commit/2d8c24a6c3df2aa3cad4aa21949a36f94cbfa050))

* refactor: rename chunks_to_analyze to low_priority_queue ([`440e9da`](https://github.com/kantord/SeaGOAT/commit/440e9daa27c7fa1324abaa1fe8217c649726e1ad))

* refactor: rename enqueue to enqueue_high_prio ([`221dba8`](https://github.com/kantord/SeaGOAT/commit/221dba8317b6fa0dbd42ade79ec46b067ba7c138))

* refactor: extract _handle_task ([`68fe9d8`](https://github.com/kantord/SeaGOAT/commit/68fe9d86d1129c7701add050ffd290b1e5155fe8))

* refactor: extract BaseQueue ([`73edaf2`](https://github.com/kantord/SeaGOAT/commit/73edaf281860bfd7349d2fce1f08c01acc156829))

* refactor: move queue to a separate folder ([`438887d`](https://github.com/kantord/SeaGOAT/commit/438887d22569c0e59cf6353893881227a2cd04ee))

### Test

* test: fix flaky test ([`528e639`](https://github.com/kantord/SeaGOAT/commit/528e63979fc60622846a643c6fc8ee8a2c8373ac))


## v0.17.1 (2023-08-31)

### Chore

* chore(deps): update dependency mkdocs-material to v9.2.6 ([`e210648`](https://github.com/kantord/SeaGOAT/commit/e2106485b8fe9453ef55d595bef2f0a7b6393cf2))

* chore(deps): update dependency pyright to v1.1.325 ([`018c1f6`](https://github.com/kantord/SeaGOAT/commit/018c1f6371845bc10e262f93085a15464b76c35a))

### Performance

* perf: avoid importing pygments when it&#39;s not needed ([`25fb7ac`](https://github.com/kantord/SeaGOAT/commit/25fb7acba2803d38c88b5ae19978fd4040125bcc))

* perf: avoid loading server dependencies in CLI

fixes #126 ([`e26078d`](https://github.com/kantord/SeaGOAT/commit/e26078db97e4b14c459f5655c93e4d6bd0f78e8e))


## v0.17.0 (2023-08-30)

### Chore

* chore(deps): update dependency syrupy to v4.4.0 ([`396c6f6`](https://github.com/kantord/SeaGOAT/commit/396c6f6239c8b8b50ff60ecbdf8157181fb4457a))

### Feature

* feat: display a warning if chunks are not fully analyzed ([`6bc200d`](https://github.com/kantord/SeaGOAT/commit/6bc200d2dd7a0065d403fda281da28e002507a05))

* feat: use a more sophisticated formula for accuracy ([`c3fa172`](https://github.com/kantord/SeaGOAT/commit/c3fa1723b0ef3307ead73c615014408c79be50e3))

* feat: estimate accuracy using square root formula ([`d31c13d`](https://github.com/kantord/SeaGOAT/commit/d31c13da0430894b7d90ad4cd5713b4eff84fbb6))

* feat: allow starting server before preanalyzing chunks ([`e28ffd8`](https://github.com/kantord/SeaGOAT/commit/e28ffd88ae93dad5a5e85a21ecec024175ad6b0f))

* feat: disable telemetry for chromadb ([`dfcf053`](https://github.com/kantord/SeaGOAT/commit/dfcf05313c03652ab318819e330b2053363b57ba))

* feat: analyze all files using the queue ([`84ea9f4`](https://github.com/kantord/SeaGOAT/commit/84ea9f4eadc724529fe0cf3ba19a57f90f833cfe))


## v0.16.2 (2023-08-29)

### Chore

* chore(deps): update dependency syrupy to v4.3.0 ([`650d4e1`](https://github.com/kantord/SeaGOAT/commit/650d4e14119c1d5e784a04e8e39da01321271cce))

* chore(deps): update dependency mkdocs-material to v9.2.5 ([`59e6ac7`](https://github.com/kantord/SeaGOAT/commit/59e6ac73dff76d68ab8bcce854a246df2fee1803))

* chore(deps): update python-semantic-release/python-semantic-release action to v8.0.8 ([`2b9512b`](https://github.com/kantord/SeaGOAT/commit/2b9512b475d1d7ed7b1af7a8190a58e12ab58964))

* chore(deps): update dependency python-semantic-release to v8.0.8 ([`95510e9`](https://github.com/kantord/SeaGOAT/commit/95510e95366a6335e103163b730f8e9aa91fb1d4))

* chore(deps): update dependency mkdocs-material to v9.2.4 ([`4f47410`](https://github.com/kantord/SeaGOAT/commit/4f47410307e4de55ba8bd01800ef8af27c2edade))

### Fix

* fix(deps): update dependency chromadb to v0.4.8 ([`cb93d6e`](https://github.com/kantord/SeaGOAT/commit/cb93d6ec9e7582e3d36360bcde3c9d8574aad629))


## v0.16.1 (2023-08-24)

### Chore

* chore(deps): update dependency pyright to v1.1.324 ([`5c3bba0`](https://github.com/kantord/SeaGOAT/commit/5c3bba08aac47b040d4b0efd1fcfa38900091f38))

* chore(deps): update dependency mkdocs-material to v9.2.3 ([`4eeecea`](https://github.com/kantord/SeaGOAT/commit/4eeeceaa329eecb9b507e42fa774bf29f1971296))

### Documentation

* docs: fix formatting issue ([`f98c440`](https://github.com/kantord/SeaGOAT/commit/f98c440f85b02ac00a256ddb47b2917f1550e759))

* docs: add &#34;bat-signal&#34;

part of this documentation: https://app.gitbook.com/o/frj4DkAraQA62Kx3r3Ah/s/aGFK5cc3nFU7yY7QWW6r/builders-area/guides/week-1-kick-ass-readme-+-intro ([`91f35ad`](https://github.com/kantord/SeaGOAT/commit/91f35adecb3f5e37354404b2b4a6d8ac4e85e8f3))

### Fix

* fix(deps): update dependency chromadb to v0.4.7 ([`e03deb4`](https://github.com/kantord/SeaGOAT/commit/e03deb40748c4c486c5392f4b0cdce1ce3b24b47))


## v0.16.0 (2023-08-22)

### Chore

* chore(deps): update dependency mkdocs-material to v9.2.2 ([`c7c37bb`](https://github.com/kantord/SeaGOAT/commit/c7c37bba6c7788024e736b273b619585e3650664))

### Feature

* feat: allow analyzing a specific number of files in Engine ([`7d7cb66`](https://github.com/kantord/SeaGOAT/commit/7d7cb66751faeed676909f788e3736cfdd6ef1df))

### Refactor

* refactor: extract _process_chunk ([`4392727`](https://github.com/kantord/SeaGOAT/commit/4392727ad8017255c18c342ea28f84e37e7455d8))

### Test

* test: make source faker reusable ([`e25ecb7`](https://github.com/kantord/SeaGOAT/commit/e25ecb74e50c7691358671e6cf29950ed5f7d105))


## v0.15.2 (2023-08-22)

### Fix

* fix: task queue unexpectedly dies ([`b217b6a`](https://github.com/kantord/SeaGOAT/commit/b217b6acdd25edd57eeecc23bd57ca291a1600bb))


## v0.15.1 (2023-08-22)

### Chore

* chore(deps): update dependency syrupy to v4.2.1 ([`c535201`](https://github.com/kantord/SeaGOAT/commit/c53520176fe5a2e6a04e77dd11f84db9ddf00ec5))

* chore(deps): update dependency mkdocs-material to v9.2.1 ([`28a8066`](https://github.com/kantord/SeaGOAT/commit/28a8066f12fb6acfbcdc91d5d4c257352b370fca))

* chore(deps): update dependency mkdocs-material to v9.2.0 ([`75edfd3`](https://github.com/kantord/SeaGOAT/commit/75edfd361ef19aa76824e608e065553b5e2437da))

### Fix

* fix(deps): update dependency flask to v2.3.3 ([`06b9157`](https://github.com/kantord/SeaGOAT/commit/06b9157fa7f49dad2ffdb5d9bb999a44e7838d81))


## v0.15.0 (2023-08-21)

### Chore

* chore(deps): update dependency syrupy to v4.2.0 ([`984697e`](https://github.com/kantord/SeaGOAT/commit/984697e6083a3c029fa3a85a8c9958b63a1b6b55))

### Feature

* feat: allow running server on custom port

fixes #75 ([`01f36d9`](https://github.com/kantord/SeaGOAT/commit/01f36d92e39859c6dffceea78903c382ab1da595))

### Refactor

* refactor: extract get_free_port() ([`1dfcaa3`](https://github.com/kantord/SeaGOAT/commit/1dfcaa3717cd44908f848cba62e4c47f267892ad))

* refactor: create a simple task queue ([`4cb0017`](https://github.com/kantord/SeaGOAT/commit/4cb0017ef5f64f9b84ca7af3cdfc64bc609b8141))


## v0.14.0 (2023-08-19)

### Feature

* feat: add --version to seagoat-server

fixes #101 ([`8c2e127`](https://github.com/kantord/SeaGOAT/commit/8c2e127079e1db5548839c47a8214fc205ae4adf))

### Fix

* fix: display server errors to user

fixes #114 ([`d768d6f`](https://github.com/kantord/SeaGOAT/commit/d768d6f9ba67f840616a7ecfcf82b956dc7ee634))

### Refactor

* refactor: use click.echo() instead of print() ([`d147008`](https://github.com/kantord/SeaGOAT/commit/d14700844027f53cb203a7a0f7e6f62703bea6ec))


## v0.13.0 (2023-08-18)

### Feature

* feat: add --context/--context-above-/--context-below

refactor: extract _include_context_lines ([`4fe4887`](https://github.com/kantord/SeaGOAT/commit/4fe4887e9dbb9c355ae664e30906b7dc21dcdbe0))


## v0.12.5 (2023-08-18)

### Chore

* chore(deps): update dependency syrupy to v4.1.1 ([`bc55692`](https://github.com/kantord/SeaGOAT/commit/bc55692870c1a4f959b78ba841f9d6781e9caf0c))

### Fix

* fix(deps): update dependency setuptools to v68.1.2 ([`dcf57e6`](https://github.com/kantord/SeaGOAT/commit/dcf57e65e5c8f794267dd9f9ff1d1d665ba7fb3a))


## v0.12.4 (2023-08-17)

### Chore

* chore(deps): update python-semantic-release/python-semantic-release action to v8.0.7 ([`237fd96`](https://github.com/kantord/SeaGOAT/commit/237fd96b8d9045d3684c1f9ca3377f941c262a7d))

* chore(deps): update dependency python-semantic-release to v8.0.7 ([`2b0a79e`](https://github.com/kantord/SeaGOAT/commit/2b0a79e4a1b7ad588bf1a50a4e088fa756c58a80))

* chore(deps): update dependency syrupy to v4.1.0 ([`63e5e84`](https://github.com/kantord/SeaGOAT/commit/63e5e844865c24c7edfa642a2f7b9412aae7e1c5))

* chore(deps): update dependency pyright to v1.1.323 ([`2811f26`](https://github.com/kantord/SeaGOAT/commit/2811f265df0fc2539da250690b1f218ced3fdd14))

### Fix

* fix(deps): update dependency click to v8.1.7 ([`e8f0de1`](https://github.com/kantord/SeaGOAT/commit/e8f0de146bfb33314318e1e38416e5254dccb77b))


## v0.12.3 (2023-08-15)

### Fix

* fix(deps): update dependency setuptools to v68.1.0 ([`a445ae4`](https://github.com/kantord/SeaGOAT/commit/a445ae454e3d4437fcdd00214ff02d70f8c4e4b0))


## v0.12.2 (2023-08-15)

### Chore

* chore(deps): update dependency exceptiongroup to v1.1.3 ([`01c03ca`](https://github.com/kantord/SeaGOAT/commit/01c03caad9f455cc3aa542dbeb418575689246e4))

* chore(deps): update python-semantic-release/python-semantic-release action to v8.0.6 ([`b8d4f04`](https://github.com/kantord/SeaGOAT/commit/b8d4f04ee982c874e86b0b97ba80ca57ae9e8bf7))

* chore(deps): update dependency python-semantic-release to v8.0.6 ([`a1b3fd9`](https://github.com/kantord/SeaGOAT/commit/a1b3fd9daf825d9392c2635b0743d368292f8dec))

### Fix

* fix(deps): update dependency chromadb to v0.4.6 ([`e1520c8`](https://github.com/kantord/SeaGOAT/commit/e1520c8e70d488f6cddd3f63d7608ddf07b222d4))


## v0.12.1 (2023-08-12)

### Chore

* chore(deps): update dependency pyright to v1.1.322 ([`c3c053f`](https://github.com/kantord/SeaGOAT/commit/c3c053f88424d78156fe86be56785dc885a1551b))

### Performance

* perf: dramatically speed up frecency analysis ([`84e8345`](https://github.com/kantord/SeaGOAT/commit/84e8345e1d00c03696103da5083b1d550d06aa15))


## v0.12.0 (2023-08-12)

### Chore

* chore(deps): update python-semantic-release/python-semantic-release action to v8.0.5 ([`ccd05f9`](https://github.com/kantord/SeaGOAT/commit/ccd05f9495ed72892fb7fbb0b7239b92fcdbc04b))

* chore(deps): update dependency python-semantic-release to v8.0.5 ([`091d0b0`](https://github.com/kantord/SeaGOAT/commit/091d0b029cc2d136341146828866d9f191b54dd2))

### Feature

* feat: reduce bias/noise in result sorting ([`557ae30`](https://github.com/kantord/SeaGOAT/commit/557ae309c85fe7b627aabc108e83ee96680ef182))


## v0.11.0 (2023-08-10)

### Feature

* feat: include reason why line was included in result ([`8df8101`](https://github.com/kantord/SeaGOAT/commit/8df8101cead6cf4c51680eefaa25d6be560816af))

### Refactor

* refactor: use dict instead of set to store result lines ([`8d26fda`](https://github.com/kantord/SeaGOAT/commit/8d26fda489b757e00726c6944d927f217f5fdb62))


## v0.10.6 (2023-08-10)

### Chore

* chore(deps): update dependency pyright to v1.1.321 ([`5d7fe81`](https://github.com/kantord/SeaGOAT/commit/5d7fe81937e59d96c9def07ce7b80103d530bf48))

### Fix

* fix(deps): update dependency tqdm to v4.66.1 ([`b29ba3b`](https://github.com/kantord/SeaGOAT/commit/b29ba3b277b8ddee9f44e8ed22e1df85faa45399))


## v0.10.5 (2023-08-09)

### Performance

* perf: limit regexp file size to 200K ([`9cc2c5f`](https://github.com/kantord/SeaGOAT/commit/9cc2c5fdefd45df9e4cba27d8ae22fa538e12ce8))

* perf: limit number of regex results per file ([`13bec2a`](https://github.com/kantord/SeaGOAT/commit/13bec2a015a17b8bfa2d0b46be4b5462b5756d96))

* perf: forward limit clue to server ([`dacb96d`](https://github.com/kantord/SeaGOAT/commit/dacb96d3def75602abec1f1ec5bb904819012599))

### Style

* style: remove unnecessary pylint ignore ([`56ebcdd`](https://github.com/kantord/SeaGOAT/commit/56ebcdd1cb56be044068934317c23de909cbbc8c))


## v0.10.4 (2023-08-09)

### Fix

* fix(deps): update dependency tqdm to v4.66.0 ([`ec737ca`](https://github.com/kantord/SeaGOAT/commit/ec737ca9238acd2af90605d226d15ffc70eb7e73))


## v0.10.3 (2023-08-09)

### Fix

* fix(deps): update dependency tqdm to v4.65.2 ([`1e09ac9`](https://github.com/kantord/SeaGOAT/commit/1e09ac9064231ef44614035754e6e976f017784b))


## v0.10.2 (2023-08-08)

### Fix

* fix(deps): update dependency tqdm to v4.65.1 ([`900c61e`](https://github.com/kantord/SeaGOAT/commit/900c61ee627eaefb7fee943a5a8c3c98d77eae18))


## v0.10.1 (2023-08-08)

### Performance

* perf: avoid overfetching data when limit is specified ([`a7904cf`](https://github.com/kantord/SeaGOAT/commit/a7904cfeca639fc4b04bc1daf9d528a74ef3eef2))


## v0.10.0 (2023-08-07)

### Documentation

* docs: document how to use regular expressions ([`0bce61b`](https://github.com/kantord/SeaGOAT/commit/0bce61b723aa32c524d656ab1d8ca72f3fbb9a2e))

### Feature

* feat: allow combining regexp and vector embeddings ([`1a7c40c`](https://github.com/kantord/SeaGOAT/commit/1a7c40cd2f4d9fcdc21ad1b6b5976873d358318e))

### Fix

* fix: re-add missing CLI documentation ([`1955e2f`](https://github.com/kantord/SeaGOAT/commit/1955e2fe7eac24a6ea0ed4991ccad910cb2a97f6))

### Test

* test: add a unit test for the ripgrep source ([`444b7ba`](https://github.com/kantord/SeaGOAT/commit/444b7ba98f1297587af0cf87643c2ef6db78aa4e))

* test: add missing docs for regexp ([`91f2873`](https://github.com/kantord/SeaGOAT/commit/91f2873a4c1970ad42ddae79133b496f4eb66a5f))


## v0.9.3 (2023-08-06)

### Fix

* fix(deps): update dependency pygments to v2.16.1 ([`262484a`](https://github.com/kantord/SeaGOAT/commit/262484ad7ea4096691220cc340ef06277814a3c5))


## v0.9.2 (2023-08-04)

### Documentation

* docs: add demo gif ([`3efad89`](https://github.com/kantord/SeaGOAT/commit/3efad89055c5676180589bd6dcd4838fd75bebb5))

* docs: group patch versions together to avoid spamming ([`f3c41cc`](https://github.com/kantord/SeaGOAT/commit/f3c41ccf63545e37394af987d728ec41e0e29972))

### Fix

* fix(deps): update dependency chromadb to v0.4.5 ([`36e7001`](https://github.com/kantord/SeaGOAT/commit/36e7001bf3c82d615eafc00ce815c05b41649e65))


## v0.9.1 (2023-08-02)

### Chore

* chore: add python-semantic-release as a dependency ([`b426e55`](https://github.com/kantord/SeaGOAT/commit/b426e55ca45d50e7428b79fcf84c88cb3f3635e4))

### Documentation

* docs: add title to code examples to save space ([`4febf4f`](https://github.com/kantord/SeaGOAT/commit/4febf4f49b30dd486d268e8cfa9f2b20b8081a19))

* docs: allow copying code examples ([`88f1891`](https://github.com/kantord/SeaGOAT/commit/88f1891bdd8ba4b37c790591829297e4fb857c70))

* docs: use syntax highlight configuration from docs

https://squidfunk.github.io/mkdocs-material/reference/code-blocks/#configuration ([`f900aa6`](https://github.com/kantord/SeaGOAT/commit/f900aa6fbe61544f3ac0301b15ded4bb539347e1))

* docs: put usage examples close to relevant sections ([`12f6282`](https://github.com/kantord/SeaGOAT/commit/12f6282510f41140bee8456d87514a9d99601716))

* docs: document that SeaGOAT only works with Git ([`f90bb2e`](https://github.com/kantord/SeaGOAT/commit/f90bb2e29a8a37829ef8c0f9893d3ceba669cbe9))

* docs: document usage ([`7e0445c`](https://github.com/kantord/SeaGOAT/commit/7e0445c8ff7e4a44a6d41e4e880168b6609abf5f))

### Fix

* fix(deps): update dependency chromadb to v0.4.4 ([`88df96c`](https://github.com/kantord/SeaGOAT/commit/88df96c70c6bebc6b5f073d1d115a354e4d22da6))


## v0.9.0 (2023-08-02)

### Chore

* chore(deps): update dependency pyright to v1.1.320 ([`3ac3b81`](https://github.com/kantord/SeaGOAT/commit/3ac3b811c940b89c92147356cecb901c2aca161d))

### Ci

* ci: update docs build to use semantic-release to get the version ([`1f602e8`](https://github.com/kantord/SeaGOAT/commit/1f602e87dfa03567ee09d01736e88616b2f340a3))

### Documentation

* docs: recommend using pipx instead of pip ([`4afe920`](https://github.com/kantord/SeaGOAT/commit/4afe9202a7d18e3979f56caf6b2a057743d60061))

### Feature

* feat: allow short format for --max-results ([`2817be7`](https://github.com/kantord/SeaGOAT/commit/2817be75434a5d010b306b5bee6a177b3c713394))

* feat: allow limiting the number of results ([`99a1d7b`](https://github.com/kantord/SeaGOAT/commit/99a1d7be02c2013044aff7ea3547ac0668a6e498))

### Refactor

* refactor: use an iterator for limiting the results ([`6d92543`](https://github.com/kantord/SeaGOAT/commit/6d925433778a2986b07be3ff58bd8a937c90d555))


## v0.8.9 (2023-07-31)

### Fix

* fix: enable docs deployment again ([`1efbaa0`](https://github.com/kantord/SeaGOAT/commit/1efbaa0858d4682c9830f6b857f0e53dba030cde))


## v0.8.8 (2023-07-30)

### Fix

* fix: fix git identity for deployments ([`7ed0350`](https://github.com/kantord/SeaGOAT/commit/7ed0350be77b25141c731d879f8e0b2ddac386e8))


## v0.8.7 (2023-07-30)

### Ci

* ci: automatically create latest tag ([`26a0181`](https://github.com/kantord/SeaGOAT/commit/26a0181e4fedfee11bac41cd24b02745aa04e394))

### Fix

* fix: temporarily remove docs deployment ([`038c6cd`](https://github.com/kantord/SeaGOAT/commit/038c6cd244d184b31f26b5c1234d8468ecb0cf9f))


## v0.8.6 (2023-07-30)

### Fix

* fix: fix poetry install in docs build ([`0cc4620`](https://github.com/kantord/SeaGOAT/commit/0cc4620e7d9e68ecead4a585b67c77c8347ba9d5))


## v0.8.5 (2023-07-30)

### Fix

* fix: try to fix docs build ([`b03bf35`](https://github.com/kantord/SeaGOAT/commit/b03bf35086b45e5bcbc3bd2c3de467a4be92c120))


## v0.8.4 (2023-07-30)

### Fix

* fix: attempt to fix docs build ([`d3be803`](https://github.com/kantord/SeaGOAT/commit/d3be803999d02e9c7886ee0afe18d13ea1ab5943))


## v0.8.3 (2023-07-30)

### Fix

* fix: yet another attempt to fix docs build ([`35682d1`](https://github.com/kantord/SeaGOAT/commit/35682d1bafe480668e69d010d1f38c0824e054a3))


## v0.8.2 (2023-07-30)

### Fix

* fix: fix docs deployment after release ([`eafb3fa`](https://github.com/kantord/SeaGOAT/commit/eafb3fa72ad733ec8eaaceabc73cfdf9019569a7))


## v0.8.1 (2023-07-30)

### Fix

* fix: fix release process ([`ce26f81`](https://github.com/kantord/SeaGOAT/commit/ce26f811907599474d0f3494795d11b4ac5d4f7b))


## v0.8.0 (2023-07-30)

### Ci

* ci: fix how poetry is installed in release.yml ([`4c0cda2`](https://github.com/kantord/SeaGOAT/commit/4c0cda2979460870b1ccdeb2d05f0ba9fd9130dc))

* ci: install poetry directly before running mike ([`b14828e`](https://github.com/kantord/SeaGOAT/commit/b14828ea01dc95d8718ecfb6d6228f4a5a440e98))

### Documentation

* docs: warn user that their documentation version is outdated ([`5749273`](https://github.com/kantord/SeaGOAT/commit/5749273fe52376ba97db22a6b1f508230e29cea3))

### Feature

* feat: show a more helpful message when server offline ([`32b9f6d`](https://github.com/kantord/SeaGOAT/commit/32b9f6d8940c7f630df12ddccbfda2942f5fdb21))


## v0.7.3 (2023-07-30)

### Ci

* ci: set up docs versioning ([`101e733`](https://github.com/kantord/SeaGOAT/commit/101e733f64cb206a8c01bb273ea4aee1399d62c6))

### Fix

* fix(deps): update dependency chromadb to ^0.4.0 ([`bebf58e`](https://github.com/kantord/SeaGOAT/commit/bebf58eb7de945da2b070ff129072f3eafbe8708))

### Refactor

* refactor: remove unnecessary persist() logic ([`112138e`](https://github.com/kantord/SeaGOAT/commit/112138ef66924848c5b8977903afc3c58edd8eaf))


## v0.7.2 (2023-07-30)

### Fix

* fix: fix single-sourced version ([`2a97445`](https://github.com/kantord/SeaGOAT/commit/2a974452e0f5fa68bdd407018a6e7de00bd80b25))


## v0.7.1 (2023-07-30)

### Fix

* fix: incorrect version number is displayed with --version ([`3e3d553`](https://github.com/kantord/SeaGOAT/commit/3e3d553eb4da332104d1aa319470f71f1a718bb0))


## v0.7.0 (2023-07-29)

### Ci

* ci: only release aur package when new version is released ([`0d7d26a`](https://github.com/kantord/SeaGOAT/commit/0d7d26ac213202e6c6a2ffa92805ec75956c7356))

* ci: automatically update AUR package ([`15b7ab2`](https://github.com/kantord/SeaGOAT/commit/15b7ab2fdd5d1d94537244a939c141bf70db4f2a))

### Feature

* feat: document server usage in help text ([`f96ac47`](https://github.com/kantord/SeaGOAT/commit/f96ac470f68a27e5769cace3d3a24dad64b7abc4))

### Unknown

* revert: revert &#34;fix(deps): update dependency chromadb to ^0.4.0&#34;

This reverts commit 5f230cc388085ea248421630a4cd826a3bfb699b. ([`917504a`](https://github.com/kantord/SeaGOAT/commit/917504adc5a7e68777bfb989b9427a34e6dd5a2f))


## v0.6.1 (2023-07-28)

### Fix

* fix(deps): update dependency chromadb to ^0.4.0 ([`5f230cc`](https://github.com/kantord/SeaGOAT/commit/5f230cc388085ea248421630a4cd826a3bfb699b))


## v0.6.0 (2023-07-28)

### Ci

* ci: deploy docs using poetry ([`027f570`](https://github.com/kantord/SeaGOAT/commit/027f570c23e56299dd286ff20061547170cc6ddd))

* ci: fix docs deployment ([`c08ea52`](https://github.com/kantord/SeaGOAT/commit/c08ea52792699b60af0370949173d9b4d664d3ed))

### Documentation

* docs: reuse readme as docs home ([`86cd0ef`](https://github.com/kantord/SeaGOAT/commit/86cd0ef5aefe4dfa8245a6c34cce702f3978e6e3))

* docs: add usage documentation to Readme ([`7cc15fa`](https://github.com/kantord/SeaGOAT/commit/7cc15fa7981da761e85eb5605aafdbfd6492e4cc))

* docs: allow editing documentation files ([`6a08d63`](https://github.com/kantord/SeaGOAT/commit/6a08d636c3205213eda3b37cdc38a503befe72ee))

* docs: set up repo_url ([`2202f16`](https://github.com/kantord/SeaGOAT/commit/2202f16a1e5ec91e64c8334fc5ecf8c95a612708))

* docs: add favicon ([`7e4dd52`](https://github.com/kantord/SeaGOAT/commit/7e4dd52a118c1e4dbd4c82dac9f53c99e591eb87))

### Feature

* feat: add --version option to cli ([`6bf15c9`](https://github.com/kantord/SeaGOAT/commit/6bf15c970811e2cd7a18a9752326ba898073d89b))


## v0.5.6 (2023-07-28)

### Chore

* chore(deps): update dependency mkdocs-material to v9.1.21 ([`8e18e00`](https://github.com/kantord/SeaGOAT/commit/8e18e009141c34591b19a365ffb1e33c23d4a38e))

* chore(deps): update dependency mkdocs-material to v9.1.20 ([`ae794b6`](https://github.com/kantord/SeaGOAT/commit/ae794b6863c96aa92633adeadf7db63b0ac99d35))

* chore(deps): update python-semantic-release/python-semantic-release action to v8.0.4 ([`cbb8b22`](https://github.com/kantord/SeaGOAT/commit/cbb8b22d2282647c039417c7ee4fbdb042d1bcb4))

* chore(deps): update dependency pylint to v2.17.5 ([`5a7e4b7`](https://github.com/kantord/SeaGOAT/commit/5a7e4b7b8936a2f0cab714bf021e6375b0c2edf7))

### Ci

* ci: set up github pages deployment ([`7939a35`](https://github.com/kantord/SeaGOAT/commit/7939a357cc9468aef87f628ced6e84b8301edcf5))

### Documentation

* docs: add minimal documentation using mkdocs ([`d98b065`](https://github.com/kantord/SeaGOAT/commit/d98b06550c914290213fe0ff66a3ebec5ad28f2c))

### Fix

* fix(deps): update dependency nest-asyncio to v1.5.7 ([`e292bbe`](https://github.com/kantord/SeaGOAT/commit/e292bbe25b865af707bbb5b200253b9ed4329cdb))


## v0.5.5 (2023-07-23)

### Chore

* chore(deps): update actions/setup-python action to v4 ([`25d9223`](https://github.com/kantord/SeaGOAT/commit/25d9223138a31e1924200a10934da31215ef1882))

* chore(deps): update actions/checkout action to v3 ([`44f74f3`](https://github.com/kantord/SeaGOAT/commit/44f74f3ac7bda530abd3b0961923bf665949be30))

* chore(deps): update python-semantic-release/python-semantic-release action to v8.0.3 ([`8e14cb6`](https://github.com/kantord/SeaGOAT/commit/8e14cb67acd131ae65c23b3a6d31cf09bf1ac895))

* chore: enable automatically merging dependency updates ([`11c6b91`](https://github.com/kantord/SeaGOAT/commit/11c6b91e7e0fbf30d45ab5a3dd479f405b1ccfb5))

* chore(deps): update dependency pyright to v1.1.318 (#39)

Co-authored-by: renovate[bot] &lt;29139614+renovate[bot]@users.noreply.github.com&gt; ([`aaabd65`](https://github.com/kantord/SeaGOAT/commit/aaabd65c4ce9a301b1ba5e752c2a06741a905126))

* chore(deps): update python-semantic-release/python-semantic-release action to v8.0.2 (#37)

Co-authored-by: renovate[bot] &lt;29139614+renovate[bot]@users.noreply.github.com&gt; ([`fe7e39b`](https://github.com/kantord/SeaGOAT/commit/fe7e39b2a9d08d1c4f335653b88b77ba7a03f05e))

* chore(deps): update dependency syrupy to v4.0.8 (#36)

Co-authored-by: renovate[bot] &lt;29139614+renovate[bot]@users.noreply.github.com&gt; ([`b1eab92`](https://github.com/kantord/SeaGOAT/commit/b1eab92cfa7d04caa20942684562a1ab59a42f52))

### Fix

* fix: print result lines when color is disabled (#18) ([`fc95cf7`](https://github.com/kantord/SeaGOAT/commit/fc95cf76f1dcde9222d08c0b1cb0a0c5b6529179))

### Unknown

* Add renovate.json (#35)

Co-authored-by: renovate[bot] &lt;29139614+renovate[bot]@users.noreply.github.com&gt; ([`376e723`](https://github.com/kantord/SeaGOAT/commit/376e7237b19bb9b2db356b7964283cdeabea2726))


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
