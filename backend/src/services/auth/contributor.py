"""Reusable declared attribution, independent of login names and imported ZIPs."""
import hashlib

FIELDS = ("nickname", "organization", "group", "contacts")


def contributor_profile(user):
    uid = str(user.id)
    seed = hashlib.sha256(uid.encode()).digest()
    adjectives = ("crazy", "quiet", "brave", "clever", "swift", "bright", "calm", "wild")
    animals = ("frog", "fox", "owl", "otter", "panda", "raven", "lynx", "badger")
    default = adjectives[seed[0] % len(adjectives)] + "-" + animals[seed[1] % len(animals)]
    saved = (getattr(user, "metadata_", None) or {}).get("contributor", {})
    return {"id": uid, **{key: str(saved.get(key, "")) for key in FIELDS}, "nickname": saved.get("nickname") or default}
