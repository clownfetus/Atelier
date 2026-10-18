"""4x upscaling for browsing artwork only (hero stories and nameplates). Never touches import or export.

Runs Real-ESRGAN's compact anime model (realesr-animevideov3, BSD-3-Clause; provenance in
models/README.md) on the CPU with numpy alone, so it adds no runtime dependency. The model suits
the banners' inked comic style: it redraws edges crisply where a resampling filter blurs them.
"""
from pathlib import Path
import threading

import numpy as np
from PIL import Image

MODEL = Path(__file__).with_name('models') / 'realesr-animevideov3.npz'
SCALE = 4
MAX_PIXELS = 512 * 512  # Fits 344x120 stories and 848x192 nameplates; larger artwork is refused.

_weights = None
_lock = threading.Lock()  # One at a time: each pass already keeps every BLAS thread busy.


def _model():
    global _weights
    if _weights is None:
        with np.load(MODEL) as data:
            _weights = {key: data[key].astype(np.float32) for key in data.files}
    return _weights


def _conv(x, weight, bias):
    """3x3 convolution with padding 1, as nine shifted matrix products (no im2col buffer)."""
    channels, height, width = x.shape
    padded = np.pad(x, ((0, 0), (1, 1), (1, 1)))
    out = np.empty((weight.shape[0], height * width), np.float32)
    out[:] = bias[:, None]
    for dy in range(3):
        for dx in range(3):
            out += weight[:, :, dy, dx] @ padded[:, dy:dy + height, dx:dx + width].reshape(channels, -1)
    return out.reshape(-1, height, width)


def _prelu(x, slope):
    return np.where(x >= 0, x, x * slope[:, None, None])


def _rgb(rgb):
    """SRVGGNetCompact: conv 3->64, 16 x (conv 64->64 + PReLU), conv 64->48, pixel shuffle, plus
    the nearest-upsampled input."""
    w = _model()
    x = rgb.transpose(2, 0, 1).astype(np.float32) / 255
    y = _prelu(_conv(x, w['body.0.weight'], w['body.0.bias']), w['body.1.weight'])
    for i in range(2, 34, 2):
        y = _prelu(_conv(y, w[f'body.{i}.weight'], w[f'body.{i}.bias']), w[f'body.{i + 1}.weight'])
    y = _conv(y, w['body.34.weight'], w['body.34.bias'])
    _, height, width = x.shape
    y = y.reshape(3, SCALE, SCALE, height, width).transpose(0, 3, 1, 4, 2).reshape(3, height * SCALE, width * SCALE)
    y += x.repeat(SCALE, 1).repeat(SCALE, 2)
    return (np.clip(y, 0, 1).transpose(1, 2, 0) * 255 + .5).astype(np.uint8)


def upscale(image):
    """Return `image` at 4x as RGBA. Colour goes through the model; alpha, which is only a soft
    edge on these banners, is resampled."""
    image = image.convert('RGBA')
    if image.width * image.height > MAX_PIXELS:
        raise ValueError('Image too large to upscale')
    pixels = np.asarray(image)
    with _lock:
        rgb = _rgb(pixels[..., :3])
    size = (image.width * SCALE, image.height * SCALE)
    alpha = image.getchannel('A').resize(size, Image.Resampling.LANCZOS)
    result = Image.fromarray(rgb, 'RGB')
    result.putalpha(alpha)
    return result
