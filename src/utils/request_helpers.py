"""Shared request helpers."""

from flask import request


def json_body():
    """Return parsed JSON body or empty dict."""
    return request.get_json(silent=True) or {}
