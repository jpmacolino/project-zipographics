"""Client industries, their default lens and restricted flag (SPEC §5.1).

This is data, not UI code, and it is meant to be edited by the agency's counsel: moving an
industry into or out of restricted use is a one-line change here plus its test. The mapping is a
guardrail, not legal advice (see ``restricted.NOT_LEGAL_ADVICE``).
"""

from __future__ import annotations

from dataclasses import dataclass

from zipographics.models import UsePolicy

#: The restricted-use question, worded exactly as in SPEC §5.1.
RESTRICTED_QUESTION = (
    "Will this be used for ads, mailers, or any other marketing for housing, jobs, "
    "credit or financing, or insurance?"
)
#: Shown under a locked (pre-answered) question.
LOCKED_NOTE = "Marketing for this industry always counts as restricted use."
#: One-line hint under the question for industries that are not restricted by default.
QUESTION_HINT = (
    "For example, a car dealer advertising financing, or a restaurant advertising jobs, "
    "should answer Yes."
)

ANSWER_YES = "Yes"
ANSWER_NO = "No"
ANSWER_FORCED = "Yes (set by industry)"


@dataclass(frozen=True, slots=True)
class Vertical:
    name: str
    restricted: bool
    lens: str  # a name in ``lenses.LENSES``; "Context" for every restricted vertical
    note: str | None = None


_FINANCING = "Financing offers: answer Yes."
# fmt: off
VERTICALS: tuple[Vertical, ...] = (
    Vertical("Home services (HVAC, plumbing, roofing, pest, remodeling)", False, "Home services",
             _FINANCING),
    Vertical("Lawn, landscaping & pool", False, "Lawn & outdoor"),
    Vertical("Solar & home energy", False, "Lawn & outdoor",
             "Loans and leases are credit: answer Yes."),
    Vertical("Moving & storage", False, "Movers"),
    Vertical("Restaurants & food service", False, "Restaurants", "Hiring ads: answer Yes."),
    Vertical("Retail (general & specialty)", False, "Retail", "Store credit cards: answer Yes."),
    Vertical("Automotive sales", False, "Auto sales", "Financing or lease ads: answer Yes."),
    Vertical("Auto repair & service", False, "Auto service"),
    Vertical("Medical practices & healthcare", False, "Health"),
    Vertical("Dental & orthodontics", False, "Dental", "Payment plans: answer Yes."),
    Vertical("Veterinary & pet services", False, "Pets"),
    Vertical("Fitness & gyms", False, "Fitness"),
    Vertical("Salon, spa & personal care", False, "Salon"),
    Vertical("Childcare & early education", False, "Childcare"),
    Vertical("Private schools & tutoring", False, "Schools"),
    Vertical("Higher ed & vocational training", False, "Higher ed", "Student loans: answer Yes."),
    Vertical("Legal services", False, "General"),
    Vertical("B2B / professional services", False, "B2B", "Business counts come in a later phase."),
    Vertical("Hospitality, entertainment & events", False, "Hospitality"),
    Vertical("Nonprofit & community organizations", False, "General"),
    Vertical("Real estate (brokerage, rentals, property management)", True, "Context"),
    Vertical("Home builders & developers", True, "Context"),
    Vertical("Senior living (communities are housing)", True, "Context"),
    Vertical("Mortgage & lending", True, "Context"),
    Vertical("Banking & credit unions", True, "Context"),
    Vertical("Insurance", True, "Context"),
    Vertical("Financial planning & investments", True, "Context"),
    Vertical("Staffing & recruiting", True, "Context"),
    Vertical("Other", False, "General", "Decided by the question below."),
)
# fmt: on

BY_NAME: dict[str, Vertical] = {v.name: v for v in VERTICALS}
CONTEXT_LENS = "Context"


def get(name: str | None) -> Vertical:
    """The vertical called ``name``; ``ValueError`` if there is none."""
    if name is None or name not in BY_NAME:
        raise ValueError(f"Unknown industry: {name!r}")
    return BY_NAME[name]


def is_locked(name: str) -> bool:
    """True when the question is pre-answered Yes and cannot be changed."""
    return get(name).restricted


def make_policy(name: str, answer: bool | None) -> UsePolicy:
    """The Step-1 outcome. ``answer`` is the user's Yes (True) / No (False) / unanswered (None).

    A restricted vertical is always restricted, whatever ``answer`` says. Any other vertical needs
    an answer, and Yes turns restricted mode on.
    """
    vertical = get(name)
    if vertical.restricted:
        return UsePolicy(True, vertical.name, ANSWER_FORCED)
    if answer is None:
        raise ValueError(f"An answer to the restricted-use question is required for {name}.")
    return UsePolicy(bool(answer), vertical.name, ANSWER_YES if answer else ANSWER_NO)


def default_lens(policy: UsePolicy) -> str:
    """The lens shown first: Context whenever restricted mode is on, else the vertical's own."""
    if policy.restricted:
        return CONTEXT_LENS
    return get(policy.vertical).lens


def search(text: str) -> list[Vertical]:
    """Verticals whose name contains ``text`` (case-insensitive); all of them for empty text."""
    needle = text.strip().lower()
    return [v for v in VERTICALS if needle in v.name.lower()]
