"""Inspect the private owner action ledger without executing anything."""
from trigger import owner_actions


def review(db_path, show_output=False, now=None):
    return owner_actions.review(db_path, show_output=show_output, now=now)