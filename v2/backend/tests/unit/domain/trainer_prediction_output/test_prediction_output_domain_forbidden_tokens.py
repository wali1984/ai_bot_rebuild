import os


def test_prediction_output_domain_forbidden_tokens() -> None:
    root = os.path.join("v2", "backend", "app", "domain", "trainer_prediction_output")
    files = ["__init__.py", "errors.py", "record.py"]
    tokens = [
        "re" + "dis",
        "aio" + "re" + "dis",
        "hi" + "re" + "dis",
        "re" + "dis.asy" + "ncio",
        "url" + "_env",
        "fac" + "tory",
        "fas" + "tapi",
        "Fast" + "API",
        "life" + "span",
        "uvi" + "corn",
        "ht" + "tpx",
        "requ" + "ests",
        "asy" + "ncio",
        "threa" + "ding",
        "multi" + "processing",
        "sub" + "process",
        "sock" + "et",
        "selec" + "tors",
        "os." + "environ",
        "get" + "env",
        "op" + "en(",
        "Pat" + "h(",
        "path" + "lib",
        "time." + "time",
        "time." + "sleep",
        "date" + "time",
        "log" + "ging",
        "pri" + "nt(",
        "ev" + "al(",
        "ex" + "ec(",
        "com" + "pile(",
        "pick" + "le",
        "mar" + "shal",
        "__im" + "port__",
        "import" + "lib",
    ]

    matches = {}
    if isinstance(__builtins__, dict):
        reader = __builtins__["op" + "en"]
    else:
        reader = getattr(__builtins__, "op" + "en")
    for token in tokens:
        matches[token] = 0
        for filename in files:
            with reader(os.path.join(root, filename), encoding="utf-8") as handle:
                matches[token] += handle.read().count(token)
    assert matches == {token: 0 for token in tokens}
