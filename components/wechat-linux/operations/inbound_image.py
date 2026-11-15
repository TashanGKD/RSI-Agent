"""Select and read an inbound image within the original operation lease."""

import hashlib
import time

from image_client import ImageFilenameMismatch, ImageSceneChanged


class UnresolvedImage(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def capture(frame, candidates, export, recover, verify_windows):
    """A pixel change invalidates coordinates, not the native source ID."""
    attempted = set()
    for _ in range(5):
        verify_windows()
        image, signature = frame()
        points = candidates(image)
        if not points:
            time.sleep(0.12)
            continue
        for point in points:
            key = signature, tuple(point)
            if key in attempted:
                continue
            verify_windows()
            if frame()[1] != signature:
                break
            if len(attempted) == 3:
                raise UnresolvedImage('IMAGE_SOURCE_MISMATCH', 'No bounded candidate matched this image.')
            try:
                result = export(point, signature)
            except ImageSceneChanged:
                # The adapter detected the change before opening a viewer.
                break
            except ValueError as error:
                if not isinstance(error, ImageFilenameMismatch) and not recover(error):
                    raise
                verify_windows()
                attempted.add(key)
            else:
                verify_windows()
                return result
        else:
            if frame()[1] == signature:
                raise UnresolvedImage('IMAGE_SOURCE_MISMATCH', 'No visible candidate matched this image.')
        time.sleep(0.12)
    raise UnresolvedImage('IMAGE_CONTEXT_CHANGED', 'No stable image location within the read budget.')


def screenshot(frame, pane):
    return frame, hashlib.sha256(frame.crop(tuple(pane)).tobytes()).hexdigest()
