"""Typed resume schema: dataclasses for every candidate-data section.

Shape and field names follow the approved design (schema-design.md §1). Field
names match the spellings that appear in real ``data.json`` files; alternate
historical spellings (``text|line|name``, ``name|title|label``) are reconciled
in :meth:`from_dict`, never by the field names themselves.

Round-trip contract
-------------------
``Resume.from_dict(d).to_dict() == d`` key-for-key, including key order, for
any dict whose sections are already in their canonical shape.

It is deliberately NOT the identity for input that is malformed or in a legacy
shape. ``from_dict`` normalizes those on the way in, and the normalized form is
what ``to_dict`` emits -- these are one-directional upgrades, not losses:

* a scalar ``summary`` becomes a single-item list;
* ``bullets`` given as ``list[str]`` become ``PriorityItem`` entries;
* a section given as ``None`` becomes ``[]`` (typed list sections only --
  the deliberately-untyped ``skills``/``teaching``/``contact`` pass ``None``
  through unchanged);
* a section of the wrong type becomes ``[]`` with a warning, and a non-dict
  list item degrades to an item with default values.

Each is idempotent: re-reading the emitted document yields the same document,
so a save never drifts further. Callers needing a byte-exact echo of arbitrary
input must not rely on this method for that.

Two mechanisms make the canonical-shape case exact rather than approximate:

``extra``
    Unknown keys -- at the top level and inside every nested item -- are kept
    verbatim in an ``extra`` dict and re-emitted in their original position.
    Dropping them would silently discard user data.

``_present``
    The set of *declared* fields that were actually present in the input.
    Dataclass defaults would otherwise invent keys on output that the input
    never had (real data has ``skills_groups`` items both with and without
    ``priority``), and coercion would rewrite values that were legitimately
    another type (``presentations[].year`` is an ``int`` in real data while
    the renderers stringify it at display time). Absent stays absent, and a
    present value is stored exactly as given.

Validation is **advisory**: shape violations are reported through
``logging.getLogger(__name__).warning`` and never raise. A malformed input
still yields a usable object.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar

__all__ = [
    "CandidateData",
    # Exported because the render path dispatches on it: the section renderers
    # need "is this a schema item or a raw dict?" to tell typed sections apart
    # from the deliberately-untyped ``teaching``.
    "_Item",
    "PriorityItem",
    "SkillGroupItem",
    "SkillGroup",
    "NamedLevelItem",
    "NamedDescItem",
    "CourseworkItem",
    "CertificationItem",
    "Education",
    "Presentation",
    "ExperienceEntry",
    "Resume",
]

_logger = logging.getLogger(__name__)

# Type alias for the unified candidate/resume data dictionary produced by
# merge_profiles() and consumed by pipeline, summarizer, and renderer stages.
CandidateData = dict[str, Any]

# Alternate historical spellings, reconciled at from_dict time rather than by
# field names. Order matters: the first key present in the input wins.
_TEXT_KEYS = ("text", "line", "name")
_NAME_KEYS = ("name", "title", "label")

# Section-specific name spellings. The DOCX renderers accept a domain-specific
# key per section (docx_sections_simple.py), and each tuple below mirrors that
# renderer's own ``name_keys`` for the section, extended with ``label`` for
# consistency with _NAME_KEYS. They are deliberately NOT folded into
# _NAME_KEYS: that would make "language" a valid name for a skills-group item,
# and would let a certification be named by "course".
_LANGUAGE_NAME_KEYS = ("name", "language", "title", "label")
_COURSEWORK_NAME_KEYS = ("name", "course", "title", "label")
_CERTIFICATION_NAME_KEYS = ("name", "title", "label", "cert")

# Marker prefix recording which alternate spelling a field arrived under, so
# to_dict can replay the original key rather than the canonical one.
_ALIAS_MARK = "@"

# Recorded in a summary item's ``_present`` when the whole ``summary`` arrived
# as a bare string. Shares the ``_ALIAS_MARK`` prefix, so the generic to_dict
# never mistakes it for a declared field: only declared names are emitted.
_SCALAR_SUMMARY = f"{_ALIAS_MARK}scalar_summary"


def _warn(msg: str, *args: Any) -> None:
    """Report an advisory shape violation. Never raises."""
    _logger.warning(msg, *args)


@dataclass
class _Item:
    """Base for every schema dataclass: exact round-trip bookkeeping.

    Subclasses declare their fields normally. This base supplies the shared
    ``extra``/``_present`` machinery plus generic ``from_dict``/``to_dict``.
    """

    #: Unknown keys preserved verbatim.
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    #: Declared field names present in the source dict, plus alias markers.
    _present: set[str] = field(default_factory=set, repr=False, compare=False)
    #: Input key order, replayed by to_dict so a save does not reshuffle the file.
    _order: list[str] = field(default_factory=list, repr=False, compare=False)

    #: Field names that are bookkeeping, not part of the on-disk shape.
    _INTERNAL: ClassVar[frozenset[str]] = frozenset({"extra", "_present", "_order"})
    #: Alternate input spellings, keyed by canonical field name.
    _ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {}

    @classmethod
    def _declared(cls) -> list[str]:
        """Field names that participate in the on-disk shape."""
        return [f.name for f in fields(cls) if f.name not in cls._INTERNAL]

    @classmethod
    def _primary_field(cls) -> str:
        """The field a bare string maps onto. Subclasses override as needed."""
        declared = cls._declared()
        return declared[0] if declared else ""

    @classmethod
    def _convert(cls, name: str, value: Any) -> Any:
        """Hook for per-field conversion of nested structures."""
        return value

    @classmethod
    def from_dict(cls, data: Any) -> Any:
        """Build an instance from a raw dict, preserving unknown keys.

        A non-dict input is tolerated: a bare string is read as the item's
        primary text field, anything else warns and yields defaults.
        """
        if not isinstance(data, dict):
            return cls._from_scalar(data)

        kwargs: dict[str, Any] = {}
        present: set[str] = set()
        consumed: set[str] = set()

        for name in cls._declared():
            key = cls._match_key(data, name)
            if key is None:
                continue
            kwargs[name] = cls._convert(name, data[key])
            present.add(name)
            consumed.add(key)
            if key != name:
                present.add(f"{_ALIAS_MARK}{name}={key}")

        extra = {k: v for k, v in data.items() if k not in consumed}
        return cls(extra=extra, _present=present, _order=list(data), **kwargs)

    @classmethod
    def _match_key(cls, data: dict[str, Any], name: str) -> str | None:
        """The input key supplying ``name``, honouring alternate spellings."""
        for key in cls._ALIASES.get(name, (name,)):
            if key in data:
                return key
        return None

    @classmethod
    def _from_scalar(cls, data: Any) -> Any:
        """Coerce a non-dict input into this item type, advisory-warning."""
        primary = cls._primary_field()
        if isinstance(data, str) and primary:
            return cls(_present={primary}, **{primary: data})
        if data is not None:
            _warn(
                "%s: expected dict, got %s; using defaults",
                cls.__name__,
                type(data).__name__,
            )
        return cls()

    def to_dict(self) -> dict[str, Any]:
        """Inverse of :meth:`from_dict`, key-for-key and in input key order.

        Order is preserved because these documents are saved back as JSON/YAML;
        emitting declaration order instead would reshuffle a hand-maintained
        file and turn a no-op save into a whole-file diff.
        """
        emitted = {
            self._replayed_key(name): _emit(getattr(self, name))
            for name in self._declared()
            if name in self._present
        }
        emitted.update(self.extra)

        out = {key: emitted.pop(key) for key in self._order if key in emitted}
        # Fields set after construction have no recorded position; append them.
        out.update(emitted)
        return out

    def _replayed_key(self, name: str) -> str:
        """The original input spelling for a canonical field name."""
        prefix = f"{_ALIAS_MARK}{name}="
        for marker in self._present:
            if marker.startswith(prefix):
                return marker[len(prefix) :]
        return name


def _emit(value: Any) -> Any:
    """Recursively convert nested schema objects back to plain data."""
    if isinstance(value, _Item):
        return value.to_dict()
    if isinstance(value, list):
        return [_emit(v) for v in value]
    return value


def _as_items(value: Any, cls: type[_Item], label: str) -> list[Any]:
    """Convert a raw list into typed items, advisory-warning on a non-list.

    Bare strings are upgraded into items via ``_from_scalar`` -- this is the
    legacy ``bullets: list[str]`` path.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        _warn("%s: expected list, got %s; ignoring", label, type(value).__name__)
        return []
    return [cls.from_dict(v) for v in value]


@dataclass
class PriorityItem(_Item):
    """Summary items, experience bullets, interests."""

    text: str = ""
    priority: float = 1.0
    desc: str = ""

    _ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {"text": _TEXT_KEYS}

    @classmethod
    def _primary_field(cls) -> str:
        return "text"


@dataclass
class SkillGroupItem(_Item):
    """An entry inside a skills group, or a ``technologies`` entry.

    Primary display key is ``name``, not ``text`` -- the skills renderers key
    on ``name|title|label`` and never on ``text``.
    """

    name: str = ""
    desc: str = ""
    priority: float = 1.0

    _ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {"name": _NAME_KEYS}

    @classmethod
    def _primary_field(cls) -> str:
        return "name"


@dataclass
class SkillGroup(_Item):
    """A titled group of skill items."""

    title: str = ""
    items: list[SkillGroupItem] = field(default_factory=list)

    @classmethod
    def _primary_field(cls) -> str:
        return "title"

    @classmethod
    def _convert(cls, name: str, value: Any) -> Any:
        if name == "items":
            return _as_items(value, SkillGroupItem, "SkillGroup.items")
        return value


@dataclass
class NamedLevelItem(_Item):
    """A ``languages`` entry.

    Accepts ``language`` as a name spelling, matching
    ``LanguagesSectionRenderer``. Without it a ``{"language": "Spanish"}``
    entry resolves to an empty ``name`` and renders as nothing.
    """

    name: str = ""
    level: str = ""

    _ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {"name": _LANGUAGE_NAME_KEYS}


@dataclass
class NamedDescItem(_Item):
    """Base for the ``name``/``desc`` sections.

    Subclassed rather than used directly for ``coursework`` and
    ``certifications``, because those two renderers accept *disjoint* domain
    keys. It remains the declared type of both sections' items, so an
    ``isinstance`` check against it still matches either.
    """

    name: str = ""
    desc: str = ""

    _ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {"name": _NAME_KEYS}


@dataclass
class CourseworkItem(NamedDescItem):
    """A ``coursework`` entry.

    Accepts ``course``, matching ``CourseworkSectionRenderer``. Kept distinct
    from :class:`CertificationItem` because a single shared tuple would invent
    aliases neither renderer honours: coursework never accepts ``cert``, and
    certifications never accept ``course``.
    """

    _ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {"name": _COURSEWORK_NAME_KEYS}


@dataclass
class CertificationItem(NamedDescItem):
    """A ``certifications`` entry.

    Accepts ``cert``, matching ``CertificationsSectionRenderer``.

    Declares ``year`` because that renderer reads it as the entry's
    description (``desc_key="year"`` in docx_sections_simple.py). Left
    undeclared it survived only in ``extra``, which round-tripped fine but read
    back as an empty attribute -- so a typed render path would drop the year
    from every certification while still rendering the name. Like
    ``Presentation.year`` it is annotated ``str`` and stored uncoerced, so real
    data's integer years are emitted unchanged.
    """

    year: str = ""

    _ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {"name": _CERTIFICATION_NAME_KEYS}


@dataclass
class Education(_Item):
    """An education entry."""

    degree: str = ""
    institution: str = ""
    year: str = ""


@dataclass
class Presentation(_Item):
    """A talk or publication.

    Superset of both renderers' field sets: ``authors``/``note`` are sidebar
    only, ``link`` is standard-renderer only. Neither field set loses.

    ``title`` accepts ``name`` because ``PresentationsSectionRenderer`` reads
    ``title`` or ``name`` (docx_sections_simple.py). Without the alias a
    ``{"name": ...}`` presentation resolves to an empty ``title`` and renders
    as nothing once the render path reads attributes -- the same silent-loss
    case the language/course/cert spellings were added to close.
    """

    title: str = ""
    event: str = ""
    year: str = ""
    authors: str = ""
    note: str = ""
    link: str = ""
    priority: float = 1.0

    _ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {"title": ("title", "name")}


@dataclass
class ExperienceEntry(_Item):
    """One position. Flat by design -- no ``roles`` nesting, no ``group_id``."""

    title: str = ""
    company: str = ""
    start: str = ""
    end: str = ""
    location: str = ""
    priority: float = 1.0
    bullets: list[PriorityItem] = field(default_factory=list)

    @classmethod
    def _convert(cls, name: str, value: Any) -> Any:
        if name == "bullets":
            return _as_items(value, PriorityItem, "ExperienceEntry.bullets")
        return value


#: Contact keys promoted to top-level scalars. ``name`` is included, fixing the
#: audited asymmetry where only email/phone/location were promoted.
_CONTACT_PROMOTED = ("name", "email", "phone", "location")

#: Element type for each typed list section of Resume.
_LIST_ITEM_TYPES: dict[str, type[_Item]] = {
    "summary": PriorityItem,
    "interests": PriorityItem,
    "skills_groups": SkillGroup,
    "experience": ExperienceEntry,
    "presentations": Presentation,
    "technologies": SkillGroupItem,
    "languages": NamedLevelItem,
    "coursework": CourseworkItem,
    "certifications": CertificationItem,
    "education": Education,
}


def _as_summary(value: Any) -> list[PriorityItem]:
    """Normalize ``summary`` into a list of items.

    A scalar string is **not** converted. It is stored as a single item so the
    typed API is uniform, but ``_SCALAR_SUMMARY`` records the original shape and
    ``to_dict`` replays the bare string, because the conversion is observable
    and lossy:

    * it does not round-trip -- a scalar and a one-item list both emitted
      ``[{"text": ...}]``, so a save rewrote the user's file; and
    * it silently changes rendering. ``SummarySectionRenderer`` routes a scalar
      summary to a prose paragraph and a list to bullets, and the bullet path
      strips the terminal period. Converting the shape moved a scalar summary
      onto the bullet path, dropping the period from rendered output.

    Scalar summaries are ordinary parser output (``parsing_linkedin`` and
    ``parsing_experience_pdf`` both emit one), not a legacy shape, so this path
    is mainstream rather than a compatibility fallback.
    """
    if isinstance(value, str):
        return [PriorityItem(text=value, _present={"text", _SCALAR_SUMMARY})]
    return _as_items(value, PriorityItem, "Resume.summary")


@dataclass
class Resume(_Item):
    """The full candidate-data document."""

    # scalar identity
    name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""

    # optional-input-only contact-derived scalars
    website: str = ""
    linkedin: str = ""
    github: str = ""
    links: list[str] = field(default_factory=list)

    # priority-scored content
    summary: list[PriorityItem] = field(default_factory=list)
    skills_groups: list[SkillGroup] = field(default_factory=list)
    experience: list[ExperienceEntry] = field(default_factory=list)
    interests: list[PriorityItem] = field(default_factory=list)
    presentations: list[Presentation] = field(default_factory=list)

    # priority-filterable, empty in current production data
    technologies: list[SkillGroupItem] = field(default_factory=list)
    languages: list[NamedLevelItem] = field(default_factory=list)
    coursework: list[CourseworkItem] = field(default_factory=list)
    certifications: list[CertificationItem] = field(default_factory=list)

    education: list[Education] = field(default_factory=list)

    # deliberately untyped (schema-design.md §1)
    skills: list[str] = field(default_factory=list)
    teaching: list[Any] = field(default_factory=list)
    contact: dict[str, Any] | None = None

    @classmethod
    def _convert(cls, name: str, value: Any) -> Any:
        if name == "summary":
            return _as_summary(value)
        item_cls = _LIST_ITEM_TYPES.get(name)
        if item_cls is not None:
            return _as_items(value, item_cls, f"Resume.{name}")
        return value

    @classmethod
    def from_dict(cls, data: Any) -> Resume:
        """Build a Resume from raw candidate data.

        Beyond the generic behaviour, this applies two one-directional legacy
        upgrades and one bugfix:

        * a scalar-string ``summary`` becomes a single-item list;
        * ``bullets`` given as ``list[str]`` become items with ``priority=1.0``;
        * ``contact`` values for name/email/phone/location are promoted to the
          matching top-level scalar when that scalar is not already set.

        Validation is advisory throughout: nothing here raises.
        """
        if not isinstance(data, dict):
            _warn("Resume: expected dict, got %s; using defaults", type(data).__name__)
            return cls()

        resume: Resume = super().from_dict(data)
        resume._promote_contact()
        return resume

    def to_dict(self) -> dict[str, Any]:
        """Inverse of :meth:`from_dict`, replaying a scalar ``summary`` as-is.

        A summary that arrived as a bare string is emitted as that same bare
        string rather than as a one-item list. Emitting the list instead would
        rewrite the user's file on save and would reroute the DOCX renderer from
        its prose branch to its bullet branch; see :func:`_as_summary`.
        """
        out = super().to_dict()
        if self.summary_is_scalar and "summary" in out:
            out["summary"] = self.summary[0].text
        return out

    @property
    def summary_is_scalar(self) -> bool:
        """True when ``summary`` was given as a bare string, not a list.

        Consumers that render a summary need this because normalization makes a
        scalar and a genuine one-item list otherwise indistinguishable, and the
        two render differently.
        """
        return len(self.summary) == 1 and _SCALAR_SUMMARY in self.summary[0]._present

    def _promote_contact(self) -> None:
        """Fill unset identity scalars from a nested ``contact`` dict."""
        if not isinstance(self.contact, dict):
            if self.contact is not None:
                _warn(
                    "Resume.contact: expected dict, got %s",
                    type(self.contact).__name__,
                )
            return
        # Gate on absence, not falsiness: a present-but-falsy top-level key
        # ("name": "") is a value the input genuinely had. Promoting over it
        # would both substitute the value and, via discard(), drop the key
        # from to_dict() -- breaking the round-trip contract.
        for key in _CONTACT_PROMOTED:
            value = self.contact.get(key)
            if value and key not in self._present:
                setattr(self, key, value)
                # A promoted value is derived, not an original top-level key;
                # replaying it would add a key the input never had.
                self._present.discard(key)
        links = self.contact.get("links")
        if isinstance(links, list) and "links" not in self._present:
            self.links = links
            self._present.discard("links")
