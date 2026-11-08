"""Open Status Document: read, discover and validate service status pages."""

__version__ = "0.1.0"

from .adapters import detect, from_betterstack, load
from .discover import Discovery, DiscoveryError, discover
from .model import Component, Document, FormatError, Incident, Update, parse
from .validate import Issue, validate_document, validate_http

__all__ = [
    "Component",
    "Discovery",
    "DiscoveryError",
    "Document",
    "FormatError",
    "Incident",
    "Issue",
    "Update",
    "detect",
    "discover",
    "from_betterstack",
    "load",
    "parse",
    "validate_document",
    "validate_http",
]
