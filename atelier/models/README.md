# Bundled models

## realesr-animevideov3.npz

Real-ESRGAN's compact anime model (SRVGGNetCompact, 4x), used by `atelier/upscale.py` to
upscale the cached hero story banners. BSD 3-Clause, see `LICENSE-Real-ESRGAN.txt`.

- Source: https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth
  (sha256 `b8a8376811077954d82ca3fcf476f1ac3da3e8a68a4f4d71363008000a18b75d`)
- Converted without PyTorch: the `.pth` state dict was read with a restricted unpickler that
  only rebuilds tensors, then stored as float16 in a compressed `.npz`
  (sha256 `725b3de5e535a7c8c4c3cef3dbc4e0dc9bdb795d6bb90a7c8ad050358a9cb475`).
  `upscale.py` widens it to float32 on load.
