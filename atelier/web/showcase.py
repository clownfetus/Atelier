"""Encode bounded, in-memory viewport captures without writing project assets."""
from io import BytesIO
import struct
from PIL import Image

MAX_CAPTURE_BYTES = 24 * 1024 * 1024


def capture_frames(stream):
    """ATC1, frame count, then repeated little-endian byte length + encoded image."""
    payload = stream.read(MAX_CAPTURE_BYTES + 1)
    if len(payload) > MAX_CAPTURE_BYTES:
        raise ValueError("Capture exceeds 24 MB")
    if len(payload) < 8 or payload[:4] != b"ATC1":
        raise ValueError("Invalid capture header")
    count = struct.unpack_from("<I", payload, 4)[0]
    if not 2 <= count <= 48:
        raise ValueError("A turntable requires 2 to 48 frames")
    offset, frames = 8, []
    for _ in range(count):
        if offset + 4 > len(payload):
            raise ValueError("Truncated capture")
        length = struct.unpack_from("<I", payload, offset)[0]
        offset += 4
        if not length or offset + length > len(payload):
            raise ValueError("Truncated capture frame")
        frames.append(BytesIO(payload[offset:offset + length]))
        offset += length
    if offset != len(payload):
        raise ValueError("Unexpected data after capture")
    return frames


def encode_turntable(streams):
    if not 2 <= len(streams) <= 48:
        raise ValueError("A turntable requires 2 to 48 frames")
    frames, total, dimensions = [], 0, None
    try:
        for stream in streams:
            payload = stream.read(MAX_CAPTURE_BYTES + 1)
            total += len(payload)
            if total > MAX_CAPTURE_BYTES:
                raise ValueError("Capture exceeds 24 MB")
            with Image.open(BytesIO(payload)) as source:
                if not (1 <= source.width <= 1024 and 1 <= source.height <= 1024):
                    raise ValueError("Capture frames must be at most 1024 by 1024")
                if dimensions is not None and source.size != dimensions:
                    raise ValueError("Capture frames must have equal dimensions")
                dimensions = source.size
                frames.append(source.convert("RGBA"))
        output = BytesIO()
        frames[0].save(output, format="WEBP", save_all=True, append_images=frames[1:],
                       duration=75, loop=0, quality=85, method=4)
        return output.getvalue()
    finally:
        for frame in frames:
            frame.close()
