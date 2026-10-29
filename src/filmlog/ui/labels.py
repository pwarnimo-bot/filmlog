"""Translatable labels for enum values."""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QCoreApplication

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


def _t(text: str) -> str:
    return QCoreApplication.translate("labels", text)


def _labels() -> dict[StrEnum, str]:
    return {
        FilmType.BW_NEGATIVE: _t("B&W negative"),
        FilmType.BW_REVERSAL: _t("B&W reversal"),
        FilmType.BW_CHROMOGENIC: _t("B&W chromogenic (C-41)"),
        FilmType.COLOUR_NEGATIVE: _t("Colour negative"),
        FilmType.COLOUR_SLIDE: _t("Colour slide"),
        FilmType.OTHER: _t("Other"),
        ChemicalKind.FILM_DEVELOPER: _t("Film developer"),
        ChemicalKind.PAPER_DEVELOPER: _t("Paper developer"),
        ChemicalKind.STOP_BATH: _t("Stop bath"),
        ChemicalKind.FIXER: _t("Fixer"),
        ChemicalKind.WETTING_AGENT: _t("Wetting agent"),
        ChemicalKind.WASHING_AID: _t("Hypo clear / washing aid"),
        ChemicalKind.TONER: _t("Toner"),
        ChemicalKind.OTHER: _t("Other"),
        ChemicalForm.LIQUID: _t("Liquid"),
        ChemicalForm.POWDER: _t("Powder"),
        PaperBase.RC: _t("RC"),
        PaperBase.FB: _t("FB"),
        ContrastType.VARIABLE: _t("Variable contrast"),
        ContrastType.GRADED: _t("Graded"),
        PaperSurface.GLOSSY: _t("Glossy"),
        PaperSurface.PEARL: _t("Pearl"),
        PaperSurface.SATIN: _t("Satin"),
        PaperSurface.LUSTRE: _t("Lustre"),
        PaperSurface.SEMI_MATT: _t("Semi-matt"),
        PaperSurface.MATT: _t("Matt"),
        PaperSurface.OTHER: _t("Other"),
        PaperTone.NEUTRAL: _t("Neutral"),
        PaperTone.WARM: _t("Warm"),
        PaperTone.COOL: _t("Cool"),
        CameraType.SLR: _t("SLR"),
        CameraType.RANGEFINDER: _t("Rangefinder"),
        CameraType.TLR: _t("TLR"),
        CameraType.MEDIUM_FORMAT_SLR: _t("Medium-format SLR"),
        CameraType.VIEWFINDER: _t("Viewfinder / compact"),
        CameraType.LARGE_FORMAT: _t("Large format"),
        CameraType.OTHER: _t("Other"),
        FilmFormat.F135: "135",
        FilmFormat.F120_645: "120 6×4.5",
        FilmFormat.F120_66: "120 6×6",
        FilmFormat.F120_67: "120 6×7",
        FilmFormat.F120_69: "120 6×9",
        FilmFormat.F4X5: "4×5",
        FilmFormat.F5X7: "5×7",
        FilmFormat.F8X10: "8×10",
        FilmFormat.OTHER: _t("Other"),
        CameraStatus.ACTIVE: _t("Active"),
        CameraStatus.RETIRED: _t("Retired"),
        CameraStatus.SOLD: _t("Sold"),
        CameraStatus.BROKEN: _t("Broken"),
        RollStatus.LOADED: _t("Loaded"),
        RollStatus.EXPOSED: _t("Exposed"),
        RollStatus.DEVELOPED: _t("Developed"),
        ContrastMethod.SINGLE_FILTER: _t("Single filter"),
        ContrastMethod.SPLIT_GRADE: _t("Split grade"),
        ContrastMethod.GRADED_PAPER: _t("Graded paper"),
        ContrastMethod.NO_FILTER: _t("No filter"),
        ExposurePurpose.BASE: _t("Base"),
        ExposurePurpose.SOFT: _t("Soft"),
        ExposurePurpose.HARD: _t("Hard"),
        ExposurePurpose.DODGE: _t("Dodge"),
        ExposurePurpose.BURN: _t("Burn"),
        ExposurePurpose.FLASH: _t("Flash"),
    }


def label(value: StrEnum | None) -> str:
    if value is None:
        return ""
    return _labels().get(value, str(value.value))


def tr(text: str) -> str:
    """Translate a services-layer string (e.g. badge text) in the "labels" context."""
    return _t(text)
