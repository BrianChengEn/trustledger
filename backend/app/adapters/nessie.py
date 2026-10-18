"""Data owner extension point. No unverified Nessie endpoints are called."""


class NessieNotConfigured(RuntimeError):
    pass


def load_transactions():
    raise NessieNotConfigured("Live Nessie adapter is not implemented; use synthetic adapter.")
