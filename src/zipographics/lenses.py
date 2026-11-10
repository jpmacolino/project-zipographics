"""Lenses and presets as data (SPEC §5.5, Appendix D). Counsel/owner-editable thresholds.

A lens decides which KPI cards lead, which charts show, which table columns are visible first and
which presets are offered. Restricted mode allows only the Context lens and no presets (§5.7); the
library enforces that here, not only in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from zipographics.errors import RestrictedUseError
from zipographics.models import Rule, UsePolicy
from zipographics.restricted import is_restricted, require_unrestricted

__all__ = [
    "CORE_CHARTS",
    "CORE_KPIS",
    "LENSES",
    "MORE_DEMOGRAPHICS_CHARTS",
    "PRESETS",
    "Lens",
    "Preset",
    "RestrictedUseError",
    "available",
    "get",
    "preset",
    "presets_for",
    "resolve",
]

#: Always-first KPI cards (SPEC §5.5): households, population, median household income, % owners,
#: % households with children.
CORE_KPIS: tuple[str, ...] = ("hh", "pop", "median_hh_income", "owner", "hh_kids")
#: Always-shown charts: income distribution, age, owner vs renter, housing age.
CORE_CHARTS: tuple[str, ...] = ("income", "age", "tenure", "housing_age")
#: The "More demographics" expander (context only; Hispanic origin is a separate Census question).
MORE_DEMOGRAPHICS_CHARTS: tuple[str, ...] = ("race", "hispanic")
#: Table columns every lens shows after Population and Households.
_CORE_COLUMNS: tuple[str, ...] = ("median_hh_income", "owner", "hh_kids")


@dataclass(frozen=True, slots=True)
class Preset:
    name: str
    rules: tuple[Rule, ...]  # combined with AND
    summary: str


@dataclass(frozen=True, slots=True)
class Lens:
    name: str
    kpis: tuple[str, ...]  # lens-specific cards, after the core ones
    charts: tuple[str, ...]  # lens-specific charts, after the core ones
    presets: tuple[str, ...]
    restricted_only: bool = False

    @property
    def core_kpis(self) -> tuple[str, ...]:
        return CORE_KPIS

    @property
    def all_kpis(self) -> tuple[str, ...]:
        """The cards in order: the core five, then this lens's own that are not already shown."""
        return CORE_KPIS + tuple(k for k in self.kpis if k not in CORE_KPIS)

    @property
    def all_charts(self) -> tuple[str, ...]:
        return CORE_CHARTS + self.charts

    @property
    def columns(self) -> tuple[str, ...]:
        """Metric columns of the ranked table shown first (after Population and Households)."""
        out: dict[str, None] = {}
        for mid in (*_CORE_COLUMNS, *self.kpis):
            if mid not in ("pop", "hh"):
                out.setdefault(mid)
        return tuple(out)


def _pct(metric: str, value: float) -> Rule:
    return Rule(metric, ">=", value)


def _idx(metric: str, value: float) -> Rule:
    return Rule(metric, ">=", value, "index")


# fmt: off
PRESETS: dict[str, Preset] = {p.name: p for p in (
    Preset("Home services",
           (_pct("owner", 0.60), _pct("built_pre1980", 0.40), _pct("inc_75p", 0.40)),
           "Homeowners in older housing with a household income of $75k or more"),
    Preset("Affluent homeowners",
           (_pct("owner", 0.70), _idx("median_value", 120)),
           "Mostly owners, with home values well above the benchmark"),
    Preset("New movers", (_idx("new_movers", 120),),
           "More recent movers than the benchmark"),
    Preset("Renters", (_pct("renter", 0.50),), "Half or more of households rent"),
    Preset("Families", (_idx("hh_kids", 115),),
           "More households with children than the benchmark"),
    Preset("Young children", (_idx("age_0_4", 115),),
           "More children under 5 than the benchmark"),
    Preset("Premium", (_pct("inc_150p", 0.25),),
           "A quarter or more of households earn $150k or more"),
    Preset("Young adults", (_idx("age_18_34", 120),),
           "More adults aged 18-34 than the benchmark"),
    Preset("Seniors", (_idx("age_65p", 120),),
           "More people aged 65 and over than the benchmark"),
    Preset("Commuters",
           (_pct("commute_drive_alone", 0.75), _idx("commute_30p", 110)),
           "Mostly drive alone, with longer commutes than the benchmark"),
    Preset("Spanish-language households", (_pct("spanish_home", 0.25),),
           "A quarter or more of people speak Spanish at home"),
)}
# fmt: on

_SPANISH = "Spanish-language households"  # offered in Retail, Restaurants, Health and General


def _lens(
    name: str,
    kpis: tuple[str, ...],
    charts: tuple[str, ...],
    presets: tuple[str, ...],
    restricted_only: bool = False,
) -> Lens:
    return Lens(name, kpis, charts, presets, restricted_only)


# fmt: off
LENSES: tuple[Lens, ...] = (
    _lens("Home services", ("single_family", "built_pre1980", "median_value"),
          ("units_in_structure",), ("Home services", "Affluent homeowners", "New movers")),
    _lens("Lawn & outdoor", ("single_family", "median_value", "inc_100p"),
          ("units_in_structure",), ("Affluent homeowners", "Home services")),
    _lens("Movers", ("new_movers", "renter", "hh"), ("tenure_by_move_in",),
          ("New movers", "Renters")),
    _lens("Restaurants", ("median_age", "age_18_34", "wfh", "commute_drive_alone"),
          ("commute_mode",), ("Young adults", "Families", "Commuters", _SPANISH)),
    _lens("Retail", ("median_age", "inc_75p", "mean_hh_income"), (),
          ("Families", "Premium", "Young adults", _SPANISH)),
    _lens("Auto sales", ("veh_per_hh", "veh_2p", "commute_drive_alone"),
          ("vehicles_available",), ("Commuters", "Premium")),
    _lens("Auto service", ("veh_per_hh", "commute_drive_alone", "commute_30p"),
          ("commute_mode",), ("Commuters",)),
    _lens("Health", ("age_65p", "median_age", "uninsured"), (),
          ("Seniors", "Families", _SPANISH)),
    _lens("Dental", ("hh_kids", "age_5_17", "inc_75p"), (), ("Families", "Premium")),
    _lens("Pets", ("single_family", "inc_75p"), (), ("Affluent homeowners", "Home services")),
    _lens("Fitness", ("age_18_44", "renter", "inc_75p"), (), ("Young adults", "Renters")),
    _lens("Salon", ("median_age", "inc_75p", "hh"), (), ("Premium", "Young adults")),
    _lens("Childcare", ("age_0_4", "working_parents_u6", "hh_kids"), (),
          ("Young children", "Families")),
    _lens("Schools", ("age_5_17", "hh_kids", "inc_100p", "ba_plus"), (),
          ("Families", "Premium")),
    _lens("Higher ed", ("age_18_34", "unemployment", "ba_plus"), ("education",),
          ("Young adults",)),
    _lens("Hospitality", ("age_25_44", "inc_100p", "median_age"), (),
          ("Premium", "Young adults")),
    _lens("B2B", ("wfh", "ba_plus", "lfpr"), ("commute_mode",), ()),
    _lens("General", ("median_age", "mean_hh_income"), (),
          ("Families", "Premium", "Seniors", _SPANISH)),
    _lens("Context", ("units", "vacancy", "renter"), (), (), restricted_only=True),
)
# fmt: on

_BY_NAME: dict[str, Lens] = {lens.name: lens for lens in LENSES}
CONTEXT = _BY_NAME["Context"]


def get(name: str) -> Lens:
    if name not in _BY_NAME:
        raise ValueError(f"Unknown lens: {name!r}")
    return _BY_NAME[name]


def available(policy: UsePolicy | None) -> tuple[Lens, ...]:
    """The lenses the user may switch to. Restricted mode (or no policy: fail closed) allows only
    Context; otherwise every lens except the restricted-only one."""
    if is_restricted(policy):
        return (CONTEXT,)
    return tuple(lens for lens in LENSES if not lens.restricted_only)


def resolve(name: str, policy: UsePolicy | None) -> Lens:
    """The lens to use for a request: Context when restricted, else the one asked for."""
    lens = get(name)
    if is_restricted(policy):
        return CONTEXT
    if lens.restricted_only:
        raise ValueError(f"The {name} lens is for restricted mode only.")
    return lens


def presets_for(lens: str | Lens, policy: UsePolicy | None) -> list[Preset]:
    """The presets a lens offers; none in restricted mode (SPEC §5.7)."""
    if is_restricted(policy):
        return []
    found = lens if isinstance(lens, Lens) else get(lens)
    return [PRESETS[n] for n in found.presets]


def preset(name: str, policy: UsePolicy | None) -> Preset:
    """One preset by name. Raises :class:`RestrictedUseError` in restricted mode."""
    require_unrestricted(policy, "select")
    if name not in PRESETS:
        raise ValueError(f"Unknown preset: {name!r}")
    return PRESETS[name]
