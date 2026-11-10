# Third-party notices

## Redistributed resources

**KaTeX 0.19.1**: MIT, copyright Khan Academy and other contributors.
The project redistributes the unmodified KaTeX renderer (`katex.min.js`), CSS,
and 20 WOFF2 fonts under `src/md2html/vendor/`. The full upstream license is
retained as `src/md2html/vendor/KATEX-LICENSE.txt` and embedded in generated HTML.
Font metadata/terms are those of the upstream KaTeX distribution. Do not remove
these notices when repackaging the project or generated textbooks.

Source: <https://github.com/KaTeX/KaTeX>, <https://katex.org/>.

## Separately installed build/runtime dependencies

Python runtime uses PyYAML (MIT), Jinja2 and MarkupSafe (BSD-3-Clause),
bleach (Apache-2.0) and webencodings (BSD-3-Clause).
Pandoc is a separately executed GPL-2.0-or-later program; its executable is NOT
bundled in this project's wheel/source ZIP. `pypandoc_binary` is an optional
installation dependency with its own bundled Pandoc notices. Node.js and all
its third-party notices belong to the separately installed Node distribution.

pytest, Playwright and their browsers are development/test dependencies, not
reader runtime assets. Their original licenses apply to separately downloaded
packages/binaries. `package-lock.json` may mention npm's commander dependency;
commander is not copied into this project's Python package or generated HTML.

All locally authored sample SVGs and fixture text are provided under the
project MIT license. The implementation-plan copy is user-provided project
input; its inclusion does not claim ownership over the original document.
