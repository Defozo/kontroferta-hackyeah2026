# Third-party resources

DEFOZO SOFTWARE HOUSE | Michał Kiełtyka

No application starter was imported. The project used earlier planning materials, task PDFs and a service catalog. Documents under fixtures/demo and eval/datasets are fictional, authored with AI assistance. AI model/API use is described in AI_USAGE.md.

This inventory records installed package metadata, not a legal license opinion. Original notices remain in installed package distributions and container layers. The software of each dependency remains the work of its respective authors. Versions are locked by uv.lock and package-lock.json.

External executables: Python (PSF license), Node.js (MIT plus bundled notices), Tesseract (Apache-2.0), SQLite (public domain), Chromium (BSD-style with bundled third-party notices), Caddy (Apache-2.0). Debian packages retain the notices under /usr/share/doc in the image. The private Windows SQLite runtime is hash-checked by scripts/bootstrap.py.

Editable presentation tooling: OpenAI Artifact Tool supplied by the authoring environment; not a runtime dependency of the application. PDF slides and screenshots are exports of the authored presentation and running application.

Competition video tooling: locally installed FFmpeg `N-115882-gc5572e329b-g0ae157b360+1` encodes the real browser recording and caption overlays. This installed build reports `--enable-gpl --enable-version3 --enable-nonfree`. Its executable is not included in the source or submission package. Pillow renders Polish captions using the installed Windows Arial and Arial Bold fonts. Font files are not redistributed. No application scene is generated.

Competition narration: ElevenLabs premade voice Bella (`hpp4J3VqNfWAUOO0d1Us`), model `eleven_multilingual_v2`, generated on a verified paid PAYG subscription. No voice was cloned. The provider's [publishing guidance](https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform) permits commercial use of paid-plan output subject to its terms and third-party rights. The presentation materials and their disclosures are available at https://kontroferta.34.116.152.48.sslip.io/materials/.

Competition music: an original instrumental composition synthesized locally by `scripts/mix_submission_audio.py`, with deterministic notes and generated percussion. It uses no external recording or sampled music. The composition source is included in scripts/mix_submission_audio.py.

| Ecosystem | Package | Version | Declared license |
| --- | --- | --- | --- |
| Python | alembic | 1.20.0 | MIT |
| Python | annotated-doc | 0.0.5 | MIT |
| Python | annotated-types | 0.8.0 | MIT |
| Python | anyio | 4.15.1 | MIT |
| Python | Authlib | 1.8.0 | BSD-3-Clause |
| Python | certifi | 2026.7.22 | MPL-2.0 |
| Python | cffi | 2.1.1 | MIT-0 |
| Python | charset-normalizer | 3.5.2 | MIT |
| Python | click | 8.5.0 | BSD-3-Clause |
| Python | colorama | 0.4.6 | License :: OSI Approved :: BSD License |
| Python | cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| Python | distro | 1.9.0 | Apache License, Version 2.0 |
| Python | fastapi | 0.142.2 | MIT |
| Python | google-auth | 2.59.1 | Apache 2.0 |
| Python | google-genai | 2.28.0 | Apache-2.0 |
| Python | greenlet | 3.5.6 | MIT AND PSF-2.0 |
| Python | h11 | 0.16.0 | MIT |
| Python | httpcore | 1.0.9 | BSD-3-Clause |
| Python | httptools | 0.8.0 | MIT |
| Python | httpx | 0.28.1 | BSD-3-Clause |
| Python | hypothesis | 6.168.3 | MPL-2.0 |
| Python | idna | 3.20 | BSD-3-Clause |
| Python | iniconfig | 2.3.0 | MIT |
| Python | itsdangerous | 2.2.0 | License :: OSI Approved :: BSD License |
| Python | Jinja2 | 3.1.6 | License :: OSI Approved :: BSD License |
| Python | joserfc | 1.7.5 | BSD-3-Clause |
| Python | Mako | 1.4.3 | MIT |
| Python | MarkupSafe | 3.0.4 | BSD-3-Clause |
| Python | numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| Python | opentelemetry-api | 1.45.0 | Apache-2.0 |
| Python | packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| Python | pdfminer.six | 20260107 | MIT |
| Python | pdfplumber | 0.11.10 | License :: OSI Approved :: MIT License |
| Python | pillow | 12.3.0 | MIT-CMU |
| Python | playwright | 1.63.0 | Apache-2.0 |
| Python | pluggy | 1.6.0 | MIT |
| Python | pyasn1 | 0.6.4 | BSD-2-Clause |
| Python | pyasn1_modules | 0.4.2 | BSD |
| Python | pycparser | 3.0 | BSD-3-Clause |
| Python | pydantic | 2.13.5 | MIT |
| Python | pydantic_core | 2.46.5 | MIT |
| Python | pyee | 13.0.1 | MIT |
| Python | Pygments | 2.21.0 | BSD-2-Clause |
| Python | pypdfium2 | 5.13.0 | BSD-3-Clause, Apache-2.0, dependency licenses |
| Python | pytesseract | 0.3.13 | Apache License 2.0 |
| Python | pytest | 9.1.1 | MIT |
| Python | pytest-asyncio | 1.4.0 | Apache-2.0 |
| Python | python-dotenv | 1.2.4 | BSD-3-Clause |
| Python | python-multipart | 0.0.32 | Apache-2.0 |
| Python | PyYAML | 6.0.3 | MIT |
| Python | reportlab | 5.0.1 | BSD license (see license.txt for details), Copyright (c) 2000-2025, ReportLab Inc. |
| Python | requests | 2.34.2 | Apache-2.0 |
| Python | ruff | 0.16.10 | MIT |
| Python | sniffio | 1.3.1 | MIT OR Apache-2.0 |
| Python | sortedcontainers | 2.4.0 | Apache 2.0 |
| Python | SQLAlchemy | 2.1.3 | MIT |
| Python | starlette | 1.7.0 | BSD-3-Clause |
| Python | tenacity | 9.1.4 | Apache 2.0 |
| Python | typing-inspection | 0.4.4 | MIT |
| Python | typing_extensions | 4.16.0 | PSF-2.0 |
| Python | tzdata | 2026.5 | Apache-2.0 |
| Python | urllib3 | 2.8.0 | MIT |
| Python | uvicorn | 0.54.0 | BSD-3-Clause |
| Python | watchfiles | 1.3.0 | MIT |
| Python | websockets | 16.1.1 | BSD-3-Clause |
| npm/auth | accepts | 1.3.8 | MIT |
| npm/auth | accepts/node_modules/mime-db | 1.52.0 | MIT |
| npm/auth | accepts/node_modules/mime-types | 2.1.35 | MIT |
| npm/auth | content-disposition | 1.0.1 | MIT |
| npm/auth | content-type | 1.0.5 | MIT |
| npm/auth | cookies | 0.9.2 | MIT |
| npm/auth | debug | 4.4.3 | MIT |
| npm/auth | deep-equal | 1.0.1 | MIT |
| npm/auth | delegates | 1.0.0 | MIT |
| npm/auth | depd | 2.0.0 | MIT |
| npm/auth | destroy | 1.2.0 | MIT |
| npm/auth | ee-first | 1.1.1 | MIT |
| npm/auth | encodeurl | 2.0.0 | MIT |
| npm/auth | escape-html | 1.0.3 | MIT |
| npm/auth | fresh | 0.5.2 | MIT |
| npm/auth | http-assert | 1.5.0 | MIT |
| npm/auth | http-assert/node_modules/depd | 1.1.2 | MIT |
| npm/auth | http-assert/node_modules/http-errors | 1.8.1 | MIT |
| npm/auth | http-assert/node_modules/statuses | 1.5.0 | MIT |
| npm/auth | http-errors | 2.0.1 | MIT |
| npm/auth | inherits | 2.0.4 | ISC |
| npm/auth | jose | 6.2.12 | MIT |
| npm/auth | keygrip | 1.1.0 | MIT |
| npm/auth | koa | 3.2.1 | MIT |
| npm/auth | koa-compose | 4.1.0 | MIT |
| npm/auth | media-typer | 1.1.1 | MIT |
| npm/auth | mime-db | 1.54.0 | MIT |
| npm/auth | mime-types | 3.0.2 | MIT |
| npm/auth | ms | 2.1.3 | MIT |
| npm/auth | negotiator | 0.6.3 | MIT |
| npm/auth | oidc-provider | 9.12.2 | MIT |
| npm/auth | on-finished | 2.4.1 | MIT |
| npm/auth | parseurl | 1.3.3 | MIT |
| npm/auth | setprototypeof | 1.2.0 | ISC |
| npm/auth | statuses | 2.0.2 | MIT |
| npm/auth | toidentifier | 1.0.1 | MIT |
| npm/auth | tsscmp | 1.0.6 | MIT |
| npm/auth | type-is | 2.1.0 | MIT |
| npm/auth | type-is/node_modules/content-type | 2.1.0 | MIT |
| npm/auth | vary | 1.1.2 | MIT |
| npm/verification | playwright | 1.63.0 | Apache-2.0 |
| npm/verification | playwright-core | 1.63.0 | Apache-2.0 |
| npm/web | @babel/code-frame | 7.29.7 | MIT |
| npm/web | @babel/compat-data | 7.29.7 | MIT |
| npm/web | @babel/core | 7.29.7 | MIT |
| npm/web | @babel/generator | 7.29.8 | MIT |
| npm/web | @babel/helper-compilation-targets | 7.29.7 | MIT |
| npm/web | @babel/helper-globals | 7.29.7 | MIT |
| npm/web | @babel/helper-module-imports | 7.29.7 | MIT |
| npm/web | @babel/helper-module-transforms | 7.29.7 | MIT |
| npm/web | @babel/helper-plugin-utils | 7.29.7 | MIT |
| npm/web | @babel/helper-string-parser | 7.29.7 | MIT |
| npm/web | @babel/helper-validator-identifier | 7.29.7 | MIT |
| npm/web | @babel/helper-validator-option | 7.29.7 | MIT |
| npm/web | @babel/helpers | 7.29.7 | MIT |
| npm/web | @babel/parser | 7.29.9 | MIT |
| npm/web | @babel/plugin-transform-react-jsx-self | 7.29.7 | MIT |
| npm/web | @babel/plugin-transform-react-jsx-source | 7.29.7 | MIT |
| npm/web | @babel/template | 7.29.7 | MIT |
| npm/web | @babel/traverse | 7.29.8 | MIT |
| npm/web | @babel/types | 7.29.8 | MIT |
| npm/web | @esbuild/aix-ppc64 | 0.28.2 | MIT |
| npm/web | @esbuild/android-arm | 0.28.2 | MIT |
| npm/web | @esbuild/android-arm64 | 0.28.2 | MIT |
| npm/web | @esbuild/android-x64 | 0.28.2 | MIT |
| npm/web | @esbuild/darwin-arm64 | 0.28.2 | MIT |
| npm/web | @esbuild/darwin-x64 | 0.28.2 | MIT |
| npm/web | @esbuild/freebsd-arm64 | 0.28.2 | MIT |
| npm/web | @esbuild/freebsd-x64 | 0.28.2 | MIT |
| npm/web | @esbuild/linux-arm | 0.28.2 | MIT |
| npm/web | @esbuild/linux-arm64 | 0.28.2 | MIT |
| npm/web | @esbuild/linux-ia32 | 0.28.2 | MIT |
| npm/web | @esbuild/linux-loong64 | 0.28.2 | MIT |
| npm/web | @esbuild/linux-mips64el | 0.28.2 | MIT |
| npm/web | @esbuild/linux-ppc64 | 0.28.2 | MIT |
| npm/web | @esbuild/linux-riscv64 | 0.28.2 | MIT |
| npm/web | @esbuild/linux-s390x | 0.28.2 | MIT |
| npm/web | @esbuild/linux-x64 | 0.28.2 | MIT |
| npm/web | @esbuild/netbsd-arm64 | 0.28.2 | MIT |
| npm/web | @esbuild/netbsd-x64 | 0.28.2 | MIT |
| npm/web | @esbuild/openbsd-arm64 | 0.28.2 | MIT |
| npm/web | @esbuild/openbsd-x64 | 0.28.2 | MIT |
| npm/web | @esbuild/openharmony-arm64 | 0.28.2 | MIT |
| npm/web | @esbuild/sunos-x64 | 0.28.2 | MIT |
| npm/web | @esbuild/win32-arm64 | 0.28.2 | MIT |
| npm/web | @esbuild/win32-ia32 | 0.28.2 | MIT |
| npm/web | @esbuild/win32-x64 | 0.28.2 | MIT |
| npm/web | @hookform/resolvers | 5.2.2 | MIT |
| npm/web | @jridgewell/gen-mapping | 0.3.13 | MIT |
| npm/web | @jridgewell/remapping | 2.3.5 | MIT |
| npm/web | @jridgewell/resolve-uri | 3.1.2 | MIT |
| npm/web | @jridgewell/sourcemap-codec | 1.6.0 | MIT |
| npm/web | @jridgewell/trace-mapping | 0.3.31 | MIT |
| npm/web | @napi-rs/canvas | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-android-arm64 | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-darwin-arm64 | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-darwin-x64 | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-linux-arm-gnueabihf | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-linux-arm64-gnu | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-linux-arm64-musl | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-linux-riscv64-gnu | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-linux-x64-gnu | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-linux-x64-musl | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-win32-arm64-msvc | 0.1.100 | MIT |
| npm/web | @napi-rs/canvas-win32-x64-msvc | 0.1.100 | MIT |
| npm/web | @napi-rs/lzma-linux-x64-gnu | 1.5.1 | MIT |
| npm/web | @radix-ui/primitive | 1.1.3 | MIT |
| npm/web | @radix-ui/react-collection | 1.1.7 | MIT |
| npm/web | @radix-ui/react-compose-refs | 1.1.2 | MIT |
| npm/web | @radix-ui/react-context | 1.1.2 | MIT |
| npm/web | @radix-ui/react-dialog | 1.1.15 | MIT |
| npm/web | @radix-ui/react-direction | 1.1.1 | MIT |
| npm/web | @radix-ui/react-dismissable-layer | 1.1.11 | MIT |
| npm/web | @radix-ui/react-focus-guards | 1.1.3 | MIT |
| npm/web | @radix-ui/react-focus-scope | 1.1.7 | MIT |
| npm/web | @radix-ui/react-id | 1.1.1 | MIT |
| npm/web | @radix-ui/react-portal | 1.1.9 | MIT |
| npm/web | @radix-ui/react-presence | 1.1.5 | MIT |
| npm/web | @radix-ui/react-primitive | 2.1.3 | MIT |
| npm/web | @radix-ui/react-roving-focus | 1.1.11 | MIT |
| npm/web | @radix-ui/react-slot | 1.2.3 | MIT |
| npm/web | @radix-ui/react-tabs | 1.1.13 | MIT |
| npm/web | @radix-ui/react-use-callback-ref | 1.1.1 | MIT |
| npm/web | @radix-ui/react-use-controllable-state | 1.2.2 | MIT |
| npm/web | @radix-ui/react-use-effect-event | 0.0.2 | MIT |
| npm/web | @radix-ui/react-use-escape-keydown | 1.1.1 | MIT |
| npm/web | @radix-ui/react-use-layout-effect | 1.1.1 | MIT |
| npm/web | @redocly/ajv | 8.11.2 | MIT |
| npm/web | @redocly/config | 0.22.0 | MIT |
| npm/web | @redocly/openapi-core | 1.34.20 | MIT |
| npm/web | @rolldown/pluginutils | 1.0.0-rc.3 | MIT |
| npm/web | @rollup/rollup-android-arm-eabi | 4.64.0 | MIT |
| npm/web | @rollup/rollup-android-arm64 | 4.64.0 | MIT |
| npm/web | @rollup/rollup-darwin-arm64 | 4.64.0 | MIT |
| npm/web | @rollup/rollup-darwin-x64 | 4.64.0 | MIT |
| npm/web | @rollup/rollup-freebsd-arm64 | 4.64.0 | MIT |
| npm/web | @rollup/rollup-freebsd-x64 | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-arm-gnueabihf | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-arm-musleabihf | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-arm64-gnu | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-arm64-musl | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-loong64-gnu | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-loong64-musl | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-ppc64-gnu | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-ppc64-musl | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-riscv64-gnu | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-riscv64-musl | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-s390x-gnu | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-x64-gnu | 4.64.0 | MIT |
| npm/web | @rollup/rollup-linux-x64-musl | 4.64.0 | MIT |
| npm/web | @rollup/rollup-openbsd-x64 | 4.64.0 | MIT |
| npm/web | @rollup/rollup-openharmony-arm64 | 4.64.0 | MIT |
| npm/web | @rollup/rollup-win32-arm64-msvc | 4.64.0 | MIT |
| npm/web | @rollup/rollup-win32-ia32-msvc | 4.64.0 | MIT |
| npm/web | @rollup/rollup-win32-x64-gnu | 4.64.0 | MIT |
| npm/web | @rollup/rollup-win32-x64-msvc | 4.64.0 | MIT |
| npm/web | @standard-schema/utils | 0.3.0 | MIT |
| npm/web | @tailwindcss/node | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-android-arm64 | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-darwin-arm64 | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-darwin-x64 | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-freebsd-x64 | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-linux-arm-gnueabihf | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-linux-arm64-gnu | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-linux-arm64-musl | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-linux-x64-gnu | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-linux-x64-musl | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-wasm32-wasi | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-win32-arm64-msvc | 4.2.1 | MIT |
| npm/web | @tailwindcss/oxide-win32-x64-msvc | 4.2.1 | MIT |
| npm/web | @tailwindcss/vite | 4.2.1 | MIT |
| npm/web | @tanstack/query-core | 5.90.20 | MIT |
| npm/web | @tanstack/react-query | 5.90.21 | MIT |
| npm/web | @types/babel__core | 7.20.5 | MIT |
| npm/web | @types/babel__generator | 7.27.0 | MIT |
| npm/web | @types/babel__template | 7.4.4 | MIT |
| npm/web | @types/babel__traverse | 7.28.0 | MIT |
| npm/web | @types/estree | 1.0.9 | MIT |
| npm/web | @types/react | 19.2.14 | MIT |
| npm/web | @types/react-dom | 19.2.3 | MIT |
| npm/web | @vitejs/plugin-react | 5.1.4 | MIT |
| npm/web | agent-base | 7.1.4 | MIT |
| npm/web | ansi-colors | 4.1.3 | MIT |
| npm/web | argparse | 2.0.1 | Python-2.0 |
| npm/web | aria-hidden | 1.2.6 | MIT |
| npm/web | axe-core | 4.11.1 | MPL-2.0 |
| npm/web | balanced-match | 1.0.2 | MIT |
| npm/web | baseline-browser-mapping | 2.11.27 | Apache-2.0 |
| npm/web | brace-expansion | 2.1.7 | MIT |
| npm/web | browserslist | 4.29.3 | MIT |
| npm/web | caniuse-lite | 1.0.30001814 | CC-BY-4.0 |
| npm/web | change-case | 5.4.4 | MIT |
| npm/web | colorette | 1.4.0 | MIT |
| npm/web | convert-source-map | 2.0.0 | MIT |
| npm/web | csstype | 3.2.3 | MIT |
| npm/web | debug | 4.4.3 | MIT |
| npm/web | detect-libc | 2.1.2 | Apache-2.0 |
| npm/web | detect-node-es | 1.1.0 | MIT |
| npm/web | electron-to-chromium | 1.5.444 | ISC |
| npm/web | enhanced-resolve | 5.26.0 | MIT |
| npm/web | esbuild | 0.28.2 | MIT |
| npm/web | escalade | 3.2.0 | MIT |
| npm/web | fast-deep-equal | 3.1.3 | MIT |
| npm/web | fdir | 6.5.0 | MIT |
| npm/web | fsevents | 2.3.3 | MIT |
| npm/web | gensync | 1.0.0-beta.2 | MIT |
| npm/web | get-nonce | 1.0.1 | MIT |
| npm/web | graceful-fs | 4.2.11 | ISC |
| npm/web | https-proxy-agent | 7.0.6 | MIT |
| npm/web | index-to-position | 1.2.0 | MIT |
| npm/web | jiti | 2.7.0 | MIT |
| npm/web | js-levenshtein | 1.1.6 | MIT |
| npm/web | js-tokens | 4.0.0 | MIT |
| npm/web | js-yaml | 4.3.2 | MIT |
| npm/web | jsesc | 3.1.0 | MIT |
| npm/web | json-schema-traverse | 1.0.0 | MIT |
| npm/web | json5 | 2.2.3 | MIT |
| npm/web | lightningcss | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-android-arm64 | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-darwin-arm64 | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-darwin-x64 | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-freebsd-x64 | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-linux-arm-gnueabihf | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-linux-arm64-gnu | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-linux-arm64-musl | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-linux-x64-gnu | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-linux-x64-musl | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-win32-arm64-msvc | 1.31.1 | MPL-2.0 |
| npm/web | lightningcss-win32-x64-msvc | 1.31.1 | MPL-2.0 |
| npm/web | lru-cache | 5.1.1 | ISC |
| npm/web | lucide-react | 0.577.0 | ISC |
| npm/web | magic-string | 0.30.21 | MIT |
| npm/web | minimatch | 5.1.9 | ISC |
| npm/web | ms | 2.1.3 | MIT |
| npm/web | nanoid | 3.3.19 | MIT |
| npm/web | node-readable-to-web-readable-stream | 0.4.2 | MIT |
| npm/web | node-releases | 2.0.57 | MIT |
| npm/web | openapi-typescript | 7.13.0 | MIT |
| npm/web | parse-json | 8.3.0 | MIT |
| npm/web | pdfjs-dist | 5.4.624 | Apache-2.0 |
| npm/web | picocolors | 1.1.1 | ISC |
| npm/web | picomatch | 4.0.7 | MIT |
| npm/web | pluralize | 8.0.0 | MIT |
| npm/web | postcss | 8.5.28 | MIT |
| npm/web | react | 19.2.4 | MIT |
| npm/web | react-dom | 19.2.4 | MIT |
| npm/web | react-hook-form | 7.71.2 | MIT |
| npm/web | react-refresh | 0.18.0 | MIT |
| npm/web | react-remove-scroll | 2.7.2 | MIT |
| npm/web | react-remove-scroll-bar | 2.3.8 | MIT |
| npm/web | react-style-singleton | 2.2.3 | MIT |
| npm/web | require-from-string | 2.0.2 | MIT |
| npm/web | rollup | 4.64.0 | MIT |
| npm/web | scheduler | 0.27.0 | MIT |
| npm/web | semver | 6.3.1 | ISC |
| npm/web | source-map-js | 1.2.2 | BSD-3-Clause |
| npm/web | supports-color | 10.2.2 | MIT |
| npm/web | tailwindcss | 4.2.1 | MIT |
| npm/web | tapable | 2.3.3 | MIT |
| npm/web | tinyglobby | 0.2.17 | MIT |
| npm/web | tslib | 2.8.1 | 0BSD |
| npm/web | type-fest | 4.41.0 | (MIT OR CC0-1.0) |
| npm/web | typescript | 5.9.3 | Apache-2.0 |
| npm/web | update-browserslist-db | 1.3.3 | MIT |
| npm/web | uri-js-replace | 1.0.1 | MIT |
| npm/web | use-callback-ref | 1.3.3 | MIT |
| npm/web | use-sidecar | 1.1.3 | MIT |
| npm/web | vite | 7.3.6 | MIT |
| npm/web | yallist | 3.1.1 | ISC |
| npm/web | yaml-ast-parser | 0.0.43 | Apache-2.0 |
| npm/web | yargs-parser | 21.1.1 | ISC |
| npm/web | zod | 4.3.6 | MIT |
