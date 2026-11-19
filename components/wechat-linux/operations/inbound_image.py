"""Select and read an inbound image within the original operation lease."""

import hashlib
import time

from image_client import ImageFilenameMismatch, ImageSceneChanged


# A busy group can push a delayed image many messages up. Each step scrolls
# less than one pane, so consecutive viewports overlap.
HISTORY_STEPS = 12


class UnresolvedImage(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def capture(frame, candidates, export, recover, verify_windows, seek_older=None):
    """A pixel change invalidates coordinates, not the native source ID."""
    attempted = set()
    attempt_budget = 9 if seek_older else 3
    retries = scrolls = 0
    while retries < 5:
        verify_windows()
        image, signature = frame()
        points = candidates(image)
        for point in points:
            key = signature, tuple(point)
            if key in attempted:
                continue
            verify_windows()
            if frame()[1] != signature:
                break
            if len(attempted) == attempt_budget:
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
                if scrolls < HISTORY_STEPS and seek_older and seek_older(signature):
                    scrolls += 1
                    continue
                if points or attempted:
                    raise UnresolvedImage('IMAGE_SOURCE_MISMATCH', 'No visible candidate matched this image.')
        retries += 1
        time.sleep(0.12)
    raise UnresolvedImage('IMAGE_CONTEXT_CHANGED', 'No stable image location within the read budget.')


def screenshot(frame, pane):
    return frame, hashlib.sha256(frame.crop(tuple(pane)).tobytes()).hexdigest()
