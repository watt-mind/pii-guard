# The demo image drops the CUDA libraries: 9.6 → 1.9 GB (2026-10-28)

LAB-1308, found during LAB-1192. **The demo image (`pii-guard:demo`, the `ner` extra) was
9.6 GB on arm64 although it runs the NER on the CPU.** The torch wheel locked from PyPI is the
CUDA build on Linux (`2.14.1+cu130`), and it pulls the CUDA libraries with it, on aarch64 too:
15 `nvidia-*` packages (3.3 GB), `triton` (817 MB) and 3 `cuda-*` packages.

- **The fix.** On Linux, torch now comes from the PyTorch CPU index (an explicit
  `[[tool.uv.index]]`, selected in `[tool.uv.sources]` with `sys_platform == 'linux'`). The
  lock holds `2.14.1+cpu` for Linux and the PyPI `2.14.1` for everything else, so macOS keeps
  MPS. The Dockerfile is unchanged: `uv sync --locked` picks the CPU wheel by itself.
- **Same behaviour.** The demo container still masks a fictional name in `/v1/mask` with the
  NER active (and leaves it with `PII_GUARD_NER_FALLBACK=off`). `make audit` and
  `make licences` pass.

Measured with `docker image ls` on an M1 Max (arm64), `docker compose --profile demo build`
(`PII_GUARD_EXTRAS="ocr local-vision ner"`), `develop` before and after:

| | before | after |
| -- | -- | -- |
| `pii-guard:demo`, disk usage | 9.62 GB | 1.9 GB (−80 %) |
| content size | 3.42 GB | 424 MB |
| `/app/.venv` (`du`) | 5.6 GB | 1.2 GB |
| `nvidia-*` / `triton` / `cuda-*` packages | 19 | 0 |

`pii-guard:dev` has no torch and doesn't change (654 MB). Details:
[operations](../operations.md#docker).

- **Cost:** $0.
