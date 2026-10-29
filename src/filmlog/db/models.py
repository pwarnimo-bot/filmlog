# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""SQLAlchemy ORM models (typed 2.x style)."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from filmlog.db.enums import (
    CameraStatus,
    CameraType,
    ChemicalForm,
    ChemicalKind,
    ContrastMethod,
    ContrastType,
    ExposurePurpose,
    FilmFormat,
    FilmType,
    PaperBase,
    PaperSurface,
    PaperTone,
    RollStatus,
)

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def enum_col[E: StrEnum](cls: type[E]) -> SAEnum:
    # Stored as VARCHAR without CHECK constraint so new values need no migration.
    return SAEnum(
        cls,
        native_enum=False,
        create_constraint=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class Timestamped:
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    notes: Mapped[str] = mapped_column(Text, default="")


# --------------------------------------------------------------------------- catalogue


class Manufacturer(Timestamped, Base):
    __tablename__ = "manufacturer"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    country: Mapped[str | None] = mapped_column(String(60))

    film_stocks: Mapped[list[FilmStock]] = relationship(back_populates="manufacturer")
    chemicals: Mapped[list[Chemical]] = relationship(back_populates="manufacturer")
    papers: Mapped[list[Paper]] = relationship(back_populates="manufacturer")

    @property
    def display_name(self) -> str:
        return self.name


class FilmStock(Timestamped, Base):
    __tablename__ = "film_stock"
    __table_args__ = (UniqueConstraint("manufacturer_id", "name", name="manufacturer_name"),)

    manufacturer_id: Mapped[int] = mapped_column(ForeignKey("manufacturer.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    box_iso: Mapped[int] = mapped_column(Integer)
    type: Mapped[FilmType] = mapped_column(enum_col(FilmType), default=FilmType.BW_NEGATIVE)
    formats_available: Mapped[str] = mapped_column(String(200), default="")
    aliases: Mapped[str] = mapped_column(String(200), default="")
    discontinued: Mapped[bool] = mapped_column(default=False)

    manufacturer: Mapped[Manufacturer] = relationship(back_populates="film_stocks")

    @property
    def display_name(self) -> str:
        """ "Ilford FP4 Plus 125"; the ISO is not repeated if the name contains it."""
        iso = str(self.box_iso)
        parts = [self.manufacturer.name if self.manufacturer else "", self.name]
        if iso not in self.name.replace("-", " ").split():
            parts.append(iso)
        return " ".join(p for p in parts if p)


class Chemical(Timestamped, Base):
    __tablename__ = "chemical"
    __table_args__ = (
        UniqueConstraint("manufacturer_id", "name", "kind", name="manufacturer_name_kind"),
    )

    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturer.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    kind: Mapped[ChemicalKind] = mapped_column(enum_col(ChemicalKind), index=True)
    common_dilutions: Mapped[str] = mapped_column(String(200), default="")
    form: Mapped[ChemicalForm] = mapped_column(enum_col(ChemicalForm), default=ChemicalForm.LIQUID)
    discontinued: Mapped[bool] = mapped_column(default=False)
    # Built-in entries (e.g. "Water" as a stop bath) cannot be deleted.
    is_builtin: Mapped[bool] = mapped_column(default=False)

    manufacturer: Mapped[Manufacturer | None] = relationship(back_populates="chemicals")

    @property
    def display_name(self) -> str:
        if self.manufacturer is None:
            return self.name
        return f"{self.manufacturer.name} {self.name}"

    @property
    def dilution_list(self) -> list[str]:
        return [d.strip() for d in self.common_dilutions.split(";") if d.strip()]


class Paper(Timestamped, Base):
    __tablename__ = "paper"
    __table_args__ = (
        UniqueConstraint("manufacturer_id", "name", "surface", name="manufacturer_name_surface"),
    )

    manufacturer_id: Mapped[int] = mapped_column(ForeignKey("manufacturer.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    base: Mapped[PaperBase] = mapped_column(enum_col(PaperBase), default=PaperBase.RC)
    contrast_type: Mapped[ContrastType] = mapped_column(
        enum_col(ContrastType), default=ContrastType.VARIABLE
    )
    grade: Mapped[str | None] = mapped_column(String(8))
    surface: Mapped[PaperSurface] = mapped_column(
        enum_col(PaperSurface), default=PaperSurface.GLOSSY
    )
    tone: Mapped[PaperTone] = mapped_column(enum_col(PaperTone), default=PaperTone.NEUTRAL)
    discontinued: Mapped[bool] = mapped_column(default=False)

    manufacturer: Mapped[Manufacturer] = relationship(back_populates="papers")

    @property
    def display_name(self) -> str:
        mfr = self.manufacturer.name if self.manufacturer else ""
        return f"{mfr} {self.name} ({self.surface.value.replace('_', '-')})".strip()


class AgitationPreset(Timestamped, Base):
    __tablename__ = "agitation_preset"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    text: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def display_name(self) -> str:
        return self.name


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)


roll_tag = Table(
    "roll_tag",
    Base.metadata,
    Column("roll_id", ForeignKey("roll.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
)

development_roll = Table(
    "development_roll",
    Base.metadata,
    Column("development_id", ForeignKey("development.id", ondelete="CASCADE"), primary_key=True),
    Column("roll_id", ForeignKey("roll.id", ondelete="CASCADE"), primary_key=True),
)


# --------------------------------------------------------------------------- cameras


class Camera(Timestamped, Base):
    __tablename__ = "camera"

    make: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(100))
    nickname: Mapped[str] = mapped_column(String(100), default="")
    camera_type: Mapped[CameraType] = mapped_column(enum_col(CameraType), default=CameraType.SLR)
    format: Mapped[FilmFormat] = mapped_column(enum_col(FilmFormat), default=FilmFormat.F135)
    lens_mount: Mapped[str] = mapped_column(String(100), default="")
    lenses: Mapped[str] = mapped_column(Text, default="")
    serial_number: Mapped[str] = mapped_column(String(60), default="")
    year_made: Mapped[int | None] = mapped_column(Integer)
    shutter: Mapped[str] = mapped_column(String(200), default="")
    metering: Mapped[str] = mapped_column(String(200), default="")
    battery: Mapped[str] = mapped_column(String(100), default="")
    acquired_date: Mapped[dt.date | None] = mapped_column(Date)
    acquired_price: Mapped[float | None] = mapped_column(Float)
    status: Mapped[CameraStatus] = mapped_column(
        enum_col(CameraStatus), default=CameraStatus.ACTIVE
    )
    photo: Mapped[str | None] = mapped_column(String(255))
    is_demo: Mapped[bool] = mapped_column(default=False, index=True)

    rolls: Mapped[list[Roll]] = relationship(back_populates="camera")

    @property
    def display_name(self) -> str:
        return self.nickname or f"{self.make} {self.model}".strip()

    @property
    def lens_list(self) -> list[str]:
        raw = self.lenses.replace(";", "\n").replace(",", "\n")
        return [x.strip() for x in raw.splitlines() if x.strip()]


# --------------------------------------------------------------------------- rolls


class Roll(Timestamped, Base):
    __tablename__ = "roll"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    title: Mapped[str] = mapped_column(String(200), default="", index=True)
    film_stock_id: Mapped[int] = mapped_column(ForeignKey("film_stock.id"), index=True)
    format: Mapped[FilmFormat] = mapped_column(enum_col(FilmFormat), default=FilmFormat.F135)
    exposures: Mapped[int | None] = mapped_column(Integer)
    shot_iso: Mapped[int] = mapped_column(Integer)
    push_pull_stops: Mapped[float] = mapped_column(Float, default=0.0)
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("camera.id", ondelete="SET NULL"), index=True
    )
    lens: Mapped[str] = mapped_column(String(200), default="")
    film_expiry: Mapped[dt.date | None] = mapped_column(Date)
    date_loaded: Mapped[dt.date | None] = mapped_column(Date)
    date_finished: Mapped[dt.date | None] = mapped_column(Date)
    subject_location: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[RollStatus] = mapped_column(
        enum_col(RollStatus), default=RollStatus.LOADED, index=True
    )
    contact_sheet_image: Mapped[str | None] = mapped_column(String(255))
    is_demo: Mapped[bool] = mapped_column(default=False, index=True)

    film_stock: Mapped[FilmStock] = relationship()
    camera: Mapped[Camera | None] = relationship(back_populates="rolls")
    tags: Mapped[list[Tag]] = relationship(secondary=roll_tag, order_by="Tag.name")
    development: Mapped[Development | None] = relationship(
        back_populates="roll",
        cascade="all, delete-orphan",
        uselist=False,
        foreign_keys="Development.roll_id",
    )
    prints: Mapped[list[Print]] = relationship(
        back_populates="roll", cascade="all, delete-orphan", order_by="Print.id"
    )
    images: Mapped[list[RollImage]] = relationship(
        back_populates="roll", cascade="all, delete-orphan", order_by="RollImage.position"
    )

    @property
    def is_expired_film(self) -> bool:
        if self.film_expiry is None:
            return False
        ref = self.date_loaded or dt.date.today()
        return self.film_expiry < ref


class RollImage(Base):
    """Additional scans attached to a roll (negatives, contact sheets, …)."""

    __tablename__ = "roll_image"

    id: Mapped[int] = mapped_column(primary_key=True)
    roll_id: Mapped[int] = mapped_column(ForeignKey("roll.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    caption: Mapped[str] = mapped_column(String(200), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    roll: Mapped[Roll] = relationship(back_populates="images")


class Development(Timestamped, Base):
    __tablename__ = "development"

    roll_id: Mapped[int] = mapped_column(
        ForeignKey("roll.id", ondelete="CASCADE"), unique=True, index=True
    )
    date_developed: Mapped[dt.date | None] = mapped_column(Date, default=dt.date.today)
    developer_id: Mapped[int | None] = mapped_column(ForeignKey("chemical.id"), index=True)
    dilution: Mapped[str] = mapped_column(String(40), default="")
    temperature_c: Mapped[float] = mapped_column(Float, default=20.0)
    dev_time_s: Mapped[int] = mapped_column(Integer)
    agitation: Mapped[str] = mapped_column(Text, default="")
    presoak_s: Mapped[int | None] = mapped_column(Integer)
    stop_chemical_id: Mapped[int | None] = mapped_column(ForeignKey("chemical.id"), index=True)
    stop_time_s: Mapped[int | None] = mapped_column(Integer)
    rinse_time_s: Mapped[int | None] = mapped_column(Integer)
    fixer_id: Mapped[int | None] = mapped_column(ForeignKey("chemical.id"), index=True)
    fixer_dilution: Mapped[str] = mapped_column(String(40), default="")
    fix_time_s: Mapped[int | None] = mapped_column(Integer)
    wash_time_s: Mapped[int | None] = mapped_column(Integer)
    wash_method: Mapped[str] = mapped_column(String(200), default="")
    wetting_agent_id: Mapped[int | None] = mapped_column(ForeignKey("chemical.id"), index=True)
    wetting_time_s: Mapped[int | None] = mapped_column(Integer)
    tank: Mapped[str] = mapped_column(String(200), default="")
    result_rating: Mapped[int | None] = mapped_column(Integer)

    roll: Mapped[Roll] = relationship(back_populates="development", foreign_keys=[roll_id])
    developer: Mapped[Chemical | None] = relationship(foreign_keys=[developer_id])
    stop_chemical: Mapped[Chemical | None] = relationship(foreign_keys=[stop_chemical_id])
    fixer: Mapped[Chemical | None] = relationship(foreign_keys=[fixer_id])
    wetting_agent: Mapped[Chemical | None] = relationship(foreign_keys=[wetting_agent_id])
    developed_with_rolls: Mapped[list[Roll]] = relationship(
        secondary=development_roll, order_by="Roll.code"
    )


# --------------------------------------------------------------------------- prints


class Print(Timestamped, Base):
    __tablename__ = "print"

    roll_id: Mapped[int] = mapped_column(ForeignKey("roll.id", ondelete="CASCADE"), index=True)
    frame: Mapped[str] = mapped_column(String(20), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    date_printed: Mapped[dt.date | None] = mapped_column(Date, default=dt.date.today)
    paper_id: Mapped[int | None] = mapped_column(ForeignKey("paper.id"), index=True)
    paper_size: Mapped[str] = mapped_column(String(40), default="")
    enlarger: Mapped[str] = mapped_column(String(100), default="")
    enlarging_lens: Mapped[str] = mapped_column(String(100), default="")
    aperture: Mapped[str] = mapped_column(String(20), default="")
    head_height_cm: Mapped[float | None] = mapped_column(Float)
    contrast_method: Mapped[ContrastMethod] = mapped_column(
        enum_col(ContrastMethod), default=ContrastMethod.SINGLE_FILTER
    )
    developer_id: Mapped[int | None] = mapped_column(ForeignKey("chemical.id"), index=True)
    dev_dilution: Mapped[str] = mapped_column(String(40), default="")
    dev_time_s: Mapped[int | None] = mapped_column(Integer)
    dev_temperature_c: Mapped[float | None] = mapped_column(Float)
    stop_chemical_id: Mapped[int | None] = mapped_column(ForeignKey("chemical.id"), index=True)
    stop_time_s: Mapped[int | None] = mapped_column(Integer)
    fixer_id: Mapped[int | None] = mapped_column(ForeignKey("chemical.id"), index=True)
    fixer_dilution: Mapped[str] = mapped_column(String(40), default="")
    fix_time_s: Mapped[int | None] = mapped_column(Integer)
    wash_time_s: Mapped[int | None] = mapped_column(Integer)
    toning: Mapped[str] = mapped_column(String(200), default="")
    is_final: Mapped[bool] = mapped_column(default=False)
    rating: Mapped[int | None] = mapped_column(Integer)
    image: Mapped[str | None] = mapped_column(String(255))
    is_demo: Mapped[bool] = mapped_column(default=False, index=True)

    roll: Mapped[Roll] = relationship(back_populates="prints")
    paper: Mapped[Paper | None] = relationship()
    developer: Mapped[Chemical | None] = relationship(foreign_keys=[developer_id])
    stop_chemical: Mapped[Chemical | None] = relationship(foreign_keys=[stop_chemical_id])
    fixer: Mapped[Chemical | None] = relationship(foreign_keys=[fixer_id])
    exposures: Mapped[list[PrintExposure]] = relationship(
        back_populates="print",
        cascade="all, delete-orphan",
        order_by="PrintExposure.position",
    )


class PrintExposure(Base):
    __tablename__ = "print_exposure"

    id: Mapped[int] = mapped_column(primary_key=True)
    print_id: Mapped[int] = mapped_column(ForeignKey("print.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    filter_grade: Mapped[str] = mapped_column(String(8), default="none")
    seconds: Mapped[float] = mapped_column(Float, default=0.0)
    aperture: Mapped[str] = mapped_column(String(20), default="")
    purpose: Mapped[ExposurePurpose] = mapped_column(
        enum_col(ExposurePurpose), default=ExposurePurpose.BASE
    )
    note: Mapped[str] = mapped_column(String(200), default="")

    print: Mapped[Print] = relationship(back_populates="exposures")
