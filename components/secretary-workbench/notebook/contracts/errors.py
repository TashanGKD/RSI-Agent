"""Shared port failures; no dependency on storage, HTTP, or model libraries."""
class ValidationError(ValueError):
    pass

class ConflictError(ValueError):
    pass
