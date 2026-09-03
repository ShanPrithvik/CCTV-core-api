"""Shared serializers for API responses."""


def membership_summary(membership):
    """Serialize a Membership row into the standard API dict."""
    org = membership.organization
    return {
        "id": membership.id,
        "user_id": membership.user_id,
        "organization_id": membership.organization_id,
        "organization_name": org.name if org else None,
        "role": membership.role,
        "status": membership.status,
    }
