"""Keep HTTPS verification enabled when a stale virtualenv path is configured.

Only replace CA environment variables that point to missing files. Valid custom
certificate bundles are preserved. Uses certifi from the *running interpreter*.
"""
import os
from pathlib import Path
import certifi

CA_VARIABLES = ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE")


def validate_ca_bundle():
    """Repair missing-file CA settings; never set verify=False."""
    bundle = str(Path(certifi.where()).resolve())
    if not Path(bundle).is_file():
        raise FileNotFoundError("The current Python environment has no certifi CA bundle")
    repaired = []
    for name in CA_VARIABLES:
        configured = os.environ.get(name)
        if configured and not Path(configured).is_file():
            os.environ[name] = bundle
            repaired.append(name)
    return repaired
