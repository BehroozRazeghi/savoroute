"""Image validation and EXIF-free bounded normalization before provider transfer."""

from __future__ import annotations

import base64
import binascii
import io

from savoroute.ai.contracts import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS


class InvalidFoodImage(ValueError):
    """The supplied image cannot be safely accepted."""


def normalize_image(encoded: str) -> bytes:
    """Accept genuine JPEG/PNG/WebP bytes, return bounded EXIF-stripped JPEG."""
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise InvalidFoodImage("Image must be valid base64") from exc
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise InvalidFoodImage("Image exceeds the 4 MB limit or is empty")

    # Pillow is an optional AI feature dependency, not an import-time base requirement.
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError('Install AI dependencies: pip install -e ".[ai]"') from exc

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise InvalidFoodImage("Only JPEG, PNG and WebP photos are supported")
            if image.width < 32 or image.height < 32:
                raise InvalidFoodImage("Image is too small")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise InvalidFoodImage("Image dimensions are too large")
            image = ImageOps.exif_transpose(image)
            # Composite transparent inputs on white before discarding alpha.
            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=78, optimize=True)
            if len(output.getvalue()) > MAX_IMAGE_BYTES:
                raise InvalidFoodImage("Normalized image is too large")
            return output.getvalue()
    except (OSError, ValueError) as exc:
        if isinstance(exc, InvalidFoodImage):
            raise
        raise InvalidFoodImage("Image cannot be decoded safely") from exc
