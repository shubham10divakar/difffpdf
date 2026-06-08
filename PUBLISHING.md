# Publishing `difffpdf` to PyPI

Distribution name: **difffpdf** · import package: `pdfdiff` · CLI: `difffpdf` (alias `pdfdiff`).

## 1. One-time accounts & tokens
1. Create accounts at <https://pypi.org> and <https://test.pypi.org>.
2. Enable 2FA, then create an **API token** on each (Account → API tokens).
   Use a token scoped to "Entire account" for the first upload; you can narrow
   it to the project afterwards.

## 2. Build fresh artifacts
```bash
python -m pip install --upgrade build twine
# from the project root:
rm -rf dist build *.egg-info        # PowerShell: Remove-Item -Recurse -Force dist,build,*.egg-info
python -m build                      # writes dist/difffpdf-0.1.0{.tar.gz,-py3-none-any.whl}
python -m twine check dist/*         # must say PASSED for both
```

## 3. Dry run on TestPyPI (recommended first)
```bash
python -m twine upload --repository testpypi dist/*
# username:  __token__
# password:  <your TestPyPI token, including the "pypi-" prefix>
```
Then verify it installs cleanly from TestPyPI:
```bash
python -m pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ difffpdf
difffpdf --help
```
(The extra index lets pip pull real deps like pymupdf, which aren't on TestPyPI.)

## 4. Publish to real PyPI
```bash
python -m twine upload dist/*
# username: __token__   password: <your PyPI token>
```
Install check:
```bash
pip install difffpdf
```

## Tips
- **Avoid typing tokens each time:** put them in `~/.pypirc`, or set
  `TWINE_USERNAME=__token__` and `TWINE_PASSWORD=<token>` in the environment.
- **A version can never be re-uploaded.** To fix anything after publishing, bump
  `version` in `pyproject.toml` (e.g. `0.1.1`) and rebuild.
- Before the first real upload, update the URLs in `pyproject.toml`
  (`[project.urls]`) to your actual repository.
- Trusted Publishing (OIDC from GitHub Actions) is the token-free alternative if
  you later move releases into CI.
