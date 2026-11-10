"""Restricted-mode data and guard (SPEC §5.7, Appendix B). Counsel-editable.

Restricted mode is a guardrail, not legal advice. The tag list documents which characteristics are
protected or act as proxies; enforcement (D4) is stricter: in restricted mode *no* metric may be
used to rank, filter or select ZIPs.
"""

from __future__ import annotations

from zipographics.errors import RestrictedUseError
from zipographics.metrics import Metric
from zipographics.models import UsePolicy
from zipographics.verticals import BY_NAME

__all__ = [
    "AD_PLATFORM_NOTICE",
    "BANNER",
    "BANNER_TITLE",
    "NOT_LEGAL_ADVICE",
    "TAGS",
    "TAG_LABELS",
    "RestrictedUseError",
    "is_restricted",
    "label_of",
    "require_unrestricted",
]

BANNER_TITLE = "Restricted mode is on."
_BANNER_BODY = (
    "You said this will be used to market housing, jobs, credit or financing, or insurance. "
    "Fair-housing, fair-lending and equal-employment rules, and Google and Meta ad policies, "
    "don't allow choosing who sees that kind of marketing based on characteristics like age, "
    "income, family status or national origin, or on stand-ins for them. You can see the profile "
    "as context, but ZIPs can't be ranked, filtered or selected by it, and the ZIP list stays the "
    "one you entered."
)
BANNER = f"{BANNER_TITLE} {_BANNER_BODY}"

AD_PLATFORM_NOTICE = (
    "Google Ads and Meta don't allow ZIP-code targeting for housing, employment, "
    "credit/financial-services ads in the US (Meta also requires at least a 15-mile radius). "
    "Check the platform's current rules before uploading this list."
)

NOT_LEGAL_ADVICE = (
    "Restricted mode is a guardrail, not legal advice. It does not make a campaign compliant. "
    "The agency's counsel should review the industry-to-restricted mapping and the restricted "
    "characteristic list before wide internal use."
)

#: Appendix B: what each tag covers. Every registry metric's ``characteristic`` is one of these
#: keys (or None for totals); a test fails when a metric is added without a tag decision.
TAGS: dict[str, str] = {
    "race_color": "race, color",
    "national_origin": (
        "national origin, ancestry, Hispanic origin, language spoken at home (proxies)"
    ),
    "religion": "religion",
    "sex": "sex, gender identity, sexual orientation",
    "familial_status": "children present, household or family type, children's ages",
    "age": "age",
    "disability": "disability",
    "marital_status": "marital status",
    "public_assistance": "receipt of public assistance income",
    "military": "veteran or military status",
    "genetic": "genetic information",
    "income": "income, poverty and wealth stand-ins (proxy)",
    "proxy_other": (
        "measures that track the above at ZIP level: tenure, home value, rent, education, "
        "vehicles, commuting, internet, new movers, housing age, units in structure"
    ),
}

#: Short labels the UI and exports put next to a metric.
TAG_LABELS: dict[str, str] = {
    "race_color": "Race / color",
    "national_origin": "National origin (incl. language)",
    "religion": "Religion",
    "sex": "Sex",
    "familial_status": "Familial status",
    "age": "Age",
    "disability": "Disability",
    "marital_status": "Marital status",
    "public_assistance": "Public assistance",
    "military": "Veteran / military",
    "genetic": "Genetic information",
    "income": "Income (proxy)",
    "proxy_other": "Proxy for protected characteristics",
}


def label_of(metric: Metric) -> str | None:
    """The characteristic label of a metric, or None for untagged totals."""
    return TAG_LABELS[metric.characteristic] if metric.characteristic else None


def is_restricted(policy: UsePolicy | None, *others: UsePolicy | None) -> bool:
    """True when any given policy is restricted, missing, or names a restricted industry.

    A caller can hold two policies (the ``policy`` argument and the one an Analysis was built
    with) or build ``UsePolicy(False, "Insurance", "No")`` by mistake; the stricter reading wins.
    """
    for p in (policy, *others):
        if p is None or p.restricted:
            return True
        vertical = BY_NAME.get(p.vertical or "")
        if vertical is not None and vertical.restricted:
            return True
    return False


def require_unrestricted(policy: UsePolicy | None, action: str, *others: UsePolicy | None) -> None:
    """Raise :class:`RestrictedUseError` when ``action`` (filter, rank, select...) is not allowed.

    Fails closed: with no policy at all the action is refused, so a caller that forgot to pass
    one cannot select ZIPs by demographics.
    """
    if is_restricted(policy, *others):
        done = {"filter": "filtered", "rank": "ranked", "select": "selected"}.get(action, action)
        raise RestrictedUseError(
            f"Restricted mode is on: ZIPs can't be {done} by demographic characteristics."
        )
