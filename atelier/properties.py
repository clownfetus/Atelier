"""Small edit helpers for UAssetAPI's unversioned property metadata."""


def mark_changed(owner, prop):
    """Rebuild an owning header when a formerly omitted zero needs bytes.

    Keep nested untouched headers: discarding those can change enum/property
    layouts in the bundled native serializer.
    """
    if prop.get("IsZero"):
        owner["OriginalStructHeader"] = None
    prop["IsZero"] = False
